"""Rotations: where every player moved in a tournament match, from the replay.

The worker (worker/run.mjs --tracks) reads full replays and posts, per match, every player's path (a sample about every 4 seconds), the
storm circles and who finished where. This module stores them (zlib, one row per match) and serves them: a player's games, and one game
with every path. Positions are stored in the loaders' frame (u, v as integers of 1/10000) and sent turned like the map the match was
played on (drops._turn), so they sit on the Map and Dropspots pictures."""
import json
import re
import zlib

import numpy as np

from . import drops, insights, service, storage

SCALE = 10000
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def ingest(body):
    """POST /api/admin/tracks: {window_id, session, duration, storm, teams: [{accounts, rank, game, placement, points, elims}], tracks: [...]}."""
    wid, sid = body.get("window_id"), str(body.get("session") or "")
    if not wid or not sid or not isinstance(body.get("tracks"), list) or not body["tracks"]:
        raise ValueError("window_id, session and tracks are required")
    lb = {}
    for t in body.get("teams") or []:
        for a in t.get("accounts") or []:
            lb[str(a).lower()] = t
    players = []
    for p in body["tracks"]:
        a = str(p.get("epic") or "").lower()
        if not HEX32.match(a):
            continue
        t = lb.get(a) or {}
        players.append((a, int(t.get("game") or 0), int(p.get("placement") or t.get("placement") or 0), int(p.get("kills") or 0), int(t.get("rank") or 0),
                        "+".join(sorted(str(x).lower() for x in (t.get("accounts") or [a])))))
    doc = {"d": int(body.get("duration") or 0), "storm": body.get("storm") or [], "tracks": [
        {"a": str(p.get("epic") or "").lower(), "t": p.get("team"), "pl": p.get("placement"), "k": p.get("kills"), "x": p.get("death"), "p": p.get("p")} for p in body["tracks"]],
        "teams": [{"acc": [str(a).lower() for a in (t.get("accounts") or [])], "rank": t.get("rank"), "game": t.get("game"), "pl": t.get("placement"), "pts": t.get("points"), "el": t.get("elims")}
                  for t in body.get("teams") or []]}
    blob = zlib.compress(json.dumps(doc, separators=(",", ":")).encode("utf8"), 9)
    storage.tracks_put(sid, wid, int(body.get("duration") or 0), blob, players)
    try:   # so the player search finds them by name
        insights._name_map([p[0] for p in players][:100])
    except Exception:
        pass
    return {"ok": True, "players": len(players), "bytes": len(blob)}


def recent(limit=40):
    """The latest games that have movement data."""
    wins = {w["window_id"]: w for w in service.list_windows()}
    return [{**r, "event": (wins.get(r["window_id"]) or {}).get("name") or r["window_id"], "region": (wins.get(r["window_id"]) or {}).get("region")}
            for r in storage.tracks_recent(limit)]


def player_games(account):
    """Every tracked game of one player: window, game number, finish, kills, final rank."""
    account = (account or "").lower()
    if not HEX32.match(account):
        raise ValueError("Pick a player from the search.")
    rows = storage.tracks_for_account(account)
    wins = {w["window_id"]: w for w in service.list_windows()}
    ids = [t for r in rows for t in (r["team"] or "").split("+") if HEX32.match(t)]
    names = insights._name_map(ids) if ids else {}
    out = []
    for r in rows:
        w = wins.get(r["window_id"]) or {}
        out.append({**r, "event": w.get("name") or r["window_id"], "region": w.get("region"), "category": w.get("category"), "end": w.get("end"),
                    "team": [names.get(t, t[:8]) for t in (r["team"] or "").split("+")]})
    return {"account": account, "name": (insights._name_map([account]) or {}).get(account, account[:8]), "games": out}


def game(session):
    """One match: every player's path (turned like its map), the storm circles, teams with names and results."""
    got = storage.tracks_get(session)
    if not got:
        raise ValueError("That game has no movement data (it is only read for some matches).")
    wid, duration, blob = got
    doc = json.loads(zlib.decompress(blob).decode("utf8"))
    row = next((r for r in storage.window_list() if r["window_id"] == wid), None)
    nrot = drops._rot_of(row) if row else 0
    turn = lambda u, v: drops._turn(u / SCALE, v / SCALE, nrot)
    def ints(u, v):
        x, y = turn(u, v)
        return int(round(x * SCALE)), int(round(y * SCALE))
    tracks = []
    for p in doc["tracks"]:
        pts = []
        for t, u, v, z in p["p"]:
            x, y = ints(u, v)
            pts.append([t, x, y, z])
        d = p.get("x")
        tracks.append({"a": p["a"], "t": p["t"], "pl": p["pl"], "k": p["k"], "p": pts, "x": (list(ints(d[0], d[1])) + [d[2]]) if d else None})
    storm = []
    for z in doc["storm"]:
        t, lr, lu, lv, nr, nu, nv, st, fi = z
        if nr <= 0:
            continue
        lx, ly = ints(lu, lv); nx, ny = ints(nu, nv)
        storm.append([t, lr, lx, ly, nr, nx, ny, st, fi])
    ids = [t["a"] for t in tracks]
    names = insights._name_map(ids) if ids else {}
    teams = {}
    for t in tracks:
        teams.setdefault(t["t"], []).append(t)
    lb = {}
    for t in doc.get("teams") or []:
        for a in t["acc"]:
            lb[a] = t
    out_teams = []
    for ti, ps in teams.items():
        info = next((lb[p["a"]] for p in ps if p["a"] in lb), {})
        out_teams.append({"team": ti, "players": [{"a": p["a"], "name": names.get(p["a"], p["a"][:8])} for p in ps], "placement": min((p["pl"] or 999) for p in ps),
                          "kills": sum((p["k"] or 0) for p in ps), "rank": info.get("rank"), "game": info.get("game"), "points": info.get("pts")})
    out_teams.sort(key=lambda t: t["placement"])
    w = next((r for r in storage.window_list() if r["window_id"] == wid), {})
    return {"session": session, "window_id": wid, "event": service.pretty(w.get("event_id") or "", wid) if w else wid, "region": w.get("region"),
            "duration": doc["d"] or duration, "scale": SCALE, "tracks": tracks, "storm": storm, "teams": out_teams, "goal": service.goal_of(w.get("meta") or {}) if w else None}
