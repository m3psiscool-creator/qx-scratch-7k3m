"""Strategy analytics: what each placement/elim is worth, what finishers actually did, pace curves,
safety margins and the rank ladder. Everything is derived from data the collector already stores."""
import bisect
import math
import statistics
import time
from statistics import NormalDist

from . import classify, config, insights, model, rules, service, storage

PLACE, ELIM, WIN = rules.STATS
BANDS = [(1, 10), (11, 50), (51, 100), (101, 250), (251, 500), (501, 1000)]
PLACE_BUCKETS = [("1st", 1, 1), ("2-3", 2, 3), ("4-5", 4, 5), ("6-10", 6, 10), ("11-15", 11, 15),
                 ("16-25", 16, 25), ("26+", 26, 999)]
ELIM_BUCKETS = [("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5", 5, 5), ("6+", 6, 999)]
LADDER_RANKS = [1, 5, 10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000, 7500, 10000]
Z95 = 1.645


def _target(window_id):
    t = storage.get_window(window_id)
    if not t:
        raise ValueError("Unknown window")
    return t


def _gp(rl, p, e, w):
    return rules.game_points(rl, {PLACE: p, ELIM: e, WIN: w})


def _rules_of(target, refs=()):
    rl = (target.get("meta") or {}).get("rules")
    if rl:
        return rl, True
    for r in refs:
        if (r.get("meta") or {}).get("rules"):
            return r["meta"]["rules"], False
    return None, False


# ---------------------------------------------------------------- reference events
def _refs(target, n=1):
    """Finished events of the same gamemode with per-game history, closest first. A finished target is its own reference."""
    out = []
    if target["final"] and len(target.get("sessions") or []) >= 300:
        out.append(target)
    if len(out) >= n:
        return out[:n]
    meta = target.get("meta") or {}
    cands = [w for w in storage.windows(final=True, category=classify.of(target), light=True)
             if w["window_id"] != target["window_id"] and len(w["points"]) >= 900]
    cands.sort(key=lambda w: ((w["region"] != target["region"]),          # same region first, then same format, then same game count
                              (w["meta"].get("format") != meta.get("format")),
                              (w["meta"].get("match_cap") != meta.get("match_cap")), -w["end"]))
    for c in cands:
        if len(out) >= n:
            break
        full = storage.get_window(c["window_id"])
        if full and len(full.get("sessions") or []) >= 300:
            out.append(full)
    return out


def _ref_info(ref):
    return {"window_id": ref["window_id"], "name": service.pretty(ref.get("event_id") or "", ref["window_id"]),
            "region": ref["region"], "end": ref["end"], "players": len(ref["sessions"])}


def _games(ref, rl, lobby):
    """Per ranked player: that player's games in time order as (placement, elims, win, points, elim pts, win pts)."""
    src = model.rescale_placements(ref, lobby) if lobby else ref
    out = []
    for sess in src["sessions"]:
        gs = sorted((g for g in sess if g and len(g) >= 3), key=lambda g: g[3] if len(g) > 3 and g[3] else 0)
        row = []
        for g in gs:
            p, e, w = g[0], g[1], g[2]
            pts = _gp(rl, p, e, w)
            ep = pts - _gp(rl, p, 0, w)
            wp = pts - _gp(rl, p, e, 0)
            row.append((p, e, w, pts, max(ep, 0), max(wp, 0)))
        out.append(row)
    return out


# ---------------------------------------------------------------- scoring value
def scoring(window_id):
    t = _target(window_id)
    rl, own = _rules_of(t)
    if not rl:
        refs = _refs(t, 1)
        rl, own = _rules_of(t, refs)
    if not rl:
        raise ValueError("Epic has not published the scoring rules for this event yet.")
    place_rule = next((r for r in rl if r[0] == PLACE), None)
    last = place_rule[2][-1][0] if place_rule else 25
    place = [_gp(rl, p, 0, 0) for p in range(1, last + 1)]
    elim = [_gp(rl, last + 1, e, 0) for e in range(0, 16)]
    win_bonus = _gp(rl, 1, 0, 1) - _gp(rl, 1, 0, 0)
    first_elim = elim[1] - elim[0]
    per_elim = first_elim
    plateau = next((e for e in range(1, len(elim)) if elim[e] == elim[e - 1]), None)
    capped = plateau is not None and first_elim > 0
    elim_cap = plateau - 1 if capped else len(elim) - 1   # elims beyond this score nothing
    marks = [p for p in (1, 2, 3, 5, 10, 15, 25) if p <= last]
    breakeven = []
    for p in marks:
        pts = place[p - 1] + (win_bonus if p == 1 else 0)
        el = round(pts / per_elim, 1) if per_elim else None
        breakeven.append({"placement": p, "points": pts, "elims": el, "reachable": bool(el is not None and (not capped or el <= elim_cap))})
    meta = t.get("meta") or {}
    return {"window_id": window_id, "own_rules": own, "placement": place, "elim": elim, "win_bonus": win_bonus,
            "per_elim": round(per_elim, 2), "elim_cap": elim_cap, "elim_capped": capped, "last_paid_place": last, "breakeven": breakeven,
            "match_cap": meta.get("match_cap"), "lobby": meta.get("lobby"), "text": rules.describe(rl, meta.get("match_cap"))}


