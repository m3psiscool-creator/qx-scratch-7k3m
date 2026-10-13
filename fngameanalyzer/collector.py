"""Server-side collector: keeps windows in sync, snapshots live boards, stores finished boards."""
import time

from . import auth, config, storage
from .epic_api import Epic

SYNC_EVERY = 600       # refresh the event list this often (seconds)
LIVE_MARGIN = 120      # start polling this long before a window opens / after it closes
MAX_RANK = 1000


def sync_windows(e, force=False):
    last = storage.kv_get("last_sync") or 0
    if not force and time.time() - last < SYNC_EVERY and storage.window_list():
        return 0
    n = 0
    for region in config.TRACKED_REGIONS:
        for w in e.windows(region):
            if w["region"] in config.TRACKED_REGIONS:
                storage.upsert_window(w)
                n += 1
    storage.kv_set("last_sync", time.time())
    return n


def poll_once(e):
    """One pass: snapshot every live window and store at most one finished window."""
    now = time.time()
    done = []
    wl = storage.window_list()
    # live = open, or closed but with games still finishing (they were started before the end)
    live = [w for w in wl if not w["final"] and w["begin"] <= now <= w["end"] + config.FINALIZE_AFTER]
    for w in live:
        try:
            lb = e.leaderboard(w["event_id"], w["window_id"], MAX_RANK)
            if lb["points"]:
                storage.save_snapshot(w["window_id"], lb)
                done.append(("snapshot", w["window_id"], len(lb["points"])))
        except Exception as ex:  # one bad window must not stop the others
            done.append(("error", w["window_id"], str(ex)[:150]))
    # the final board is stored only once every in-flight game has had time to finish
    ended = [w for w in wl if not w["final"] and now > w["end"] + config.FINALIZE_AFTER
             and now - w["end"] < 3 * 86400]
    for w in ended[:1]:
        try:
            lb = e.leaderboard(w["event_id"], w["window_id"], MAX_RANK)
            if lb["points"]:
                storage.save_final(w["window_id"], lb)
                done.append(("final", w["window_id"], len(lb["points"])))
        except Exception as ex:
            done.append(("error", w["window_id"], str(ex)[:150]))
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
