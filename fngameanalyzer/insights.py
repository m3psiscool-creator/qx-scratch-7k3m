"""Read-side analytics for the site's pages (home, archive, classes, players, FNCS, accuracy, status)."""
import statistics
import time

from . import auth, classify, config, service, storage
from .epic_api import Epic

STD_RANKS = [1, 10, 35, 50, 100, 250, 500, 1000, 2000, 5000, 10000]
PRED_RANKS = [1, 10, 35, 50, 100, 500]
_idx = {"key": None, "data": None}


def cutoffs(w, ranks=STD_RANKS):
    out = {}
    for r in ranks:
        if r <= len(w.get("points") or []):
            out[r] = w["points"][r - 1]
        elif str((w.get("deep") or {}).get(str(r), {}).get("points", "")) != "":
            out[r] = w["deep"][str(r)]["points"]
    return out


def _name_map(ids):
    ids = list({i for i in ids if i})
    names = storage.names_get(ids) if ids else {}
    missing = [i for i in ids if i not in names][:100]
    if missing:
        try:
            got = Epic(auth.Session()).display_names(missing)
            storage.names_set(got)
            names.update(got)
        except Exception:
            pass
    return names


# ---------------------------------------------------------------- home
def home():
    now = time.time()
    infos = service.list_windows()
    live = [w for w in infos if w["status"] in ("live", "games finishing", "ended (collecting)")]
    out = []
    for w in live:
        snap = (storage.snapshots(w["window_id"], last=1) or [None])[0]
        preds = {}
        for p in storage.predictions_for(w["window_id"])[::-1]:
            preds.setdefault(p["rank"], p)
        top = []
        if snap:
            names = _name_map([a for t in snap.get("top", [])[:3] for a in t["players"]])
            top = [{"rank": t["rank"], "points": t["points"], "games": t["games"],
                    "players": [names.get(a, a[:8]) for a in t["players"]]} for t in snap.get("top", [])[:3]]
        out.append({**w, "progress": min(1, max(0, (now - w["begin"]) / (w["end"] - w["begin"]))),
                    "age_s": round(now - snap["ts"]) if snap else None,
                    "entrants": snap["entrants"] if snap else None, "top": top,
                    "now": {r: snap["points"][r - 1] for r in PRED_RANKS if snap and r <= len(snap["points"])},
                    "preds": {str(r): {k: p[k] for k in ("low", "likely", "safe")} for r, p in preds.items()}})
    up = [w for w in infos if w["status"] == "upcoming"]
    up.sort(key=lambda w: w["begin"])
    done = [w for w in infos if w["status"] == "finished"]
    done.sort(key=lambda w: -w["end"])
    return {"live": out, "upcoming": up[:12], "finished": done[:8], "now": now}


# ---------------------------------------------------------------- tournament board
def board(window_id, page=0, q="", size=50):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    if w["final"]:
        pts, games, players = w["points"], w["games"], w["players"]
        src, ts = "final", w["end"]
    else:
        last = storage.snapshots(window_id, last=1)
        if not last:
            return {"rows": [], "total": 0, "source": None}
        s = last[0]
        pts, games = s["points"], s["games"]
        players = [[] for _ in pts]
        for t in s.get("top", []):
            players[t["rank"] - 1] = t["players"]
        src, ts = "live", s["ts"]
    idx = list(range(len(pts)))
    if q:
        hits = {i for i, _ in storage.names_search(q, 50)}
        idx = [i for i in idx if any(a in hits for a in players[i])]
    total = len(idx)
    sel = idx[page * size:(page + 1) * size]
    names = _name_map([a for i in sel for a in players[i]]) if sel and (src == "final" or sel[0] < 60) else {}
    return {"source": src, "updated": ts, "total": total, "page": page, "size": size,
            "rows": [{"rank": i + 1, "points": pts[i], "games": games[i],
                      "players": [{"id": a, "name": names.get(a, a[:8])} for a in players[i]]} for i in sel]}


# ---------------------------------------------------------------- archive / classes
def archive():
    rows = []
    for w in storage.windows(final=True):
        i = service.window_info(w)
        rows.append({k: i[k] for k in ("window_id", "name", "family", "region", "category", "begin", "end", "match_cap")}
                    | {"entrants": w.get("entrants"), "cutoffs": cutoffs(w)})
    rows.sort(key=lambda r: -r["end"])
    return rows


def classes():
    fin = storage.windows(final=True)
    by = {}
    for w in fin:
        by.setdefault(classify.of(w), []).append(w)
    up = {}
    for w in storage.window_list():
        if not w["final"]:
            up[classify.of(w)] = up.get(classify.of(w), 0) + 1
    out = []
    for c, ws in sorted(by.items(), key=lambda kv: -len(kv[1])):
        out.append({"category": c, "events": len(ws), "upcoming": up.get(c, 0),
                    "median": {r: statistics.median(v) for r in (1, 10, 100, 500, 1000)
                               if (v := [cutoffs(w, [r])[r] for w in ws if r in cutoffs(w, [r])])}})
    return out