# ---------------------------------------------------------------- what finishers did
def _hist(vals, buckets):
    n = len(vals) or 1
    return [round(sum(1 for v in vals if a <= v <= b) / n, 4) for _, a, b in buckets]


def _stride(seq, k):
    if len(seq) <= k:
        return list(seq)
    step = len(seq) / k
    return [seq[int(i * step)] for i in range(k)]


def _band_stats(pg, a, b, with_extra=False):
    rows = [g for g in pg[a - 1:b] if g]
    games = [x for g in rows for x in g]
    n = len(games)
    if not n:
        return None
    pts = [x[3] for x in games]
    tot = sum(pts) or 1
    out = {"from": a, "to": b, "players": len(rows), "games": n,
           "games_per_player": round(n / len(rows), 1),
           "pts_per_game": round(tot / n, 2), "sd": round(statistics.pstdev(pts), 2),
           "avg_place": round(sum(x[0] for x in games) / n, 2),
           "elims_per_game": round(sum(x[1] for x in games) / n, 2),
           "win_rate": round(sum(1 for x in games if x[2]) / n, 4),
           "top5_rate": round(sum(1 for x in games if x[0] <= 5) / n, 4),
           "top10_rate": round(sum(1 for x in games if x[0] <= 10) / n, 4),
           "split": {"elim": round(sum(x[4] for x in games) / tot, 4), "win": round(sum(x[5] for x in games) / tot, 4)},
           "place_hist": _hist([x[0] for x in games], PLACE_BUCKETS),
           "elim_hist": _hist([x[1] for x in games], ELIM_BUCKETS),
           "sample": _stride([[x[3], x[0]] for x in games], 300),
           "players_pts": [[[x[3], x[0]] for x in g] for g in _stride(rows, 80)],
           "players_meta": [[round(sum(x[0] for x in g) / len(g), 2), round(sum(x[1] for x in g) / len(g), 2)] for g in _stride(rows, 80)]}
    out["split"]["place"] = round(max(0.0, 1 - out["split"]["elim"] - out["split"]["win"]), 4)
    if with_extra:
        longest = max(len(g) for g in rows)
        by = []
        for k in range(longest):
            v = [g[k][3] for g in rows if len(g) > k]
            if len(v) >= 5:
                by.append({"game": k + 1, "pts": round(sum(v) / len(v), 2), "n": len(v)})
        out["by_game"] = by
        out["scatter"] = _stride([[round(sum(x[0] for x in g) / len(g), 2), round(sum(x[1] for x in g) / len(g), 2),
                                   round(sum(x[3] for x in g) / len(g), 1)] for g in rows], 160)
    return out


def _focus(rank):
    rank = max(1, min(int(rank), 1000))
    w = max(8, round(rank * 0.12))
    return max(1, rank - w), min(1000, rank + w)


def profile(window_id, rank=None):
    t = _target(window_id)
    goal = (service.goal_of(t.get("meta")) or {}).get("rank") or 100
    asked = int(rank or goal)
    rank = max(1, min(asked, 1000))
    refs = _refs(t, 1)
    if not refs:
        raise ValueError("No finished event of this gamemode has per-game history yet, so there is nothing to compare with.")
    ref = refs[0]
    rl, _ = _rules_of(t, refs)
    if not rl:
        raise ValueError("No scoring rules available for this gamemode.")
    pg = _games(ref, rl, (t.get("meta") or {}).get("lobby"))
    a, b = _focus(rank)
    bands = [s for s in (_band_stats(pg, x, y) for x, y in BANDS) if s]
    focus = _band_stats(pg, a, b, with_extra=True)
    same = ref["window_id"] == t["window_id"]
    note = ("This event's own finishers." if same else
            f"{service.pretty(ref.get('event_id') or '', ref['window_id'])} ({ref['region']}), the closest finished event of this gamemode, re-scored under this event's rules.")
    return {"window_id": window_id, "rank": rank, "asked": asked, "clamped": asked != rank, "ref": _ref_info(ref),
            "own": same, "note": note, "bands": bands, "focus": focus, "place_buckets": [b[0] for b in PLACE_BUCKETS],
            "elim_buckets": [b[0] for b in ELIM_BUCKETS]}


