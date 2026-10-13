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


_timed_cache = {}


def _timed_games(w):
    """Per player: list of (end time, points) per game, scored with the window's own rules."""
    if w["window_id"] not in _timed_cache:
        rl = (w.get("meta") or {}).get("rules") or []
        _timed_cache[w["window_id"]] = [
            [(g[3], rules.game_points(rl, rules.session_stats(g))) for g in p if len(g) > 3 and g[3]]
            for p in w["sessions"]]
    return _timed_cache[w["window_id"]]


def board_at(w, t):
    """Rebuilt leaderboard (points, best first) of a finished window at time t."""
    return sorted((sum(pt for end, pt in p if end <= t) for p in _timed_games(w)), reverse=True)


def shape_pool(target, finished, limit=12):
    """Finished windows that ran like the target (same game count, similar length)."""
    meta = target.get("meta") or {}
    dur = target["end"] - target["begin"]
    pool = [w for w in finished
            if w["window_id"] != target["window_id"] and len(w.get("sessions") or []) >= 300
            and (w.get("meta") or {}).get("match_cap") == meta.get("match_cap")
            and abs((w["end"] - w["begin"]) - dur) <= 0.25 * dur
            and any(len(g) > 3 and g[3] for g in w["sessions"][0][:1])]
    pool = [w for w in pool if _timing_ok(w)]
    same = [w for w in pool if w["meta"].get("game_type") == meta.get("game_type")]
    return sorted(same if len(same) >= 3 else pool, key=lambda w: w["end"], reverse=True)[:limit]


def _timing_ok(w):
    """Game timestamps must fit the scheduled window (some events ran off their listed times)."""
    ends = [e for p in _timed_games(w) for e, _ in p]
    if not ends:
        return False
    dur = w["end"] - w["begin"]
    late = sum(1 for e in ends if e > w["begin"] + 0.5 * dur) / len(ends)
    inside = sum(1 for e in ends if w["begin"] <= e <= w["end"] + 1800) / len(ends)
    return late >= 0.25 and inside >= 0.95


def reconstructed_growth(target, snap, finished, rank):
    """log(final / now) at the same point in time of the window, seen in similar past windows."""
    after = snap["ts"] - target["end"]          # seconds past the end: games are finishing
    p = min(max((snap["ts"] - target["begin"]) / max(target["end"] - target["begin"], 1), 0.0), 1.0)
    out = []
    for w in shape_pool(target, finished):
        if rank > len(w["points"]) * 0.5:
            continue
        t = w["end"] + after if after > 0 else w["begin"] + p * (w["end"] - w["begin"])
        cur = board_at(w, t)
        if rank <= len(cur) and cur[rank - 1] > 0:
            out.append(_l(w["points"][rank - 1]) - _l(cur[rank - 1]))
    return p, out


def live(target, snap, finished, rank, snaps_by_window=None, now=None):
    cur = _at(snap["points"], rank)
    if cur is None:
        return None
    from . import sim  # player-by-player simulation (preferred)
    est = sim.live_estimate(target, snap, finished, rank)
    if est:
        return est
    p_t, rg = reconstructed_growth(target, snap, finished, rank)
    if len(rg) >= 3 and p_t >= 0.03:
        g = statistics.mean(rg)
        var = max(statistics.pvariance(rg) * (1 + 1 / len(rg)), 0.05 ** 2)
        return {"mean": _l(cur) + g, "var": var, "progress": p_t, "basis": "time (rebuilt from past events)",
                "learned": True, "current": cur, "n": len(rg)}
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


def observed_lobby(w):
    """Highest placement seen in a window's recorded games (about the lobby size)."""
    if len(w.get("sessions") or []) < 100:
        return None
    return max((g[0] for p in w["sessions"] for g in p), default=None)


def lobby_size(w, finished):
    """Teams per lobby: configured table value, else seen in past windows of the same playlist."""
    meta = w.get("meta") or {}
    seen = [observed_lobby(f) for f in finished
            if (f.get("meta") or {}).get("playlist") and
            f["meta"]["playlist"] == meta.get("playlist")]
    seen = [s for s in seen if s]
    return max(seen + [meta.get("lobby") or 0]) or None


def rescale_placements(w, target_lobby):
    """Copy of w whose placements are mapped to a lobby of target_lobby teams."""
    src = (w.get("meta") or {}).get("lobby") or observed_lobby(w)
    if not target_lobby or not src or src == target_lobby:
        return w
    f = target_lobby / src
    sess = [[[max(1, math.ceil(g[0] * f))] + list(g[1:]) for g in p] for p in w["sessions"]]
    return {**w, "sessions": sess, "window_id": f"{w['window_id']}@{target_lobby}"}


def _rescored_games(w, rule_list):
    """Per-player list of per-game points for window w under the target's rules."""
    key = (w["window_id"], json.dumps(rule_list))
    if key not in _game_cache:
        _game_cache[key] = [[rules.game_points(rule_list, rules.session_stats(g)) for g in p]
                            for p in w["sessions"]]
    return _game_cache[key]


