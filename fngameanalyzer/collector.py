"""Server-side collector: keeps windows in sync, snapshots live boards, stores finished boards."""
import time
import re
from concurrent.futures import ThreadPoolExecutor

from . import auth, config, storage
from .epic_api import Epic

SYNC_ERRORS = []
SYNC_EVERY = 600       # refresh the event list this often (seconds)
MAX_RANK = 1000
BACKFILL_PER_POLL = 2  # old finished windows downloaded per pass when time allows


def sync_windows(e, force=False):
    last = storage.kv_get("last_sync") or 0
    if not force and time.time() - last < SYNC_EVERY:
        return 0
    n = 0
    for region in config.DOWNLOAD_REGIONS:
        try:
            for w in e.windows(region):
                if w["region"] in config.TRACKED_REGIONS:
                    storage.upsert_window(w)
                    n += 1
        except Exception as ex:
            SYNC_ERRORS.append((region, str(ex).split(" -> ")[-1][:200]))
            continue  # one region failing must not block the rest
    # Rebuild aggregates whose source boards were collected before this sync.
    for group in _day_groups(storage.window_list()):
        _build_cumulative(group)
    storage.kv_set("last_sync", time.time())
    return n


def _snap(e, w):
    try:
        lb = e.leaderboard(w["event_id"], w["window_id"], MAX_RANK)
        if lb["points"]:
            ts = time.time()
            storage.save_snapshot(w["window_id"], lb, ts)
            if lb.get("players"):   # accounts behind every rank, aligned with this snapshot
                storage.kv_set("board:" + w["window_id"], {"ts": ts, "players": lb["players"]})
            return ("snapshot", w["window_id"], len(lb["points"]))
    except Exception as ex:  # one bad window must not stop the others
        return ("error", w["window_id"], str(ex).split(" -> ")[-1][:200])
    return ("empty", w["window_id"], 0)


def _final(e, w):
    try:
        rows = storage.window_list()
        cumulative_source = any(w["window_id"] in {x["window_id"] for x in g}
                                for g in _day_groups(rows))
        lb = e.leaderboard(w["event_id"], w["window_id"], 2000 if cumulative_source else MAX_RANK)
        if lb["points"]:
            storage.save_final(w["window_id"], lb)
            for group in _day_groups(storage.window_list()):
                if any(x["window_id"] == w["window_id"] for x in group):
                    _build_cumulative(group)
            return ("final", w["window_id"], len(lb["points"]))
        storage.kv_set("empty:" + w["window_id"], time.time())
    except Exception as ex:
        return ("error", w["window_id"], str(ex).split(" -> ")[-1][:200])
    return ("empty", w["window_id"], 0)


def _day_groups(rows):
    """Group day-split windows for the same Epic event and region, across all formats."""
    groups = {}
    for w in rows:
        if (w.get("meta") or {}).get("cumulative"):
            continue
        wid = w["window_id"]
        day = re.search(r"Day(\d+)", wid, re.I)
        if not day:
            continue
        base = re.sub(r"Day\d+", "Day", wid, flags=re.I)
        key = (w["event_id"], w["region"], base)
        groups.setdefault(key, {})[int(day.group(1))] = w
    return [list(by_day.values()) for by_day in groups.values() if len(by_day) > 1]


