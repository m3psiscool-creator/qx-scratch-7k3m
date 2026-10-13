"""Rank -> points prediction in log1p space.

Prior: recency-weighted points at rank X from comparable finished windows.
Live: current points at rank X scaled to the end of the window.
Combined by inverse variance.
"""
import json
import math
import random
import statistics

from . import rules

DECAY = 0.7
BETA_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
Z90 = 1.645
MIN_VAR = 0.02 ** 2
NAIVE_SD = 0.30      # log-space sd when no snapshots are available
PRIOR_SD_FLOOR = 0.10


def _l(x):
    return math.log1p(max(x, 0.0))


def _at(points, rank):
    """Points at 1-based rank, or None if the board is shorter."""
    return points[rank - 1] if 1 <= rank <= len(points) else None


def _fmt(w):
    return (w.get("meta") or {}).get("format")


def comparable(target, finished):
    """Finished windows with the SAME format (game count + scoring rules)."""
    same = [w for w in finished
            if w["family"] == target["family"] and w["window_id"] != target["window_id"]
            and w["points"] and _fmt(w) == _fmt(target)]
    reg = [w for w in same if w["region"] == target["region"]]
    pool = reg if len(reg) >= 3 else same
    return sorted(pool, key=lambda w: w["end"], reverse=True)


def _wmean_var(vals, weights):
    sw = sum(weights)
    m = sum(v * w for v, w in zip(vals, weights)) / sw
    var = sum(w * (v - m) ** 2 for v, w in zip(vals, weights)) / sw
    n_eff = sw ** 2 / sum(w * w for w in weights)
    var = var * n_eff / max(n_eff - 1, 1) if n_eff > 1 else 0.25 ** 2
    return m, max(var, PRIOR_SD_FLOOR ** 2)


def _prior_vals(pool, rank, entrants, beta):
    vals, ws = [], []
    for i, w in enumerate(pool):
        r = rank
        if entrants and w.get("entrants"):
            r = max(1, round(rank * (w["entrants"] / entrants) ** beta))
        p = _at(w["points"], r)
        if p is not None:
            vals.append(_l(p))
            ws.append(DECAY ** i)
    return vals, ws


def choose_beta(pool, rank):
    """Leave-one-out choice of the entrant exponent; needs 5+ windows."""
    if len(pool) < 5:
        return 0.0
    best, best_err = 0.0, float("inf")
    for beta in BETA_GRID:
        err, n = 0.0, 0
        for i, held in enumerate(pool):
            rest = pool[:i] + pool[i + 1:]
            vals, ws = _prior_vals(rest, rank, held.get("entrants"), beta)
            actual = _at(held["points"], rank)
            if len(vals) < 2 or actual is None:
                continue
            m = sum(v * w for v, w in zip(vals, ws)) / sum(ws)
            err += (m - _l(actual)) ** 2
            n += 1
        if n and err / n < best_err:
            best, best_err = beta, err / n
    return best


def prior(target, finished, rank, entrants=None):
    pool = comparable(target, finished)
    beta = choose_beta(pool, rank)
    vals, ws = _prior_vals(pool, rank, entrants, beta)
    if not vals:
        return None
    m, var = _wmean_var(vals, ws)
    return {"mean": m, "var": var, "n": len(vals), "beta": beta}


def _near(arr, rank, width=10):
    lo, hi = max(0, rank - 1 - width), min(len(arr), rank + width)
    return arr[lo:hi]


def progress(target, snap, rank, pool, now=None):
    """Fraction of the window done, 0-1. Games near rank X, else elapsed time."""
    now = now if now is not None else snap["ts"]
    time_p = (now - target["begin"]) / max(target["end"] - target["begin"], 1)
    time_p = min(max(time_p, 0.0), 1.0)
    cur = [g for g in _near(snap["games"], rank) if g]
    tot = [statistics.mean(x) for x in
           (_near(w["games"], rank) for w in pool if w["games"]) if x and statistics.mean(x) > 0]
    if cur and tot:
        return min(max(statistics.mean(cur) / statistics.median(tot), 0.01), 1.0), "games"
    return max(time_p, 0.01), "time"


