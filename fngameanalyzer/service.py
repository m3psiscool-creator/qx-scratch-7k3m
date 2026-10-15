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
    name = re.sub(r"\b(\w+) \1\b", r"\1", name)   # collapse repeated words

    rest = window_id.replace(event_id.replace("epicgames_", ""), "")
    extra = re.findall(r"(Round\d|Day\d|Heat\d|Event\d+|Final)", window_id)
    seen = [x for x in dict.fromkeys(extra) if x not in name]
    return (name + (" · " + " ".join(seen) if seen else "")).strip()


def _history(target):
    """Finished events the model may use: the same gamemode, or every gamemode when approximation is on."""
    if model.approx():
        return storage.windows(final=True)
    return storage.windows(final=True, category=classify.of(target))


goal_of = classify.goal_of


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
        "reward_flags": (m.get("rewards") or {}).get("flags") or {
            "item": any(i["type"] == "item" for t in (m.get("rewards") or {}).get("tiers", []) for i in t["items"]),
            "advance": any(i["type"] == "advance" for t in (m.get("rewards") or {}).get("tiers", []) for i in t["items"])},
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


MAX_TOP = 10000


def _run_predict(window_id, top, entrants=None):
    target = storage.get_window(window_id)
    if not target:
        raise ValueError("Unknown window")
    if not isinstance(top, int) or top < 1 or top > MAX_TOP:
        raise ValueError(f"Top X must be a whole number from 1 to {MAX_TOP:,}")
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
    field = entrants or (snap or target).get("entrants")
    if field and top > field:
        raise ValueError(f"Only {field:,} teams {'played' if target['final'] else 'have entered so far'}, so there is no rank {top:,}. "
                         "Try a smaller number" + ("" if target["final"] else " or fill in a larger expected field under Entrants") + ".")
    if not field:   # field size unknown yet: use what past events of this format had
        sizes = sorted(w["entrants"] for w in model.comparable(target, finished) if w.get("entrants"))
        if sizes and top > sizes[-1] * 1.15:
            raise ValueError(f"Past events of this format ({classify.of(target)}, same game count and scoring) had {sizes[0]:,} to {sizes[-1]:,} teams "
                             f"(typically about {sizes[len(sizes) // 2]:,}), so rank {top:,} is outside the field. Try a rank up to about {sizes[-1]:,}, "
                             "or enter the expected number of teams under Entrants.")
    if top > 700:
        d = deep_predict(target, finished, snap, top)
        d["snapshot_age_s"] = round(time.time() - snap["ts"]) if snap else None
        d["cutoffs"] = []
        return d
    r = model.predict(target, finished, top, entrants, snap, {})
    if r and not model.approx() and not r["prior"] and not (r.get("live") or {}).get("learned"):
        r = None   # strict: a gamemode with no history gets no estimate rather than a crude guess
    if not r:
        cat = classify.of(target)
        n = sum(1 for w in finished if classify.of(w) == cat and w["family"] == target["family"])
        raise ValueError(f"No usable '{cat}' history yet ({n} finished events of that gamemode). "
                         "Tick 'Allow similar gamemodes' to estimate from the nearest other gamemodes.")
    cur = (r.get("live") or {}).get("current")
    if cur:   # a rank's score never falls
        for k in ("low", "likely", "safe"):
            r[k] = max(r[k], round(cur))
    pool = model.comparable(target, finished)
    r["history_mix"] = {"same": sum(1 for w in pool if w["region"] == target["region"]), "other": sum(1 for w in pool if w["region"] != target["region"]), "region": target["region"]}
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
    form = storage.player_form_sql(ids, classify.of(w))
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
    # same gamemode AND same format (game count + scoring), same region first: a 12-game event says nothing about a 6-game one
    hist = [w for w in model.comparable(target, finished)
            if len(w["points"]) >= min(rank, 1000) and (rank <= 1000 or (w.get("deep") and len(w["points"]) >= 1000))]
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
    vals = sorted(v for v in (_interp_deep(w["points"][999] if len(w["points"]) > 999 else 0, w.get("deep") or {}, rank, w["points"]) for w in hist) if v)
    if not vals:
        raise ValueError(f"No finished '{cat}' event with the same format (game count and scoring) has data around rank {rank} yet")
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
        raise ValueError(f"No usable '{classify.of(target)}' history yet for a simulation. Tick 'Allow similar gamemodes' to estimate from the nearest gamemodes.")
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