def class_detail(category):
    ws = sorted((w for w in storage.windows(final=True) if classify.of(w) == category), key=lambda w: w["end"])
    ev = [{"window_id": w["window_id"], "name": service.pretty(w.get("event_id") or "", w["window_id"]),
           "region": w["region"], "end": w["end"], "family": w["family"], "cutoffs": cutoffs(w)} for w in ws]
    table = {}
    for r in STD_RANKS:
        v = sorted(e["cutoffs"][r] for e in ev if r in e["cutoffs"])
        if v:
            table[r] = {"n": len(v), "min": v[0], "p25": v[len(v) // 4], "median": statistics.median(v),
                        "p75": v[(3 * len(v)) // 4], "max": v[-1]}
    return {"category": category, "events": ev, "table": table}


# ---------------------------------------------------------------- players
def _index():
    fin = storage.windows(final=True)
    key = (len(fin), max((w["end"] for w in fin), default=0))
    if _idx["key"] == key:
        return _idx["data"]
    data = {}
    for w in fin:
        ent = min(w.get("entrants") or 10000, 10000)
        cat = classify.of(w)
        for rank, accts in enumerate(w.get("players") or [], start=1):
            sess = w["sessions"][rank - 1] if rank <= len(w["sessions"]) else []
            plc = [g[0] for g in sess if g and g[0]]
            for a in accts:
                data.setdefault(a, []).append({
                    "window_id": w["window_id"], "name": service.pretty(w.get("event_id") or "", w["window_id"]),
                    "category": cat, "family": w["family"], "region": w["region"], "end": w["end"],
                    "rank": rank, "points": w["points"][rank - 1], "games": w["games"][rank - 1],
                    "pct": round(100 * rank / ent, 2),
                    "wins": sum(1 for g in sess if len(g) > 2 and g[2]),
                    "elims": sum(g[1] for g in sess if len(g) > 1),
                    "avg_place": round(statistics.mean(plc), 1) if plc else None})
    _idx.update(key=key, data=data)
    return data


def player(account_id):
    rows = sorted(_index().get(account_id, []), key=lambda r: -r["end"])
    name = _name_map([account_id]).get(account_id, account_id[:8])
    by = {}
    for r in rows:
        by.setdefault(r["category"], []).append(r)
    summary = []
    for c, v in by.items():
        g = sum(x["games"] for x in v)
        summary.append({"category": c, "events": len(v), "best_rank": min(x["rank"] for x in v),
                        "median_rank": statistics.median(x["rank"] for x in v),
                        "avg_top_pct": round(statistics.mean(x["pct"] for x in v), 2),
                        "pts_per_game": round(sum(x["points"] for x in v) / g, 1) if g else None,
                        "wins": sum(x["wins"] for x in v), "elims_per_game": round(sum(x["elims"] for x in v) / g, 2) if g else None})
    return {"id": account_id, "name": name, "events": rows, "summary": summary}


def player_search(q):
    hits = storage.names_search(q, 25) if q else []
    idx = _index()
    return [{"id": i, "name": n, "events": len(idx.get(i, []))} for i, n in hits]


def top_players(category=None, limit=50):
    """Players ranked by average finishing percentile (needs >= 3 events in the class)."""
    out = []
    for a, rows in _index().items():
        v = [r for r in rows if category in (None, "", r["category"])]
        if len(v) >= 3:
            out.append((statistics.mean(r["pct"] for r in v), a, v))
    out.sort(key=lambda x: x[0])
    names = _name_map([a for _, a, _ in out[:limit]])
    return [{"id": a, "name": names.get(a, a[:8]), "events": len(v), "avg_top_pct": round(p, 2),
             "best": min(r["rank"] for r in v)} for p, a, v in out[:limit]]


# ---------------------------------------------------------------- FNCS tracker
def fncs():
    rows = []
    preds = {}
    for w in storage.window_list():
        if w["family"] != "FNCS":
            continue
        i = service.window_info(w)
        full = storage.get_window(w["window_id"]) if w["final"] else None
        for p in storage.predictions_for(w["window_id"])[::-1]:
            preds.setdefault((w["window_id"], p["rank"]), p)
        adv = []
        for rank, token in i["advance"]:
            actual = cutoffs(full, [rank]).get(rank) if full else None
            pr = preds.get((w["window_id"], rank))
            adv.append({"rank": rank, "token": token, "actual": actual,
                        "predicted": {k: pr[k] for k in ("low", "likely", "safe")} if pr and not full else None})
        rows.append({k: i[k] for k in ("window_id", "name", "region", "category", "begin", "end", "status", "match_cap")} | {"advance": adv})
    rows.sort(key=lambda r: r["begin"])
    return rows


# ---------------------------------------------------------------- accuracy
def accuracy():
    fin = {w["window_id"]: w for w in storage.windows(final=True)}
    buckets = {0.25: [], 0.5: [], 0.75: [], 0.9: []}
    recent = {}
    for wid, ts, rank, low, likely, safe, prog in storage.predictions_all():
        w = fin.get(wid)
        if not w or prog is None:
            continue
        act = cutoffs(w, [rank]).get(rank)
        if act is None:
            continue
        b = min(buckets, key=lambda x: abs(x - prog))
        if abs(b - prog) > 0.07:
            continue
        err = (likely - act) / act
        buckets[b].append((err, low <= act <= safe))
        recent.setdefault(wid, []).append((rank, prog, likely, act))
    out = []
    for b, v in buckets.items():
        if v:
            out.append({"progress": b, "n": len(v), "mean_abs_error_pct": round(100 * statistics.mean(abs(e) for e, _ in v), 1),
                        "bias_pct": round(100 * statistics.mean(e for e, _ in v), 1),
                        "inside_range_pct": round(100 * sum(1 for _, ok in v if ok) / len(v))})
    return {"buckets": out, "events": len(recent), "note": "range = low..safe; progress = share of the window elapsed"}


# ---------------------------------------------------------------- status
def status():
    s = auth.status()
    tick = storage.kv_get("last_tick")
    c = storage.counts()
    wl = service.list_windows()
    by = {}
    for w in wl:
        by[w["status"]] = by.get(w["status"], 0) + 1
    return {"login": s, "last_tick_age_s": round(time.time() - tick["at"]) if tick else None,
            "last_tick": (tick or {}).get("log", []), "counts": c, "windows_by_status": by,
            "regions": config.TRACKED_REGIONS, "now": time.time()}