# ---------------------------------------------------------------- pace
def _q(vals, f):
    s = sorted(vals)
    return s[min(len(s) - 1, int(f * len(s)))]


def pace(window_id, rank, target_points=None):
    t = _target(window_id)
    meta = t.get("meta") or {}
    rank = max(1, min(int(rank), 1000))
    refs = _refs(t, 2)
    if not refs:
        raise ValueError("No finished event of this gamemode has per-game history yet.")
    rl, _ = _rules_of(t, refs)
    if not rl:
        raise ValueError("No scoring rules available for this gamemode.")
    a, b = max(1, int(rank * 0.9)), min(1000, int(rank * 1.1) + 1)
    if b - a < 16:
        a, b = max(1, rank - 8), min(1000, rank + 8)
    curves = []
    for ref in refs:
        for row in _games(ref, rl, meta.get("lobby"))[a - 1:b]:
            if row:
                c, s = [], 0
                for x in row:
                    s += x[3]
                    c.append(s)
                curves.append(c)
    cap = meta.get("match_cap") or max(len(c) for c in curves)
    kmax = max((k for k in range(1, cap + 1) if sum(1 for c in curves if len(c) >= k) >= 10), default=0)
    if not kmax:
        raise ValueError("Not enough per-game history near this rank.")
    mid, lo, hi = [], [], []
    for k in range(1, kmax + 1):
        v = [c[k - 1] for c in curves if len(c) >= k]
        mid.append(statistics.median(v))
        lo.append(_q(v, 0.25))
        hi.append(_q(v, 0.75))
    final_est = mid[-1] * cap / kmax
    scale = (target_points / final_est) if target_points and final_est else 1.0
    r = lambda arr: [round(x * scale, 1) for x in arr]
    return {"window_id": window_id, "rank": rank, "band": [a, b], "cap": cap, "kmax": kmax, "players": len(curves),
            "mid": r(mid), "lo": r(lo), "hi": r(hi), "final_est": round(final_est * scale),
            "scaled": bool(target_points), "scale": round(scale, 3), "refs": [_ref_info(x) for x in refs]}


# ---------------------------------------------------------------- safety margin
def safety(window_id, rank):
    t = _target(window_id)
    rank = max(1, min(int(rank), 10000))
    r = service.run_predict(window_id, rank)
    if r.get("final"):
        return {"window_id": window_id, "rank": rank, "final": True, "likely": r["likely"]}
    cur = r.get("current") or (r.get("live") or {}).get("current") or 0
    m = math.log1p(max(r["likely"], 0))
    sd = max((math.log1p(max(r["safe"], 0)) - math.log1p(max(r["low"], 0))) / (2 * Z95), 0.005)
    nd = NormalDist()
    ladder = []
    for conf in (0.5, 0.8, 0.9, 0.95, 0.99):
        ladder.append({"conf": conf, "points": max(round(math.expm1(m + nd.inv_cdf(conf) * sd)), round(cur))})
    lo_x, hi_x = math.expm1(m - 3 * sd), math.expm1(m + 3 * sd)
    curve = []
    for i in range(61):
        x = lo_x + (hi_x - lo_x) * i / 60
        p = 0.0 if x < cur else nd.cdf((math.log1p(max(x, 0)) - m) / sd)
        curve.append([round(x), round(p, 4)])
    drift = None
    try:
        rows = storage.series(window_id)
        if len(rows) >= 3:
            keys = [int(k) for k in rows[-1]["p"]]
            key = str(min(keys, key=lambda k: abs(k - rank)))
            pts = [(x["ts"], x["p"].get(key)) for x in rows if x["p"].get(key) is not None]
            now_ts, now_v = pts[-1]

            def back(h):
                old = [v for ts, v in pts if ts <= now_ts - h * 3600]
                return now_v - old[-1] if old else None
            drift = {"rank_used": int(key), "h1": back(1), "h3": back(3), "h6": back(6)}
    except Exception:
        drift = None
    return {"window_id": window_id, "rank": rank, "final": False, "current": round(cur), "low": max(0, r["low"]),
            "likely": r["likely"], "safe": r["safe"], "sd_pct": round(100 * sd, 1), "mu": round(m, 5), "sd": round(sd, 5), "ladder": ladder, "curve": curve,
            "drift": drift, "method": r.get("method"), "progress": (r.get("live") or {}).get("progress"),
            "history_events": (r.get("prior") or {}).get("n") or r.get("history_events")}