def _series_key(window_id):
    """'S42_ReloadCashCup_DuosZB_Event5Round2_OCE' -> 'ReloadCashCup_DuosZB': the same event series across rounds and seasons."""
    import re
    k = re.sub(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", "", window_id)
    k = re.sub(r"^S\d+_", "", k)
    k = re.sub(r"(Event|Qual|Heat|Round|Day|Week|Part|Stage)\d+", "", k)
    return re.sub(r"_+", "_", k).strip("_")


def sessions(window_id):
    """Every session (round, day, edition) of this event in the same region, oldest first, with the points the goal rank took."""
    from . import insights
    cur = storage.get_window(window_id)
    if not cur:
        raise ValueError("Unknown window")
    key, region = _series_key(window_id), cur["region"]
    rows = [w for w in storage.window_list() if w["region"] == region and _series_key(w["window_id"]) == key]
    rows.sort(key=lambda w: w["begin"])
    goal = (goal_of(cur.get("meta")) or {}).get("rank")
    finals = {w["window_id"]: w for w in storage.windows(final=True, light=True)} if any(w["final"] for w in rows) else {}
    items = []
    for w in rows:
        i = window_info(w)
        label = i["name"].split(" · ", 1)[1] if " · " in i["name"] else i["name"]
        pts = None
        if goal and w["window_id"] in finals:
            pts = insights.cutoffs(finals[w["window_id"]], [goal]).get(goal)
        items.append({"window_id": w["window_id"], "label": label, "begin": w["begin"], "end": w["end"],
                      "status": i["status"], "goal_pts": pts, "games": i["match_cap"]})
    idx = next((n for n, x in enumerate(items) if x["window_id"] == window_id), 0)
    lo = max(0, idx - 30)
    return {"key": key, "region": region, "goal_rank": goal, "index": idx - lo, "items": items[lo:idx + 12], "total": len(items)}


# ---- calendar export (.ics) of upcoming and live windows, with a reminder 30 minutes before
def _ics_text(x):
    """Escape text for an iCalendar field."""
    return str(x).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _event_key(window_id):
    import re
    return re.sub(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", "", window_id)


def calendar_ics(site, region="", family="", category="", q="", window="", favs=""):
    if window:
        wl = [w for w in list_windows() if w["window_id"] == window]
    else:
        keys = {k for k in favs.split(",") if k}
        terms = q.lower().split()
        wl = [w for w in list_windows() if w["status"] in ("upcoming", "live", "games finishing")
              and (not region or w["region"] == region) and (not family or w["family"] == family)
              and (not category or w["category"] == category)
              and all(t in (w["name"] + " " + w["region"] + " " + w["category"]).lower() for t in terms)
              and (not keys or _event_key(w["window_id"]) in keys)]
    stamp = lambda t: time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t))
    now = stamp(time.time())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FN Game Analyzer//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:FN Game Analyzer tournaments"]
    for w in wl[:120]:
        goal = w.get("goal")
        link = f"{site}/#/t/{w['window_id']}/strategy"
        desc = (f"{w['category']} - {w.get('match_cap') or '?'} games" + (f" - goal: top {goal['rank']}" if goal else "")
                + "\nPlan your strategy: " + link)
        lines += ["BEGIN:VEVENT", f"UID:{w['window_id']}@fn-game-analyzer", f"DTSTAMP:{now}",
                  f"DTSTART:{stamp(w['begin'])}", f"DTEND:{stamp(w['end'])}",
                  "SUMMARY:" + _ics_text(f"{w['name']} ({w['region']})"), "DESCRIPTION:" + _ics_text(desc),
                  "URL:" + link, "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Starts in 30 minutes",
                  "TRIGGER:-PT30M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
