"""Logic behind the site's API (shared by the hosted app and the local server)."""
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
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name.replace("_", " "))
    rest = window_id.replace(event_id.replace("epicgames_", ""), "")
    extra = re.findall(r"(Round\d|Day\d|Heat\d|Event\d+|Final)", window_id)
    seen = [x for x in dict.fromkeys(extra) if x not in name]
    return (name + (" · " + " ".join(seen) if seen else "")).strip()


def window_info(w):
    m = w.get("meta") or {}
    now = time.time()
    status = ("finished" if w["final"] else "upcoming" if now < w["begin"]
              else "live" if now <= w["end"]
              else "games finishing" if now <= w["end"] + config.POST_END_GRACE
              else "ended (collecting)")
    return {
        "window_id": w["window_id"], "family": w["family"], "region": w["region"],
        "name": pretty(w.get("event_id") or "", w["window_id"]),
        "begin": w["begin"], "end": w["end"], "final": w["final"], "status": status,
        "category": classify.of(w),
        "match_cap": m.get("match_cap"), "mode": m.get("mode"), "game_type": m.get("game_type"),
        "lobby": m.get("lobby"), "stage": m.get("stage"), "advance": m.get("advance", []),
        "scoring": rules.describe(m["rules"]) if m.get("rules") else None,
    }


def list_windows():
    order = {"live": 0, "games finishing": 0, "ended (collecting)": 1, "upcoming": 2, "finished": 3}
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
    finished = storage.windows(final=True)
    snap = None
    if not target["final"]:
        last = storage.snapshots(window_id, last=1)
        snap = last[0] if last else None
    entrants = entrants or (snap or {}).get("entrants")
    r = model.predict(target, finished, top, entrants, snap, {})
    if r and not model.approx() and not r["prior"] and not (r.get("live") or {}).get("learned"):
        r = None   # strict: a class with no history gets no estimate rather than a crude guess
    if not r:
        cat = classify.of(target)
        n = sum(1 for w in finished if classify.of(w) == cat and w["family"] == target["family"])
        raise ValueError(f"No usable '{cat}' history yet ({n} finished events of that class). "
                         "Tick 'Allow similar classes' to estimate from the nearest other classes.")
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
    form = player_form(ids, [f for f in storage.windows(final=True) if classify.of(f) == cat],
                       w["family"])
    return {"snapshot": {"age_s": round(time.time() - s["ts"]), "entrants": s["entrants"]},
            "top": [{"rank": t["rank"], "points": t["points"], "games": t["games"],
                     "players": [{"id": a, "name": names.get(a, a[:8]), **form.get(a, {})}
                                 for a in t["players"]]} for t in top]}
