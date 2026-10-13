"""Server-side collector: keeps windows in sync, snapshots live boards, stores finished boards."""
import time
from concurrent.futures import ThreadPoolExecutor

from . import auth, config, storage
from .epic_api import Epic

SYNC_EVERY = 600       # refresh the event list this often (seconds)
MAX_RANK = 1000
BACKFILL_PER_POLL = 1  # old finished windows downloaded per pass when time allows


def sync_windows(e, force=False):
    last = storage.kv_get("last_sync") or 0
    if not force and time.time() - last < SYNC_EVERY and storage.window_list():
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
            storage.save_snapshot(w["window_id"], lb)
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
    wl = storage.window_list()
    # live = open, or closed but with games still finishing (they started before the end)
    live = [w for w in wl if not w["final"] and w["begin"] <= now <= w["end"] + config.FINALIZE_AFTER]
    done = []
    if live:
        with ThreadPoolExecutor(max_workers=min(8, len(live))) as ex:
            done.extend(ex.map(lambda w: _snap(e, w), live))
    # the final board is stored only once every in-flight game has had time to finish;
    # older windows we never saw are backfilled newest first
    ended = sorted((w for w in wl if not w["final"] and now > w["end"] + config.FINALIZE_AFTER),
                   key=lambda w: -w["end"])
    todo = []
    for w in ended:  # skip windows Epic has no board for; check lazily to save database reads
        if len(todo) >= BACKFILL_PER_POLL:
            break
        if not storage.kv_get("empty:" + w["window_id"]):
            todo.append(w)
    for w in todo:
        if time.time() - t0 > budget:
            break
        done.append(_final(e, w))
    return done


def run_tick(duration=50, interval=30):
    """Poll now and every `interval` seconds until `duration` has passed."""
    t0 = time.time()
    try:
        e = Epic(auth.Session())
        e.s.bearer()  # keeps the rolling login alive even when nothing is live
    except auth.NotLoggedIn as ex:
        return {"ok": False, "error": str(ex)}
    log = []
    synced = sync_windows(e)
    while True:
        t = time.time()
        log.extend(poll_once(e))
        wait = interval - (time.time() - t)
        if time.time() - t0 + max(wait, 0) + 5 > duration:
            break
        if not any(x[0] == "snapshot" for x in log):
            break  # nothing live: no point waiting
        time.sleep(max(wait, 0))
    out = {"ok": True, "synced": synced, "log": log[-12:], "seconds": round(time.time() - t0, 1)}
    storage.kv_set("last_tick", {"at": time.time(), "synced": synced, "log": log[-12:]})
    return out