# ---------------------------------------------------------------- which past events count as history
def peers(target, rows, min_same=4, limit=14):
    """Previous events of the same gamemode and format. The same region's events come first; other regions are added
    only when the region has fewer than `min_same`."""
    meta = target.get("meta") or {}
    base = [w for w in rows if w["window_id"] != target["window_id"] and w["family"] == target["family"]
            and classify.of(w) == classify.of(target) and w["end"] <= target["begin"]]
    fmt = [w for w in base if meta.get("format") and (w.get("meta") or {}).get("format") == meta["format"]]
    pool = fmt if len(fmt) >= 2 else base
    reg = sorted([w for w in pool if w["region"] == target["region"]], key=lambda w: -w["end"])
    if len(reg) >= min_same:
        return reg[:limit]
    return (reg + sorted([w for w in pool if w["region"] != target["region"]], key=lambda w: -w["end"]))[:limit]


# ---------------------------------------------------------------- rank ladder
def ladder(window_id):
    t = _target(window_id)
    cat = classify.of(t)
    hist = peers(t, storage.windows(final=True, category=cat, light=True))
    rows = {}
    for w in hist:
        for rk, v in insights.cutoffs(w, LADDER_RANKS).items():
            rows.setdefault(rk, []).append(v)
    hist_out = {str(rk): {"p25": _q(v, 0.25), "median": statistics.median(v), "p75": _q(v, 0.75), "n": len(v)}
                for rk, v in rows.items() if len(v) >= 2}
    th = service.thresholds(window_id)
    cur = {str(k): v for k, v in (th.get("ranks") or {}).items()}
    preds = {}
    if not t["final"]:
        for p in storage.predictions_for(window_id)[::-1]:
            preds.setdefault(str(p["rank"]), {k: p[k] for k in ("low", "likely", "safe")})
    return {"window_id": window_id, "ranks": LADDER_RANKS, "now": cur, "source": th.get("source"),
            "history": hist_out, "events": len(hist), "predicted": preds, "category": cat,
            "same_region": sum(1 for w in hist if w["region"] == t["region"]), "region": t["region"]}


# ---------------------------------------------------------------- tempo: how long a game takes at each placement
def tempo(window_id):
    """Minutes one game takes (queue + time alive) for each finishing placement, from real player histories.

    A player's stored game time is when they were eliminated. The gap between two consecutive stored times
    therefore equals the wait for the next lobby plus how long they survived in that next game, and it depends
    on the placement of the NEXT game (about 18 min for a top-4 finish, about 4 min for dying early), not the previous."""
    t = _target(window_id)
    refs = _refs(t, 2)
    if not refs:
        raise ValueError("No finished event of this gamemode has per-game timing yet.")
    meta = t.get("meta") or {}
    lobbies = [model.observed_lobby(r) or 0 for r in refs]
    lobby = int(meta.get("lobby") or lobbies[0] or 0)
    if not lobby:
        raise ValueError("Lobby size unknown.")
    samples = []   # (placement as a share of the lobby, minutes)
    for ref, rl in zip(refs, lobbies):
        if not rl:
            continue
        for sess in ref["sessions"]:
            gs = sorted((g for g in sess if g and len(g) > 3 and g[3]), key=lambda g: g[3])
            for a, b in zip(gs, gs[1:]):
                d = (b[3] - a[3]) / 60
                if 1 <= d <= 45:           # longer gaps are breaks, not games
                    samples.append((b[0] / rl, d))
    if len(samples) < 500:
        raise ValueError("Not enough per-game timing near this gamemode yet.")
    samples.sort()
    qs = [x[0] for x in samples]
    out = []
    for p in range(1, lobby + 1):
        q, w = p / lobby, 0.03
        while True:
            lo, hi = bisect.bisect_left(qs, q - w), bisect.bisect_right(qs, q + w)
            if hi - lo >= 40 or w >= 0.3:
                break
            w += 0.02
        vals = [samples[i][1] for i in range(lo, hi)] or [samples[-1][1]]
        out.append(round(statistics.median(vals), 1))
    # survival can only get shorter as you place worse: remove noise in the curve
    for i in range(len(out) - 2, -1, -1):
        out[i] = max(out[i], out[i + 1])
    return {"window_id": window_id, "lobby": lobby, "by_place": out, "samples": len(samples),
            "overall": round(statistics.median(d for _, d in samples), 1), "refs": [_ref_info(r) for r in refs]}
