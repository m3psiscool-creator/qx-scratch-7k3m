"""Tournament replays: the match list of one window and short-lived signed download links.

Epic keeps a server replay of every tournament match, keyed by the session id that the leaderboard lists for each game
(kept for roughly one to two weeks). This module hands out the match list and file links (valid ~15 minutes); a worker
downloads and parses the files so the production Epic login is used for nothing but these small requests."""
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from . import auth, rules, storage
from .epic_api import Epic

DATA = "https://datastorage-public-service-live.ol.epicgames.com/api/v1/data/fnreplaysmetadata/public"
ACCESS = "https://datastorage-public-service-live.ol.epicgames.com/api/v1/access/fnreplays/public"
SID = re.compile(r"^[0-9a-f]{32}$")
DONE_KEY = "drops_done:"


def links(session_id, max_ms=0):
    """File list + signed links of one match. max_ms > 0: only the header and the data chunks that start before it."""
    sid = (session_id or "").replace("-", "").lower()
    if not SID.match(sid):
        raise ValueError("session id must be 32 hex characters")
    tok = auth.Session().bearer()
    head = {"Authorization": "Bearer " + tok}
    r = requests.get(f"{DATA}/{sid}.json", headers=head, timeout=20)
    if r.status_code == 404:
        raise ValueError("No replay stored for this session (not played, not a tournament match, or already deleted).")
    r.raise_for_status()
    meta = r.json()
    if max_ms:
        names = ["header.bin"] + [f"{c['Id']}.bin" for c in meta.get("DataChunks") or [] if c.get("Time1", 0) < max_ms]
    else:
        names = ["header.bin"] + [f"{c['Id']}.bin" for k in ("DataChunks", "Events", "Checkpoints") for c in meta.get(k) or []]
    files = {}
    for i in range(0, len(names), 100):
        p = requests.post(f"{ACCESS}/{sid}/", json={"files": names[i:i + 100]}, headers=head, timeout=30)
        p.raise_for_status()
        for n, f in (p.json().get("files") or {}).items():
            files[n] = {"url": f.get("readLink"), "size": f.get("size")}
    return {"session": sid, "meta": meta, "files": files}


def matches(window_id, pages=100):
    """Every match (session) of a tournament window as listed on the leaderboard, with the teams that played it.

    One entry per session: its end time, and for each team the account ids, final rank, the number of the game for that team
    (their 1st, 2nd... game), placement, eliminations, win and points. `done` lists sessions already turned into landings."""
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    epic = Epic(auth.Session())
    rl = (w.get("meta") or {}).get("rules") or []

    err = []

    def page(pg):
        try:
            return epic.page(w["event_id"], window_id, pg)
        except Exception as e:
            err.append(f"{type(e).__name__}: {str(e)[:300]}")
            return None
    first = page(0)
    if not first:
        raise ValueError("Leaderboard not available" + (f" ({err[0]})" if err else ""))
    total = min(first.get("totalPages", 1) or 1, pages)
    with ThreadPoolExecutor(max_workers=6) as ex:
        got = [first] + list(ex.map(page, range(1, total)))
    sessions = {}
    for d in got:
        for e in (d or {}).get("entries", []):
            hist = sorted(e.get("sessionHistory") or [], key=lambda s: s.get("endTime") or "")
            for n, s in enumerate(hist, start=1):
                sid = s.get("sessionId")
                if not sid:
                    continue
                st = s.get("trackedStats") or {}
                row = sessions.setdefault(sid, {"session": sid, "end": s.get("endTime"), "teams": []})
                row["teams"].append({"accounts": e.get("teamAccountIds") or [], "rank": e.get("rank"), "game": n,
                                     "placement": st.get("PLACEMENT_STAT_INDEX"), "elims": st.get("TEAM_ELIMS_STAT_INDEX", 0),
                                     "win": 1 if st.get("VICTORY_ROYALE_STAT") else 0,
                                     "points": rules.game_points(rl, st) if rl else None})
    done = set((storage.kv_get(DONE_KEY + window_id) or {}).get("sessions") or [])
    from . import drops
    row = next((r for r in storage.window_list() if r["window_id"] == window_id), None)
    cdone_ids = set((storage.kv_get(drops._ctn_key(row)) or {}).get("done") or []) if row else set()
    cdone = sorted(sid for sid in sessions if sid[:12] in cdone_ids)
    try:
        tdone = sorted(storage.tracks_done(window_id) & set(sessions))
    except Exception:
        tdone = []
    out = sorted(sessions.values(), key=lambda r: r["end"] or "")
    return {"window_id": window_id, "begin": w["begin"], "end": w["end"], "final": bool(w["final"]), "playlist": (w.get("meta") or {}).get("playlist"),
            "game_type": (w.get("meta") or {}).get("game_type"),
            "sessions": out, "done": sorted(done & set(sessions)), "cdone": cdone, "tdone": tdone, "pages": total}
