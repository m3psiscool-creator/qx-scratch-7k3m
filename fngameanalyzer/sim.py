"""Player-by-player simulation of a live leaderboard.

Every player on the live board is replayed forward using what happened to *comparable players in
comparable past events at the same moment*: players with the same number of games played and a
similar points-per-game. That captures, from data, how many more games people get (including the
last queue that starts before the cutoff and finishes after it), how many points those games are
worth (the per-game cap, regression to the mean) and that players far behind rarely catch up."""
import math

import numpy as np

from . import model

BUCKETS = 10
MIN_N = 30


class Tables:
    def __init__(self, pool, p, after):
        """pool: finished windows; p: fraction of the window elapsed; after: seconds past the end."""
        self.scale_nadd = after <= 0   # after the end only in-flight games remain: no pace scaling
        g_all, m_all, nadd, adds = [], [], [], []
        for w in pool:
            t = w["end"] + after if after > 0 else w["begin"] + p * (w["end"] - w["begin"])
            for games in model._timed_games(w):
                before = [pt for e, pt in games if e <= t]
                later = [pt for e, pt in games if e > t]
                g_all.append(len(before))
                m_all.append(sum(before) / len(before) if before else 0.0)
                nadd.append(len(later))
                adds.append(later)
        g_all, m_all, nadd = np.array(g_all), np.array(m_all), np.array(nadd)
        self.g_pos = np.sort(g_all[g_all > 0])
        self.nadd_by_g = {int(gv): nadd[g_all == gv] for gv in np.unique(g_all)}
        has = g_all > 0
        self.edges = np.quantile(m_all[has], np.linspace(0, 1, BUCKETS + 1)[1:-1]) if has.any() else np.array([])
        b = np.searchsorted(self.edges, m_all, side="right")
        self.pts = [np.array([x for i in np.where(has & (b == k))[0] for x in adds[i]], dtype=float)
                    for k in range(BUCKETS)]
        self.gs = sorted(self.nadd_by_g)

    def nadd_for(self, gv):
        arr = self.nadd_by_g.get(int(gv))
        if arr is not None and len(arr) >= MIN_N:
            return arr
        for gg in sorted(self.gs, key=lambda x: abs(x - gv)):
            if len(self.nadd_by_g[gg]) >= MIN_N:
                return self.nadd_by_g[gg]
        return np.array([0])


def simulate(P, g, tables, ranks, S=200, seed=0, cap=None, pace=True, m_eff=None, full=False):
    """P, g: points and games per player. Returns {rank: array of S simulated final scores}.

    pace: this event may run faster or slower than the comparison events. A player's games are
    matched by *standing* (quantile among players) and the games still to come are scaled by the
    ratio of typical games played so far."""
    rng = np.random.default_rng(seed)
    P, g = np.asarray(P, float), np.asarray(g, int)
    n = len(P)
    m = np.divide(P, g, out=np.zeros(n), where=g > 0) if m_eff is None else np.asarray(m_eff, float)
    pos = np.sort(g[g > 0])
    ratio = 1.0
    g_eq = g.copy()
    if pace and len(pos) and len(tables.g_pos):
        ratio = float(np.median(pos) / max(np.median(tables.g_pos), 1e-9))
        q = np.searchsorted(pos, g, side="right") / len(pos)          # live standing of each player
        g_eq = np.where(g > 0, np.rint(np.quantile(tables.g_pos, np.clip(q, 0, 1))), 0).astype(int)
    nadd = np.zeros((n, S), dtype=np.int16)
    for gv in np.unique(g_eq):
        idx = np.where(g_eq == gv)[0]
        draw = rng.choice(tables.nadd_for(gv), size=(len(idx), S))
        if pace and ratio != 1.0 and tables.scale_nadd:
            draw = np.rint(draw * ratio)
        nadd[idx] = draw
    if cap:
        nadd = np.minimum(nadd, np.maximum(cap - g, 0)[:, None])
    maxk = int(nadd.max()) if nadd.size else 0
    add = np.zeros((n, S))
    bidx = np.searchsorted(tables.edges, m, side="right")
    for b in np.unique(bidx):
        pts = tables.pts[b]
        idx = np.where(bidx == b)[0]
        if len(pts) == 0 or maxk == 0:
            continue
        draws = rng.choice(pts, size=(len(idx), S, maxk))
        mask = np.arange(maxk)[None, None, :] < nadd[idx][:, :, None]
        add[idx] = (draws * mask).sum(axis=2)
    last_info["games_left_top200"] = float(nadd[:200].mean()) if nadd.size else 0.0
    final = P[:, None] + add
    if full:
        return final
    final.sort(axis=0)
    return {r: final[-r, :] for r in ranks if r <= n}


