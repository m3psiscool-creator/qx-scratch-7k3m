"""Logic behind the site's API (shared by the hosted app and the local server)."""
import math
import statistics
import time

from . import auth, classify, config, model, rules, storage
from .epic_api import Epic


def pretty(event_id, window_id):
    """'epicgames_S42_EliteKadoThorneCup_NAC' + window id -> 'Elite Kado Thorne Cup'."""
    import re
    name = re.sub(r"^epicgames_", "", event_id)
    name = re.sub(r"^S\d+_", "", name)
    name = re.sub(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", "", name)
    name = name.replace("_", " ")
    name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    rest = window_id.replace(event_id.replace("epicgames_", ""), "")
    extra = re.findall(r"(Round\d|Day\d|Heat\d|Event\d+|Final)", window_id)
    seen = [x for x in dict.fromkeys(extra) if x not in name]
    return (name + (" · " + " ".join(seen) if seen else "")).strip()


def _history(target):
    """Finished events the model may use: the same class, or every class when approximation is on."""
    if model.approx():
        return storage.windows(final=True)
    return storage.windows(final=True, category=classify.of(target))


def goal_of(meta):
    """The rank the event is really about: last place with cosmetics, else last paid place, else the
    advancement cutoff."""
    tiers = ((meta or {}).get("rewards") or {}).get("tiers") or []
    rank = [t for t in tiers if t["kind"] == "rank"]
    kinds = lambda t: {i["type"] for i in t["items"]}
    items = [t for t in rank if "item" in kinds(t)]
    if items:
        t = max(items, key=lambda x: x["upto"])
        what = ", ".join(sorted({i["kind"] for i in t["items"] if i["type"] == "item"}))
        return {"rank": t["upto"], "kind": "cosmetics", "label": f"last place that wins the cosmetics ({what})"}
    cash = [t for t in rank if "cash" in kinds(t)]
    if cash:
        t = max(cash, key=lambda x: x["upto"])
        usd = [i["usd"] for i in t["items"] if i["type"] == "cash"]
        return {"rank": t["upto"], "kind": "cash", "label": f"last paid place (${usd[0]:,})" if usd else "last paid place"}
    adv = [t for t in rank if "advance" in kinds(t)]
    if adv:
        t = min(adv, key=lambda x: x["upto"])
        return {"rank": t["upto"], "kind": "advance", "label": "cutoff to advance"}
    return None


def window_info(w):
    m = w.get("meta") or {}
    now = time.time()
    status = ("finished" if w["final"] else "upcoming" if now < w["begin"]
              else "live" if now <= w["end"]
              else "games finishing" if now <= w["end"] + config.POST_END_GRACE
              else "ended (collecting)" if now <= w["end"] + config.FINALIZE_AFTER + 6 * 3600
              else "not collected yet")
    return {
        "window_id": w["window_id"], "family": w["family"], "region": w["region"],
        "name": pretty(w.get("event_id") or "", w["window_id"]),
        "begin": w["begin"], "end": w["end"], "final": w["final"], "status": status,
        "category": classify.of(w), "goal": goal_of(m),
        "rewards": (m.get("rewards") or {}).get("tiers", []), "cash_total": (m.get("rewards") or {}).get("cash_total", 0),
        "payout_at": (m.get("rewards") or {}).get("payout_at"), "payout_rule": (m.get("rewards") or {}).get("payout_rule"),
        "match_cap": m.get("match_cap"), "mode": m.get("mode"), "game_type": m.get("game_type"),
        "lobby": m.get("lobby"), "stage": m.get("stage"), "advance": m.get("advance", []),
        "scoring": rules.describe(m["rules"]) if m.get("rules") else None,
    }


def list_windows():
    order = {"live": 0, "games finishing": 0, "ended (collecting)": 1, "upcoming": 2, "finished": 3, "not collected yet": 4}
    ws = [window_info(w) for w in storage.window_list()]
    return sorted(ws, key=lambda w: (order[w["status"]], w["begin"] if w["status"] != "finished"
                                     else -w["begin"]))


def run_predict(window_id, top, entrants=None, approx=False):
    model._ctx.approx = bool(approx)
    try:
        return _run_predict(window_id, top, entrants)
    finally:
        model._ctx.approx = False


def _run_predict(window_id, top, entrants=None):
    target = storage.get_window(window_id)
    if not target:
        raise ValueError("Unknown window")
    finished = _history(target)
    if target["final"]:   # already happened: show the real result, not a prediction
        def actual(rank):
            if rank <= len(target["points"]):
                return target["points"][rank - 1]
            return (target.get("deep") or {}).get(str(rank), {}).get("points")
        v = actual(top)
        if v is not None:
            cut = [{"rank": rk, "label": lb, "low": actual(rk), "likely": actual(rk), "safe": actual(rk)}
                   for rk, lb in (target["meta"].get("advance") or []) if rk != top and actual(rk) is not None]
            return {"rank": top, "low": round(v), "likely": round(v), "safe": round(v), "current": round(v),
                    "final": True, "cutoffs": cut, "method": "Final result: this event has finished"}
    snap = None
    if not target["final"]:
        last = storage.snapshots(window_id, last=1)
        snap = last[0] if last else None
    entrants = entrants or (snap or {}).get("entrants")
    if top > 700:
        d = deep_predict(target, finished, snap, top)
        d["snapshot_age_s"] = round(time.time() - snap["ts"]) if snap else None
        d["cutoffs"] = []
        return d
    r = model.predict(target, finished, top, entrants, snap, {})
    if r and not model.approx() and not r["prior"] and not (r.get("live") or {}).get("learned"):
        r = None   # strict: a class with no history gets no estimate rather than a crude guess
    if not r:
        cat = classify.of(target)
        n = sum(1 for w in finished if classify.of(w) == cat and w["family"] == target["family"])
        raise ValueError(f"No usable '{cat}' history yet ({n} finished events of that class). "
                         "Tick 'Allow similar classes' to estimate from the nearest other classes.")
    cur = (r.get("live") or {}).get("current")
    if cur:   # a rank's score never falls
        for k in ("low", "likely", "safe"):
            r[k] = max(r[k], round(cur))
    r["entrants_used"] = entrants or (r["prior"] or {}).get("entrants") or 0
    r["snapshot_age_s"] = round(time.time() - snap["ts"]) if snap else None
    if not target["final"]:
        r["snapshots"] = storage.snapshot_stats(window_id)
        r["board_players"] = len(snap["points"]) if snap else 0
    r["cutoffs"] = []
    for rank, label in (target["meta"].get("advance") or []):
        if rank != top:
            c = model.predict(target, finished, rank, entrants, snap, {})
            if c:
                r["cutoffs"].append({"rank": rank, "label": label, "low": c["low"],
                                     "likely": c["likely"], "safe": c["safe"]})
    return r


def _history_index(finished, family):
    idx = {}
    for w in finished:
        if w["family"] != family:
            continue
        for rank, accts in enumerate(w.get("players") or [], start=1):
            for a in accts:
                idx.setdefault(a, []).append((w["window_id"], rank))
    return idx


def player_form(ids, finished, family):
    idx = _history_index(finished, family)
    out = {}
    for a in ids:
        h = idx.get(a, [])
        out[a] = {"events": len(h), "best": min((r for _, r in h), default=None),
                  "median": statistics.median(r for _, r in h) if h else None}
    return out


def live_view(window_id, n=25):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    snaps = storage.snapshots(window_id, last=1)
    if not snaps:
        return {"snapshot": None}
    s = snaps[0]
    top = s.get("top", [])[:n]
    ids = sorted({a for t in top for a in t["players"]})
    names = storage.names_get(ids)
    missing = [i for i in ids if i not in names]
    if missing:
        try:
            names.update(Epic(auth.Session()).display_names(missing))
            storage.names_set({k: v for k, v in names.items() if k in missing})
        except Exception:
            pass  # names are a nicety
    cat = classify.of(w)
    form = player_form(ids, storage.windows(final=True, category=cat), w["family"])
    return {"snapshot": {"age_s": round(time.time() - s["ts"]), "entrants": s["entrants"]},
            "top": [{"rank": t["rank"], "points": t["points"], "games": t["games"],
                     "players": [{"id": a, "name": names.get(a, a[:8]), **form.get(a, {})}
                                 for a in t["players"]]} for t in top]}


# ---- thresholds beyond the stored top-1000 board -------------------------------------------
def _interp_deep(points_1000, deep, rank, points=None):
    """Points at an arbitrary rank from the stored board and thresholds (log-linear in between)."""
    if points and rank <= len(points):
        return points[rank - 1]
    pts = {1000: points_1000}
    pts.update({int(r): v["points"] for r, v in (deep or {}).items() if "points" in v})
    ks = sorted(pts)
    if rank in pts:
        return pts[rank]
    lo = max((k for k in ks if k < rank), default=None)
    hi = min((k for k in ks if k > rank), default=None)
    if lo is None or hi is None or pts[lo] <= 0 or pts[hi] <= 0:
        return None
    f = (rank - lo) / (hi - lo)
    return math.exp(math.log(pts[lo]) * (1 - f) + math.log(pts[hi]) * f)


def deep_predict(target, finished, snap, rank):
    """Estimate for a rank beyond the stored board (1001-10000)."""
    cat = classify.of(target)
    hist = [w for w in finished if classify.of(w) == cat and w["family"] == target["family"]
            and w["window_id"] != target["window_id"] and w.get("deep")
            and len(w["points"]) >= 1000]
    if snap and snap.get("deep"):
        now_r = _interp_deep(snap["points"][min(999, len(snap["points"]) - 1)], snap["deep"], rank, snap["points"])
        ref = min(500, len(snap["points"]))   # the simulation is only trustworthy well inside the board
        base = model.predict(target, finished, ref, snap.get("entrants"), snap, {})
        now_ref = snap["points"][ref - 1]
        if now_r and base and now_ref > 0:
            k = lambda x: max(round(now_r * x / now_ref), round(now_r))   # a threshold never falls
            return {"rank": rank, "low": k(base["low"]), "likely": k(base["likely"]),
                    "safe": k(base["safe"]), "current": round(now_r),
                    "method": f"live points at this rank scaled by the predicted growth of rank {ref} (approximate)",
                    "history_events": len(hist)}
    vals = sorted(v for v in (_interp_deep(w["points"][999], w["deep"], rank) for w in hist) if v)
    if not vals:
        raise ValueError(f"No stored thresholds around rank {rank} for class '{cat}' yet")
    q = lambda f: vals[min(len(vals) - 1, int(f * len(vals)))]
    return {"rank": rank, "low": round(q(0.1)), "likely": round(statistics.median(vals)),
            "safe": round(q(0.9)), "current": None, "history_events": len(vals),
            "method": f"past {cat} events at this rank (no live board yet)"}


def thresholds(window_id):
    """Points at every stored threshold rank for a window (final board, else latest snapshot)."""
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    snap = None
    if w["final"]:
        pts, deep, src = w["points"], w["deep"], "final"
    else:
        last = storage.snapshots(window_id, last=1)
        if not last:
            return {"source": None, "ranks": {}}
        snap = last[0]
        pts, deep, src = snap["points"], snap["deep"], "live"
    out = {}
    for r in config.SERIES_RANKS:
        if r <= len(pts):
            out[r] = pts[r - 1]
        elif str(r) in (deep or {}):
            out[r] = deep[str(r)]["points"]
    return {"source": src, "ranks": out, "updated": snap["ts"] if snap else w["end"],
            "entrants": (snap or w).get("entrants")}


def series_view(window_id):
    rows = storage.series(window_id)
    return {"ranks": [str(r) for r in config.SERIES_RANKS], "points": rows}


REGION_SUFFIX = None


def siblings(window_id):
    """The same event in every region (window ids differ only in the trailing region code)."""
    import re
    strip = lambda x: re.sub(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", "", x)
    key = strip(window_id)
    out = []
    for x in storage.window_list():
        if strip(x["window_id"]) == key:
            i = window_info(x)
            out.append({"window_id": i["window_id"], "region": i["region"], "status": i["status"],
                        "begin": i["begin"], "end": i["end"]})
    order = {r: n for n, r in enumerate(config.ALL_REGIONS)}
    return sorted(out, key=lambda o: order.get(o["region"], 99))


def bubble_view(window_id, goal=None, approx=False):
    """Players around the cutoff and their chance to finish inside it."""
    from . import sim
    from .insights import _name_map
    target = storage.get_window(window_id)
    if not target:
        raise ValueError("Unknown window")
    if target["final"]:
        raise ValueError("This event has finished; there is no race left.")
    goal = goal or (goal_of(target["meta"]) or {}).get("rank") or 100
    if goal > 700:
        raise ValueError("The bubble table works up to rank 700 (beyond that only thresholds are stored).")
    last = storage.snapshots(window_id, last=1)
    if not last:
        raise ValueError("No live board yet.")
    snap = last[0]
    board = storage.kv_get("board:" + window_id)
    players = board["players"] if board and abs(board["ts"] - snap["ts"]) < 5 else None
    model._ctx.approx = bool(approx)
    try:
        res = sim.bubble(target, snap, _history(target), goal, players)
    finally:
        model._ctx.approx = False
    if not res:
        raise ValueError(f"No usable '{classify.of(target)}' history yet for a simulation. Tick 'Allow similar classes' to estimate from the nearest classes.")
    prob = res["prob"]
    pts, games = snap["points"], snap["games"]
    rows = [i for i in range(len(pts)) if 0.02 <= prob[i] <= 0.985 or abs(i + 1 - goal) <= 3][:80]
    ids = [a for i in rows for a in (players[i] if players else [])]
    names = _name_map(ids) if ids else {}
    return {"goal": goal, "progress": res["progress"], "age_s": round(time.time() - snap["ts"]),
            "cutoff_now": pts[goal - 1], "cutoff_final": round(res["cutoff_median"]),
            "safe": int((prob >= 0.985).sum()), "in_race": len(rows), "history_used": res["used_history"],
            "rows": [{"rank": i + 1, "points": pts[i], "games": games[i], "prob": round(float(prob[i]), 3),
                      "final": round(float(res["median"][i])),
                      "players": [{"id": a, "name": names.get(a, a[:8])} for a in (players[i] if players else [])]}
                     for i in rows]}
