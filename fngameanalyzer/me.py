"""A player's own results in one tournament, looked up by Epic display name (public leaderboard data only)."""
import threading
import time

from . import auth, rules, storage
from .epic_api import Epic, parse_time

PLACE, ELIM, WIN = rules.STATS
_scans = threading.BoundedSemaphore(2)    # at most two board scans at once: each one is ~100 requests to Epic


def _resolve(epic, name):
    low = name.lower()
    for acct, known in storage.names_search(name, 10):
        if known.lower() == low:
            return acct, known
    try:
        r = epic.lookup(name)
    except RuntimeError as e:
        if "404" in str(e):
            raise ValueError(f"No Epic account is named '{name}'. Type your Epic display name exactly as it appears in Fortnite.")
        raise
    storage.names_set({r["id"]: r["name"]})
    return r["id"], r["name"]


def account(name):
    """Check an Epic display name once and return its account id (the site then remembers it in the browser)."""
    name = (name or "").strip()
    if len(name) < 3 or len(name) > 32:
        raise ValueError("Type your Epic display name (3 to 32 characters).")
    acct, shown = _resolve(Epic(auth.Session()), name)
    return {"id": acct, "name": shown}


def lookup(window_id, name, account_id=None):
    name = (name or "").strip()
    if not account_id and (len(name) < 3 or len(name) > 32):
        raise ValueError("Type your Epic display name (3 to 32 characters).")
    t = storage.get_window(window_id)
    if not t:
        raise ValueError("Unknown window")
    if time.time() < t["begin"]:
        return {"found": False, "name": name, "message": "This event has not started yet, so there are no results to read."}
    epic = Epic(auth.Session())
    if account_id and len(account_id) == 32 and all(c in "0123456789abcdef" for c in account_id):
        acct, shown = account_id, (storage.names_get([account_id]).get(account_id) or name or account_id[:8])   # already checked when it was saved
    else:
        acct, shown = _resolve(epic, name)
    key = f"me:{window_id}:{acct}"
    cached = storage.kv_get(key)
    ttl = 3600 if t["final"] else 60
    if cached and time.time() - cached["updated"] < ttl:
        return cached
    if not _scans.acquire(timeout=30):
        raise ValueError("Busy looking up other players. Try again in a few seconds.")
    try:
        entry, pages = epic.find_entry(t["event_id"], window_id, acct)
    finally:
        _scans.release()
    if not entry:
        out = {"found": False, "name": shown, "account": acct, "updated": time.time(), "pages": pages,
               "message": f"{shown} is not in the top {pages * 100:,} of this event (yet), or has not played a game here."}
        storage.kv_set(key, out)
        return out
    rl = (t.get("meta") or {}).get("rules") or []
    games, prev = [], None
    for i, s in enumerate(sorted(entry.get("sessionHistory") or [], key=lambda s: s.get("endTime") or "")):
        st = s.get("trackedStats") or {}
        stats = {k: st.get(k, 0) for k in rules.STATS}
        end = round(parse_time(s["endTime"])) if s.get("endTime") else 0
        games.append({"n": i + 1, "session": s.get("sessionId"), "placement": stats[PLACE], "elims": stats[ELIM], "win": stats[WIN], "end": end,
                      "points": rules.game_points(rl, stats) if rl else None,
                      "gap_min": round((end - prev) / 60, 1) if prev and end else None})
        prev = end or prev
    mates = [a for a in (entry.get("teamAccountIds") or []) if a != acct]
    mate_names = []
    if mates:
        try:
            mate_names = list(epic.display_names(mates).values())
        except Exception:
            mate_names = []
    n = len(games) or 1
    scored = sum(g["points"] or 0 for g in games) if rl else None
    out = {"found": True, "name": shown, "account": acct, "updated": time.time(), "pages": pages,
           "rank": entry.get("rank"), "points": entry.get("pointsEarned", entry.get("score", 0)), "percentile": entry.get("percentile"),
           "team": mate_names, "games": games, "games_played": len(games),
           "avg_place": round(sum(g["placement"] for g in games) / n, 2) if games else None,
           "elims_per_game": round(sum(g["elims"] for g in games) / n, 2) if games else None,
           "pts_per_game": round(float(entry.get("pointsEarned", 0) or 0) / n, 2) if games else None,
           "wins": sum(1 for g in games if g["win"]), "rules_total": scored, "last_end": games[-1]["end"] if games else None}
    storage.kv_set(key, out)
    return out