def _build_cumulative(group):
    """Create the combined leaderboard for every multi-day event-window group."""
    if len(group) < 2:
        return False
    group = [storage.get_window(w["window_id"]) or w for w in group]
    group = sorted(group, key=lambda w: int(re.search(r"Day(\d+)", w["window_id"], re.I).group(1)))
    first = group[0]
    stem = re.sub(r"Day\d+", "Days", first["window_id"], flags=re.I)
    totals = {}
    for w in group:
        for i, team in enumerate(w.get("players") or []):
            key = tuple(sorted(team))
            if not key:
                continue
            row = totals.setdefault(key, {"points": 0.0, "games": 0, "sessions": []})
            row["points"] += (w.get("points") or [])[i]
            row["games"] += (w.get("games") or [])[i]
            row["sessions"].extend((w.get("sessions") or [[]])[i])
    if not totals:
        return False
    board = sorted(totals.items(), key=lambda x: (-x[1]["points"], x[0]))
    region_suffix = re.search(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", stem, re.I)
    if region_suffix:
        stem = stem[:region_suffix.start()]
    cumulative_id = f"{stem}Cumulative_{first['region']}"
    meta = dict(first.get("meta") or {})
    meta["cumulative"] = True
    meta["cumulative_sources"] = [w["window_id"] for w in group]
    advances = sorted({(int(rank), str(label)) for w in group
                       for rank, label in ((w.get("meta") or {}).get("advance") or [])})
    meta["advance"] = [[rank, label] for rank, label in advances] or [[2000, "Qualification cutoff"]]
    aggregate = {"window_id": cumulative_id, "event_id": first["event_id"],
                           "family": first["family"], "region": first["region"],
                           "begin": min(w["begin"] for w in group), "end": max(w["end"] for w in group), "meta": meta}
    storage.upsert_window(aggregate)
    if any(not w.get("final") for w in group):
        return True
    storage.save_final(cumulative_id, {"entrants": len(board), "points": [v["points"] for _, v in board],
        "games": [v["games"] for _, v in board], "sessions": [v["sessions"] for _, v in board],
        "players": [list(k) for k, _ in board], "deep": {}})
    return True


def poll_once(e, budget=12.0):
    """One pass: snapshot every live window (in parallel), then store finished windows."""
    t0 = time.time()
    now = t0
    # live = open, or closed but with games still finishing (they started before the end)
    live = storage.live_windows(now, config.FINALIZE_AFTER)
    done = []
    if live:
        with ThreadPoolExecutor(max_workers=min(8, len(live))) as ex:
            done.extend(ex.map(lambda w: _snap(e, w), live))
    # deep thresholds (rank 1500 ... 10000) for finished events saved before they were tracked
    if time.time() - t0 < budget:
        for w in storage.deep_missing(1):
            try:
                deep = e.deep_only(w["event_id"], w["window_id"])
                storage.set_deep(w["window_id"], deep or {"_": 0})
                done.append(("deep", w["window_id"], len(deep)))
            except Exception as ex:
                done.append(("error", w["window_id"], str(ex).split(" -> ")[-1][:200]))
    # the final board is stored only once every in-flight game has had time to finish;
    # older windows we never saw are backfilled newest first
    for w in storage.ended_unfinished(now, config.FINALIZE_AFTER, BACKFILL_PER_POLL):
        if time.time() - t0 > budget:
            break
        done.append(_final(e, w))
    # compact replay data for events saved before that column existed
    if time.time() - t0 < budget:
        for wid in storage.timed_missing(2):
            storage.fill_timed(wid)
            done.append(("timed", wid, 0))
    return done


PRED_EVERY = 1200  # seconds between stored predictions for the same window (each needs the class history)


def _ranks_of(w):
    from . import insights, service
    goal = service.goal_of(w["meta"])
    return sorted(set(insights.PRED_RANKS) | {r for r, _ in (w["meta"].get("advance") or [])} | ({goal["rank"]} if goal and goal["rank"] <= 1000 else set()))


def store_predictions(budget):
    """Save predictions for the live windows (feeds the home and accuracy pages). Every live window of every region and type gets its
    turn: the one waiting longest goes first and the pass continues with the next until the time budget is used."""
    from . import service
    t0 = time.time()
    now = t0
    due = []
    for w in storage.live_windows(now, config.POST_END_GRACE):
        if not (w["begin"] + 600 <= now <= w["end"] + config.POST_END_GRACE):
            continue
        last = storage.kv_get("predw:" + w["window_id"]) or 0
        if now - last >= PRED_EVERY:
            due.append((last, w))
    saved = 0
    for _, w in sorted(due, key=lambda x: x[0]):
        if time.time() - t0 > budget:
            break
        storage.kv_set("predw:" + w["window_id"], now)          # claim it first so overlapping passes don't repeat the work
        rows = []
        for r in _ranks_of(w):
            if time.time() - t0 > budget:
                break
            try:
                d = service.run_predict(w["window_id"], r, None, True)
                rows.append((w["window_id"], now, r, d["low"], d["likely"], d["safe"],
                             (d.get("live") or {}).get("progress"), (d.get("live") or {}).get("current") or d.get("current")))
            except Exception:
                pass
        if rows:
            storage.add_predictions(rows)
            saved += len(rows)
    return saved


def backfill_prestart(budget):
    """Score every finished tournament: predict it as of its start (history from before it only) and store that, so the accuracy page
    covers all of them, not only the ones that were live while the collector watched."""
    from . import service
    t0 = time.time()
    done = 0
    for w in storage.windows(final=True, light=True):
        if time.time() - t0 > budget:
            break
        key = "prest2:" + w["window_id"]
        if storage.kv_get(key):
            continue
        try:
            full = storage.get_window(w["window_id"])
            got = service.prestart(w["window_id"], _ranks_of(full))
            if got:
                storage.add_predictions([(w["window_id"], w["begin"], r, lo, li, sa, 0.0, None) for r, (lo, li, sa) in got.items()])
            storage.kv_set(key, {"at": time.time(), "ranks": len(got)})
            done += 1
        except Exception as ex:
            storage.kv_set(key, {"at": time.time(), "error": str(ex)[:200]})      # not retried forever: the error is kept for /api/admin/prestart
    return done


def backfill_names(budget):
    """Look up display names of top finishers so players can be searched by name."""
    if time.time() - (storage.kv_get("last_names") or 0) < 600:
        return 0
    storage.kv_set("last_names", time.time())
    ids = list(dict.fromkeys(a for a, *_ in storage.recent_top_accounts(20, 120)))
    have = storage.names_get(ids)
    todo = [i for i in ids if i not in have][:200]
    if not todo:
        return 0
    try:
        got = Epic(auth.Session()).display_names(todo)
    except Exception:
        return 0
    storage.names_set(got)
    return len(got)


_BOOT = time.time()   # when this server process started (a fresh process has empty caches)


def run_tick(duration=50, interval=30, force_sync=False):
    """Poll now and every `interval` seconds until `duration` has passed."""
    t0 = time.time()
    eg0 = storage.egress_bytes()
    try:
        e = Epic(auth.Session())
        e.s.bearer()  # keeps the rolling login alive even when nothing is live
    except auth.NotLoggedIn as ex:
        return {"ok": False, "error": str(ex)}
    log = []
    synced = sync_windows(e, force=force_sync)
    log.extend(("sync-error",) + x for x in SYNC_ERRORS[-3:])
    SYNC_ERRORS.clear()
    if (storage.kv_get("last_prune") or 0) < time.time() - 6 * 3600:
        storage.prune(3)
        storage.kv_set("last_prune", time.time())
    while True:
        t = time.time()
        log.extend(poll_once(e))
        wait = interval - (time.time() - t)
        if time.time() - t0 + max(wait, 0) + 5 > duration:
            break
        if not any(x[0] == "snapshot" for x in log):
            break  # nothing live: no point waiting
        time.sleep(max(wait, 0))
    left = duration + 8 - (time.time() - t0)
    try:
        n = store_predictions(max(left - 4, 0)) if left > 6 else 0
        if n:
            log.append(("predictions", "", n))
        rem = duration + 8 - (time.time() - t0)
        if rem > 5:
            nb = backfill_prestart(rem - 4)
            if nb:
                log.append(("prestart", "", nb))
        if time.time() - t0 < duration + 4:
            nn = backfill_names(5)
            if nn:
                log.append(("names", "", nn))
    except Exception as ex:
        log.append(("error", "extras", str(ex)[:120]))
    out = {"ok": True, "synced": synced, "log": log[-12:], "seconds": round(time.time() - t0, 1)}
    used = storage.egress_bytes() - eg0
    log.append(("meter", f"process age {round(time.time() - _BOOT)}s", f"{round(used / 1000)} KB read this pass"))
    storage.kv_set("last_tick", {"at": time.time(), "synced": synced, "log": log[-12:]})
    storage.egress_flush()
    return out