_cal = {}
last_info = {}
_hist = {}
PRIOR_GAMES = 2.0     # pseudo-games of evidence per past event
MAX_PRIOR_GAMES = 6.0


def history_ratios(target, finished):
    """account -> list of (skill ratio, games): points per game relative to that event's field,
    from earlier finished events of the SAME class."""
    from . import classify
    cat = classify.of(target)
    key = (cat, round(target["begin"]), len(finished))
    if key in _hist:
        return _hist[key]
    out = {}
    for h in finished:
        if classify.of(h) != cat or h["window_id"] == target["window_id"] or h["end"] >= target["begin"]:
            continue
        if not h.get("players") or not h.get("sessions"):
            continue
        tg = model._timed_games(h)
        means = [(sum(pt for _, pt in gs) / len(gs)) if gs else None for gs in tg]
        vals = [m for m in means if m]
        if len(vals) < 100:
            continue
        mu = float(np.mean(vals))
        for i, accts in enumerate(h["players"]):
            if i < len(means) and means[i]:
                for a in accts:
                    out.setdefault(a, []).append((means[i] / mu, len(tg[i])))
    _hist[key] = out
    return out


def skill_rates(P, g, players, hist):
    """Blend each entry's points-per-game so far with what their past results in this class say."""
    P, g = np.asarray(P, float), np.asarray(g, int)
    n = len(P)
    m = np.divide(P, g, out=np.zeros(n), where=g > 0)
    live = m[g > 0]
    if not len(live) or not hist:
        return m, 0
    mu = float(live.mean())
    m_eff = m.copy()
    used = 0
    for i in range(n):
        rs = [r for a in players[i] for r in hist.get(a, [])]
        if not rs or g[i] == 0:
            continue
        ratio = float(np.mean([r for r, _ in rs]))
        k = min(MAX_PRIOR_GAMES, PRIOR_GAMES * len(rs) / max(1, len(players[i])))
        m_eff[i] = (k * ratio * mu + g[i] * m[i]) / (k + g[i])
        used += 1
    return m_eff, used



def _state(w, t):
    tg = model._timed_games(w)
    P = np.array([sum(pt for e, pt in gs if e <= t) for gs in tg], float)
    g = np.array([sum(1 for e, pt in gs if e <= t) for gs in tg], int)
    return P, g


def calibration(pool, p, after, rank):
    """Leave-one-out back-test: simulate each past window from its own mid-event state."""
    key = (tuple(sorted(w["window_id"] for w in pool)), round(p, 2), round(after / 300), rank)
    if key in _cal:
        return _cal[key]
    errs = []
    for w in pool:
        others = [x for x in pool if x is not w]
        if len(others) < 2 or rank > len(w["points"]) * 0.5:
            continue
        t = w["end"] + after if after > 0 else w["begin"] + p * (w["end"] - w["begin"])
        P, g = _state(w, t)
        sims = simulate(P, g, Tables(others, p, after), [rank], S=80, cap=w["meta"].get("match_cap"))
        if rank in sims:
            errs.append(math.log1p(w["points"][rank - 1]) - math.log1p(float(np.median(sims[rank]))))
    res = (float(np.mean(errs)), float(np.var(errs)), len(errs)) if len(errs) >= 4 else (0.0, 0.0, len(errs))
    _cal[key] = res
    return res


