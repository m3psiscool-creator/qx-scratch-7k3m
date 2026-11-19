"""Rank -> points prediction in log1p space.

Prior: recency-weighted points at rank X from comparable finished windows.
Live: current points at rank X scaled to the end of the window.
Combined by inverse variance.
"""
import json
import math
import random
import statistics

from . import classify, rules
import threading

_ctx = threading.local()   # per-request switch: allow similar classes when a class has no history


def approx():
    return getattr(_ctx, 'approx', False)

DECAY = 0.5           # back-test of 250 finished events (scripts/backtest_prestart.py, sweep): 0.5 beat 0.7 (p90 error 27% -> 25%)
BETA_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
Z90 = 1.645
Z80 = 1.2816          # Low = 10th percentile, Safe = 90th: an 80% band (was 90%), so the two ends sit closer together
# Back-test of 500+ finished events: the centre is well calibrated, but the real spread was wider than the model's sd before
# the event and a quarter in (heavy tails), about right at the half, and slightly narrower late. Multiplier on the sd by progress.
BAND_SCALE = [(0.0, 1.05), (0.25, 1.25), (0.5, 0.95), (0.75, 0.90), (1.0, 0.85)]


def band_scale(p):
    p = min(max(p, 0.0), 1.0)
    for (a, x), (b, y) in zip(BAND_SCALE, BAND_SCALE[1:]):
        if p <= b:
            return x + (y - x) * (p - a) / (b - a)
    return BAND_SCALE[-1][1]
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


MIN_SAME_REGION = 8    # fewer previous events than this in the region: other regions are added


def comparable(target, finished):
    """Previous events of the same gamemode AND the same format (game count + scoring rules).
    Same-region events come first (and carry the most weight); other regions are added only when the region has too few.
    When Epic omits the target's scoring rules, use the same class and match cap as a practical fallback."""
    target_meta = target.get("meta") or {}
    target_format = _fmt(target)
    missing_format = target_format is None and target_meta.get("match_cap") is not None
    same = [w for w in finished
            if w["window_id"] != target["window_id"]
            and w["points"] and (
                _fmt(w) == target_format if target_format is not None
                else missing_format and (w.get("meta") or {}).get("match_cap") == target_meta["match_cap"]
            )
            and classify.of(w) == classify.of(target)]
    # Some new formats have no finished events yet (for example, the first
    # Squads Victory Cup). After exhausting the exact class, borrow the closest
    # BR team format with a similar game count rather than returning zero.
    if approx() and len(same) < MIN_SAME_REGION:
        mode_size = {"solo": 1, "duo": 2, "trio": 3, "trios": 3, "squads": 4}
        target_mode = (target_meta.get("mode") or "").lower()
        target_type = target_meta.get("game_type")
        target_cap = target_meta.get("match_cap")
        candidates = [w for w in finished
                      if w["window_id"] != target["window_id"] and w["points"]
                      and classify.of(w) != classify.of(target)
                      and (w.get("meta") or {}).get("game_type") == target_type]
        candidates.sort(key=lambda w: (
            w["region"] != target["region"],
            mode_size.get((w.get("meta") or {}).get("mode"), 9) - mode_size.get(target_mode, 9)
            if mode_size.get((w.get("meta") or {}).get("mode"), 9) >= mode_size.get(target_mode, 9)
            else mode_size.get(target_mode, 9) - mode_size.get((w.get("meta") or {}).get("mode"), 9),
            abs(((w.get("meta") or {}).get("match_cap") or 0) - (target_cap or 0)),
            (w.get("meta") or {}).get("stage") != target_meta.get("stage"),
            -w["end"],
        ))
        have = {w["window_id"] for w in same}
        fallback = [w for w in candidates if w["window_id"] not in have]
        same.extend(fallback[:MIN_SAME_REGION - len(same)])
    reg = sorted([w for w in same if w["region"] == target["region"]], key=lambda w: w["end"], reverse=True)
    if len(reg) >= MIN_SAME_REGION:
        return reg
    return reg + sorted([w for w in same if w["region"] != target["region"]], key=lambda w: w["end"], reverse=True)


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


def expected_field(target, pool):
    """Teams to expect: the target's own count when known, else the median of its most recent comparable events."""
    n = target.get("entrants")
    if n:
        return n
    sizes = [w["entrants"] for w in pool[:6] if w.get("entrants")]
    return statistics.median(sizes) if sizes else None


