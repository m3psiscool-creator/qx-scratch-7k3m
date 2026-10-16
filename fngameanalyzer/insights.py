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
def home(region=""):
    now = time.time()
    infos = [w for w in service.list_windows() if not region or w["region"] == region]
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
                    "now": {r: snap["points"][r - 1] for r in sorted(set(PRED_RANKS) | ({w["goal"]["rank"]} if w.get("goal") else set()))
                            if snap and r <= len(snap["points"])},
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
    for w in storage.windows(final=True, light=True):
        i = service.window_info(w)
        rows.append({k: i[k] for k in ("window_id", "name", "family", "region", "category", "begin", "end", "match_cap")}
                    | {"entrants": w.get("entrants"), "cutoffs": cutoffs(w)})
    rows.sort(key=lambda r: -r["end"])
    return rows


def classes():
    fin = storage.windows(final=True, light=True)
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
    ws = sorted(storage.windows(final=True, category=category, light=True), key=lambda w: w["end"])
    ev = [{"window_id": w["window_id"], "name": service.pretty(w.get("event_id") or "", w["window_id"]),
           "region": w["region"], "end": w["end"], "family": w["family"], "cutoffs": cutoffs(w),
           "stage": (w.get("meta") or {}).get("stage"), "games": (w.get("meta") or {}).get("match_cap")} for w in ws]
    table = {}
    for r in STD_RANKS:
        v = sorted(e["cutoffs"][r] for e in ev if r in e["cutoffs"])
        if v:
            table[r] = {"n": len(v), "min": v[0], "p25": v[len(v) // 4], "median": statistics.median(v),
                        "p75": v[(3 * len(v)) // 4], "max": v[-1]}
    return {"category": category, "events": ev, "table": table}


# ---------------------------------------------------------------- players
def player(account_id):
    rows = [{**r, "name": service.pretty(r["event_id"], r["window_id"])} for r in storage.player_events(account_id)]
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
    counts = storage.player_event_counts([i for i, _ in hits])
    return [{"id": i, "name": n, "events": counts.get(i, 0)} for i, n in hits]


def top_players(category=None, limit=50):
    """Players ranked by average finishing share of the field (needs >= 3 events), computed in SQL."""
    rows = storage.top_players_sql(limit, category)
    names = _name_map([r["id"] for r in rows])
    return [{**r, "name": names.get(r["id"], r["id"][:8])} for r in rows]


# ---------------------------------------------------------------- FNCS tracker
def fncs():
    rows = []
    preds = {}
    finals = {w["window_id"]: w for w in storage.windows(final=True, light=True)}
    for w in storage.window_list():
        if w["family"] != "FNCS":
            continue
        i = service.window_info(w)
        full = finals.get(w["window_id"])
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
POINTS = (0.0, 0.25, 0.5, 0.75, 0.9)       # the moments scored: before the start and a quarter, half, three quarters and 90% of the way


def accuracy():
    """Every stored prediction (live ones, and the as-of-the-start ones made for every finished tournament) against the real final cutoff:
    error and bias by moment in the event (chart A) and, per event and rank, what was predicted over time against what happened (chart B)."""
    fin = {w["window_id"]: w for w in storage.windows(final=True, light=True)}
    buckets = {p: [] for p in POINTS}
    by_event = {}
    for wid, ts, rank, low, likely, safe, prog in storage.predictions_all():
        w = fin.get(wid)
        if not w or prog is None:
            continue
        act = cutoffs(w, [rank]).get(rank)
        if not act:      # no result for that rank (or 0 points): no relative error to measure
            continue
        err = (likely - act) / act
        b = min(POINTS, key=lambda x: abs(x - prog))
        if abs(b - prog) <= (0.03 if b == 0 else 0.07):
            buckets[b].append((err, low <= act <= safe, wid))
        by_event.setdefault((wid, rank), {"act": act, "pts": []})["pts"].append((round(float(prog), 3), low, likely, safe))
    out = []
    for b, v in buckets.items():
        if v:
            out.append({"progress": b, "n": len(v), "events": len({x[2] for x in v}),
                        "mean_abs_error_pct": round(100 * statistics.mean(abs(e) for e, _, _ in v), 1),
                        "median_abs_error_pct": round(100 * statistics.median(abs(e) for e, _, _ in v), 1),
                        "bias_pct": round(100 * statistics.mean(e for e, _, _ in v), 1),
                        "inside_range_pct": round(100 * sum(1 for _, ok, _ in v if ok) / len(v))})
    events = {}
    for (wid, rank), d in by_event.items():
        w = fin[wid]
        pts = sorted(d["pts"])
        if len(pts) < 2 and pts[0][0] > 0.03:
            continue
        ev = events.setdefault(wid, {"window_id": wid, "name": service.pretty(w.get("event_id") or "", wid), "region": w.get("region"),
                                     "end": w.get("end"), "ranks": {}})
        thin = pts if len(pts) <= 40 else pts[::max(1, len(pts) // 40)]
        ev["ranks"][str(rank)] = {"actual": d["act"], "points": [list(p) for p in thin]}
    evs = sorted(events.values(), key=lambda e: -(e.get("end") or 0))[:300]
    return {"buckets": out, "events": len({k[0] for k in by_event}), "finished": len(fin), "list": evs,
            "live_events": len({wid for (wid, _), d in by_event.items() if any(p[0] > 0.03 for p in d["pts"])}),
            "note": "range = low..safe; progress = share of the window elapsed; 'start' = predicted from earlier events only, before the window opened"}


# ---------------------------------------------------------------- status
def status():
    s = auth.status()
    tick = storage.kv_get("last_tick")
    c = storage.counts()
    by = storage.status_counts()
    return {"login": s, "last_tick_age_s": round(time.time() - tick["at"]) if tick else None,
            "last_tick": (tick or {}).get("log", []), "counts": c,
            "egress_mb_month": round(storage.egress_month() / 1e6, 1),
            "egress_by": storage.kv_get("egress_by") or [],
            "auth_log": storage.kv_get("auth_log") or [], "windows_by_status": by,
            "regions": config.TRACKED_REGIONS, "now": time.time()}