_cal_cache = {}


def calibration(target, finished, rank):
    """Leave-one-out back-test of the re-scoring on past windows of the same kind.

    Returns (mean log error, error variance, n); error = actual - predicted in log1p space."""
    meta = target.get("meta") or {}
    key = (meta.get("game_type"), meta.get("mode"), meta.get("stage"), rank, len(finished))
    if key in _cal_cache:
        return _cal_cache[key]
    tests = [w for w in finished
             if (w.get("meta") or {}).get("mode") == meta.get("mode")
             and w["meta"].get("game_type") == meta.get("game_type")
             and w["meta"].get("stage") == meta.get("stage")
             and w["meta"].get("rules") and len(w["sessions"]) >= 900
             and len(w["sessions"]) >= rank]
    tests = sorted(tests, key=lambda w: w["end"], reverse=True)[:6]
    deltas = []
    for t in tests:
        others = [w for w in finished if w["window_id"] != t["window_id"]]
        p = rescored_prior(t, others, rank, t.get("entrants"), calibrate=False)
        if p:
            deltas.append(_l(t["points"][rank - 1]) - p["mean"])
    res = ((statistics.mean(deltas), statistics.pvariance(deltas), len(deltas))
           if len(deltas) >= 4 else (0.0, 0.0, len(deltas)))
    _cal_cache[key] = res
    return res


def rescored_prior(target, finished, rank, entrants=None, calibrate=True):
    """No past window has this format: replay old games under the target's scoring rules.

    Each past player's games are re-scored, M = target game count of them are drawn
    (without replacement) to rebuild a board, and the value at the percentile-matched
    rank is read off. Repeated and averaged over several draws."""
    meta = target.get("meta") or {}
    rule_list, cap = meta.get("rules"), meta.get("match_cap")
    if not rule_list or not cap:
        return None
    cands = [w for w in finished
             if w["sessions"] and len(w["sessions"]) >= MIN_PLAYERS
             and (w.get("meta") or {}).get("mode") == meta.get("mode")]
    # Prefer the same game type (Reload/BR) and the same stage (open first round vs later round),
    # then widen. Placements are rescaled to the target lobby size, so widening is safe.
    same_type = [w for w in cands if w["meta"].get("game_type") == meta.get("game_type")]
    same_stage = [w for w in same_type if w["meta"].get("stage") == meta.get("stage")]
    pool = next((c for c in (same_stage, same_type, cands) if c), [])
    pool = sorted(pool, key=lambda w: w["end"], reverse=True)[:RESCORE_WINDOWS]
    if not pool:
        return None
    if not entrants:
        entrants = statistics.median(w["entrants"] for w in pool if w.get("entrants"))
    target_lobby = lobby_size(target, finished)
    if not target_lobby and pool[0]["meta"].get("game_type") != meta.get("game_type"):
        return None  # unknown lobby size and a different game type: placements aren't comparable
    rng = random.Random(7)
    vals, ws, spread = [], [], []
    for i, w in enumerate(pool):
        r = max(1, round(rank * (w.get("entrants") or entrants) / entrants))
        if r > len(w["sessions"]):
            continue
        scaled = rescale_placements(w, target_lobby)
        # history keeps at most 11 games, so a 12-game target scales up from 11
        games = [g for g in _rescored_games(scaled, rule_list) if len(g) >= cap - 1]
        if len(games) < r:
            continue
        reps = []
        for _ in range(RESCORE_REPS):
            board = sorted(sum(rng.sample(g, min(cap, len(g)))) * cap / min(cap, len(g))
                           for g in games)
            reps.append(_l(board[-r]))
        reps = [x for x in reps if x is not None]
        if reps:
            vals.append(statistics.mean(reps))
            ws.append(DECAY ** i)
            spread.append(statistics.pvariance(reps))
    if not vals:
        return None
    m, var = _wmean_var(vals, ws) if len(vals) > 1 else (vals[0], 0.25 ** 2)
    var = max(var + statistics.mean(spread), RESCORE_SD_FLOOR ** 2)
    bias, cal_var, cal_n = calibration(target, finished, rank) if calibrate else (0.0, 0.0, 0)
    return {"mean": m + bias, "var": var + cal_var, "n": len(vals), "beta": 0.0,
            "entrants": entrants, "bias_corrected": round(math.expm1(bias), 3),
            "backtest_n": cal_n}


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
    ws = [(name, e) for name, e in (("history", pr), ("live", lv)) if e]
    tot = sum(1 / e["var"] for _, e in ws)
    parts = {name: {"likely": f(e["mean"]), "weight": round(1 / e["var"] / tot, 2)} for name, e in ws}
    return {
        "rank": rank, "low": f(m - Z90 * sd), "likely": f(m), "safe": f(m + Z90 * sd),
        "parts": parts,
        "prior": pr, "live": lv, "method": method if pr else None,
    }