def prior(target, finished, rank, entrants=None):
    pool = comparable(target, finished)
    field = entrants or expected_field(target, pool)
    if field:
        # A 100-team final says nothing about a 3000-team cup: keep events of a similar size when there are enough,
        # and never ask for a place deeper than the field (that is last place).
        near = [w for w in pool if w.get("entrants") and 0.5 <= w["entrants"] / field <= 2]
        if len(near) >= 3:
            pool = near
        rank = max(1, min(rank, int(field)))
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
    if w["window_id"] not in _timed_cache and w.get("timed") is not None:
        b = w["begin"]    # stored compactly as [seconds since the window started, points, ...]
        _timed_cache[w["window_id"]] = [[(b + row[i], row[i + 1]) for i in range(0, len(row), 2)]
                                        for row in w["timed"]]
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
            if w["window_id"] != target["window_id"] and _has_timed(w)
            and (w.get("meta") or {}).get("match_cap") == meta.get("match_cap")
            and abs((w["end"] - w["begin"]) - dur) <= 0.25 * dur]
    pool = [w for w in pool if _timing_ok(w)]
    cat = classify.of(target)
    same = [w for w in pool if classify.of(w) == cat]
    if approx() and len(same) < 3:   # explicitly allowed: nearest classes by game type, then any
        same = [w for w in pool if w["meta"].get("game_type") == meta.get("game_type")] or pool
    # same region first, then same format, then newest
    return sorted(same, key=lambda w: (w["region"] != target["region"], _fmt(w) != _fmt(target), -w["end"]))[:limit]


def _has_timed(w):
    """The window carries game-by-game timing (compact timed points, or raw sessions with end times)."""
    if w.get("timed") is not None:
        return len(w["timed"]) >= 300 and any(row for row in w["timed"][:20])
    return len(w.get("sessions") or []) >= 300 and any(len(g) > 3 and g[3] for g in w["sessions"][0][:1])


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
    key = (classify.of(target), meta.get("stage"), rank, len(finished), approx())
    if key in _cal_cache:
        return _cal_cache[key]
    tests = [w for w in finished
             if classify.of(w) == classify.of(target)
             and w["meta"].get("stage") == meta.get("stage")
             and w["meta"].get("rules") and len(w["points"]) >= 900
             and len(w["points"]) >= rank]
    tests = sorted(tests, key=lambda w: w["end"], reverse=True)[:6]
    from . import storage
    tests = storage.attach_sessions(tests)
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
             if len(w.get("points") or []) >= MIN_PLAYERS and classify.of(w) == classify.of(target)]
    if not cands and approx():   # explicitly allowed: other classes with the same team size
        cands = [w for w in finished if len(w.get("points") or []) >= MIN_PLAYERS
                 and (w.get("meta") or {}).get("mode") == meta.get("mode")]
    # Prefer the same game type (Reload/BR) and the same stage (open first round vs later round),
    # then widen. Placements are rescaled to the target lobby size, so widening is safe.
    same_type = [w for w in cands if w["meta"].get("game_type") == meta.get("game_type")]
    same_stage = [w for w in same_type if w["meta"].get("stage") == meta.get("stage")]
    pool = next((c for c in (same_stage, same_type, cands) if c), [])
    pool = sorted(pool, key=lambda w: (w["region"] != target["region"], -w["end"]))[:RESCORE_WINDOWS]
    from . import storage
    pool = [w for w in storage.attach_sessions(pool) if len(w.get("sessions") or []) >= MIN_PLAYERS]
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
    method = ("same-format history" if _fmt(target) is not None
              else "same-mode, same-game-count history (scoring rules unavailable)")
    if not pr or pr["n"] < 2:
        rp = rescored_prior(target, finished, rank, entrants)
        if rp:
            pr, method = rp, "past games re-scored under this event's rules"
    lv = live(target, snapshot, finished, rank, snaps_by_window, now) if snapshot else None
    c = combine([pr, lv])
    if not c:
        return None
    m, sd = c
    prog = (lv or {}).get("progress") or 0.0
    sd *= band_scale(prog)
    f = lambda z: round(math.expm1(z))
    ws = [(name, e) for name, e in (("history", pr), ("live", lv)) if e]
    tot = sum(1 / e["var"] for _, e in ws)
    parts = {name: {"likely": f(e["mean"]), "weight": round(1 / e["var"] / tot, 2)} for name, e in ws}
    return {
        "rank": rank, "low": f(m - Z80 * sd), "likely": f(m), "safe": f(m + Z80 * sd),
        "sd": round(sd, 4), "band": "80%",
        "parts": parts,
        "prior": pr, "live": lv, "method": method if pr else None,
    }
