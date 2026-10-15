"""Tournament replays: the list of files of one match and short-lived signed download links.

Epic keeps a server replay of every tournament match, keyed by the session id that the leaderboard lists for each game.
This module only hands out the file list and links (valid ~15 minutes); a worker downloads and parses the files so the
production Epic login is used for nothing but these small requests."""
import re

import requests

from . import auth

DATA = "https://datastorage-public-service-live.ol.epicgames.com/api/v1/data/fnreplaysmetadata/public"
ACCESS = "https://datastorage-public-service-live.ol.epicgames.com/api/v1/access/fnreplays/public"
SID = re.compile(r"^[0-9a-f]{32}$")


def links(session_id):
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
    names = ["header.bin"] + [f"{c['Id']}.bin" for k in ("DataChunks", "Events", "Checkpoints") for c in meta.get(k) or []]
    files = {}
    for i in range(0, len(names), 100):
        p = requests.post(f"{ACCESS}/{sid}/", json={"files": names[i:i + 100]}, headers=head, timeout=30)
        p.raise_for_status()
        for n, f in (p.json().get("files") or {}).items():
            files[n] = {"url": f.get("readLink"), "size": f.get("size")}
    return {"session": sid, "meta": meta, "files": files}
