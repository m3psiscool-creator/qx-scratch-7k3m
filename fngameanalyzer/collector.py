"""Server-side collector: keeps windows in sync, snapshots live boards, stores finished boards."""
import time
from concurrent.futures import ThreadPoolExecutor

from . import auth, config, storage
from .epic_api import Epic

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
        except Exception:
            continue  # one region failing must not block the rest
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
        return ("error", w["window_id"], str(ex)[:150])
    return ("empty", w["window_id"], 0)


def _final(e, w):
    try:
        lb = e.leaderboard(w["event_id"], w["window_id"], MAX_RANK)
        if lb["points"]:
            storage.save_final(w["window_id"], lb)
            return ("final", w["window_id"], len(lb["points"]))
        storage.kv_set("empty:" + w["window_id"], time.time())
    except Exception as ex:
        return ("error", w["window_id"], str(ex)[:150])
    return ("empty", w["window_id"], 0)


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
                done.append(("error", w["window_id"], str(ex)[:150]))
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


def store_predictions(budget):
    """Save predictions for one live window per pass (feeds the home and accuracy pages)."""
    from . import insights, service
    t0 = time.time()
    now = t0
    for w in storage.live_windows(now, config.POST_END_GRACE):
        if not (w["begin"] + 600 <= now <= w["end"] + config.POST_END_GRACE):
            continue
        key = "predw:" + w["window_id"]
        if now - (storage.kv_get(key) or 0) < PRED_EVERY:
            continue
        storage.kv_set(key, now)          # claim it first so overlapping passes don't repeat the work
        goal = service.goal_of(w["meta"])
        ranks = sorted(set(insights.PRED_RANKS) | {r for r, _ in (w["meta"].get("advance") or [])}
                       | ({goal["rank"]} if goal and goal["rank"] <= 1000 else set()))
        rows = []
        for r in ranks:
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
        return len(rows)
    return 0


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