def live_estimate(target, snap, finished, rank):
    pool = model.shape_pool(target, finished)
    if len(pool) < 3 or rank > len(snap["points"]):
        return None
    after = snap["ts"] - target["end"]
    p = min(max((snap["ts"] - target["begin"]) / max(target["end"] - target["begin"], 1), 0.0), 1.0)
    if p < 0.03:
        return None
    tables = Tables(pool, p, after)
    sims = simulate(snap["points"], snap["games"], tables, [rank], S=300, cap=(target.get("meta") or {}).get("match_cap"))[rank]
    games_left = last_info.get("games_left_top200", 0.0)   # read before the back-test overwrites it
    bias, cal_var, cal_n = calibration(pool, p, after, rank)
    logs = np.log1p(sims)
    mean = float(np.median(logs)) + bias
    var = float(np.var(logs)) + cal_var + 0.03 ** 2
    cur = snap["points"][rank - 1]
    analogs = []
    for w in pool:
        t = w["end"] + after if after > 0 else w["begin"] + p * (w["end"] - w["begin"])
        board = model.board_at(w, t)
        if rank <= len(board) and rank <= len(w["points"]):
            analogs.append({"window": w["window_id"], "region": w["region"], "now": board[rank - 1],
                            "final": w["points"][rank - 1]})
    return {"mean": mean, "var": var, "progress": p, "basis": "player simulation", "learned": True,
            "current": cur, "n": len(pool), "backtest_n": cal_n, "bias": round(math.expm1(bias), 3),
            "games_left_median": games_left, "analogs": analogs}


BUBBLE_X = [0.0, 0.01, 0.025, 0.033, 0.05, 0.075, 0.087, 0.122, 0.175, 0.215, 0.288, 0.363, 0.461, 0.924, 1.0]
BUBBLE_Y = [0.012, 0.017, 0.025, 0.033, 0.05, 0.066, 0.082, 0.104, 0.142, 0.191, 0.237, 0.283, 0.361, 0.689, 0.95]


def honest(prob):
    """The raw simulation is overconfident when it is sure; this is the back-tested correction."""
    return np.interp(prob, BUBBLE_X, BUBBLE_Y)


def bubble_probs(P, g, tables, goal, S=300, seed=3, cap=None, m_eff=None, shift=0.0, noise=0.0):
    """Chance that each entry finishes in the top `goal`, plus its median final and expected games.

    shift/noise move and blur the cutoff the same way the back-test says the simulation misses it."""
    final = simulate(P, g, tables, [], S=S, seed=seed, cap=cap, m_eff=m_eff, full=True)
    n = final.shape[0]
    goal = min(goal, n)
    thr = np.sort(final, axis=0)[-goal, :]
    rng = np.random.default_rng(seed + 1)
    thr = thr * np.exp(shift + (rng.normal(0, noise, size=S) if noise > 0 else 0.0))
    prob = (final >= thr[None, :]).mean(axis=1)
    return prob, np.median(final, axis=1), thr


def bubble(target, snap, finished, goal, players=None, approx=False):
    pool = model.shape_pool(target, finished)
    if len(pool) < 3 or not snap or goal > len(snap["points"]):
        return None
    after = snap["ts"] - target["end"]
    p = min(max((snap["ts"] - target["begin"]) / max(target["end"] - target["begin"], 1), 0.0), 1.0)
    if p < 0.03:
        return None
    tables = Tables(pool, p, after)
    cap = (target.get("meta") or {}).get("match_cap")
    P, g = np.asarray(snap["points"], float), np.asarray(snap["games"], int)
    m_eff, used = (None, 0)
    if players and len(players) == len(P):
        hist = history_ratios(target, finished)
        if hist:
            m_eff, used = skill_rates(P, g, players, hist)
    raw, med, thr = bubble_probs(P, g, tables, goal, cap=cap, m_eff=m_eff)
    return {"prob": honest(raw), "raw": raw, "median": med, "cutoff_median": float(np.median(thr)),
            "used_history": used, "progress": p}