def live(target, snap, finished, rank, snaps_by_window=None, now=None):
    cur = _at(snap["points"], rank)
    if cur is None:
        return None
    pool = comparable(target, finished)
    p, basis = progress(target, snap, rank, pool, now)
    growth = []
    for w in pool:
        final = _at(w["points"], rank)
        if final is None:
            continue
        for s in (snaps_by_window or {}).get(w["window_id"], []):
            sp, _ = progress(w, s, rank, pool, s["ts"])
            sc = _at(s["points"], rank)
            if abs(sp - p) <= 0.05 and sc:
                growth.append(_l(final) - _l(sc))
    if len(growth) >= 3:
        g = statistics.mean(growth)
        var = max(statistics.pvariance(growth) / len(growth) + statistics.pvariance(growth), MIN_VAR)
        learned = True
    else:
        # naive: linear extrapolation, wide band that shrinks as the window progresses
        g = math.log(1 / p) if cur else 0.0
        var = (NAIVE_SD * (1 - p) + 0.05) ** 2
        learned = False
    return {"mean": _l(cur) + g, "var": var, "progress": p, "basis": basis,
            "learned": learned, "current": cur}


def combine(estimates):
    est = [e for e in estimates if e]
    if not est:
        return None
    w = [1 / e["var"] for e in est]
    m = sum(wi * e["mean"] for wi, e in zip(w, est)) / sum(w)
    return m, math.sqrt(1 / sum(w))


RESCORE_WINDOWS = 8
RESCORE_REPS = 20
RESCORE_SD_FLOOR = 0.12
MIN_PLAYERS = 100
_game_cache = {}


def _rescored_games(w, rule_list):
    """Per-player list of per-game points for window w under the target's rules."""
    key = (w["window_id"], json.dumps(rule_list))
    if key not in _game_cache:
        _game_cache[key] = [[rules.game_points(rule_list, rules.session_stats(g)) for g in p]
                            for p in w["sessions"]]
    return _game_cache[key]


def rescored_prior(target, finished, rank, entrants=None):
    """No past window has this format: replay old games under the target's scoring rules.

    Each past player's games are re-scored, M = target game count of them are drawn
    (without replacement) to rebuild a board, and the value at the percentile-matched
    rank is read off. Repeated and averaged over several draws."""
    meta = target.get("meta") or {}
    rule_list, cap = meta.get("rules"), meta.get("match_cap")
    if not rule_list or not cap:
        return None
    pool = [w for w in finished
            if w["family"] == target["family"] and w["sessions"] and len(w["sessions"]) >= MIN_PLAYERS
            and (w.get("meta") or {}).get("mode") == meta.get("mode")]
    pool = sorted(pool, key=lambda w: w["end"], reverse=True)[:RESCORE_WINDOWS]
    if not pool:
        return None
    if not entrants:
        entrants = statistics.median(w["entrants"] for w in pool if w.get("entrants"))
    rng = random.Random(7)
    vals, ws, spread = [], [], []
    for i, w in enumerate(pool):
        r = max(1, round(rank * (w.get("entrants") or entrants) / entrants))
        if r > len(w["sessions"]):
            continue
        games = [g for g in _rescored_games(w, rule_list) if g]
        reps = []
        for _ in range(RESCORE_REPS):
            board = sorted((sum(rng.sample(g, cap)) if len(g) >= cap
                            else sum(g) * cap / len(g)) for g in games)
            reps.append(_l(board[-r]) if r <= len(board) else None)
        reps = [x for x in reps if x is not None]
        if reps:
            vals.append(statistics.mean(reps))
            ws.append(DECAY ** i)
            spread.append(statistics.pvariance(reps))
    if not vals:
        return None
    m, var = _wmean_var(vals, ws) if len(vals) > 1 else (vals[0], 0.25 ** 2)
    var = max(var + statistics.mean(spread), RESCORE_SD_FLOOR ** 2)
    return {"mean": m, "var": var, "n": len(vals), "beta": 0.0, "entrants": entrants}


def predict(target, finished, rank, entrants=None, snapshot=None, snaps_by_window=None, now=None):
    pr = prior(target, finished, rank, entrants)
    method = "same-format history"
    if not pr or pr["n"] < 2:
        rp = rescored_prior(target, finished, rank, entrants)
        if rp:
            pr, method = rp, "past games re-scored under this event's rules"
    lv = live(target, snapshot, finished, rank, snaps_by_window, now) if snapshot else None
    c = combine([pr, lv])
    if not c:
        return None
    m, sd = c
    f = lambda z: round(math.expm1(z))
    return {
        "rank": rank, "low": f(m - Z90 * sd), "likely": f(m), "safe": f(m + Z90 * sd),
        "prior": pr, "live": lv, "method": method if pr else None,
    }
