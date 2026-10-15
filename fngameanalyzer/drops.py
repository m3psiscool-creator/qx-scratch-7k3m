"""Dropspots: where teams landed in a tournament and what happened to them afterwards.

Epic's leaderboard has no location data, so landing rows come from a loader (the owner-only endpoint
/api/admin/drops, see docs/dropspots-data.md). This module stores them, aggregates them for the map and
describes the map an event is played on."""
import math
import re
import time

import numpy as np

from . import classify, config, insights, rules, service, storage

GRID = 96
BASE = 128           # resolution of the background map drawn from player movement
CHEST = 360          # chest map: CHEST x CHEST cells over the map square (about 3 m per cell)
_cache = {}          # window_id -> (time, arrays); a tournament is a few tens of thousands of rows
CACHE_TTL = 300
HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------- what map is this event played on
# Maps we have a picture for, by the codename in the playlist id. The picture is drawn in the same 0-1 frame as the
# landings (north-up is NOT assumed: it is the picture rotated/scaled to match the game's own coordinates, see
# docs/dropspots-data.md "Map pictures"). Picture: Epic Games' overview image of the map, via the Fortnite Wiki.
MAPS = {
    "SourSpawn": {"name": "Nitemare Island", "image": "/maps/nitemare-island.jpg", "mask": "nitemare-island",
                  "credit": "Map: Nitemare Island, Epic Games (overview image from the Fortnite Wiki)"},
}
MIN_ON_LAND = 0.93     # a registered picture is only shown while at least this share of the real landings is on its land
_masks = {}


def _land_mask(name):
    """Land/water outline that goes with a map picture (tools/mapfit/make_mask.py), as a boolean array."""
    if name not in _masks:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "maps", name + ".mask.json")
        d = json.load(open(path))
        _masks[name] = np.array([[c == "1" for c in row] for row in d["rows"]], dtype=bool)
    return _masks[name]


def picture_check(window_id, known):
    """Share of this tournament's landings that fall on land of the registered picture (None: no landings to test with)."""
    try:
        a = _arrays(window_id)
    except ValueError:
        return None
    m = _land_mask(known["mask"])
    n = m.shape[0]
    ix = np.clip((a["x"] * n).astype(int), 0, n - 1)
    iy = np.clip((a["y"] * n).astype(int), 0, n - 1)
    return float(m[iy, ix].mean())


def map_info(window_id):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    meta = w.get("meta") or {}
    playlist = meta.get("playlist") or ""
    reload_ = meta.get("game_type") == "reload"
    build = " zb" not in " " + classify.of(w)
    codename = next((t for t in ("SourSpawn", "BlastBerry", "DashBerry", "PiperBoot", "JumpBear") if t.lower() in playlist.lower()), None)
    label = "Reload map" if reload_ else "Battle Royale island"
    rec = storage.drop_map_get(window_id) if hasattr(storage, "drop_map_get") else None
    known = MAPS.get(codename)
    check = None
    if known:   # a known map picture wins over the background drawn from player movement, but only while the landings agree with it
        rec = {**(rec or {}), **known}
        share = picture_check(window_id, known) if known.get("mask") else None
        check = {"on_land": None if share is None else round(share, 3), "min": MIN_ON_LAND,
                 "status": "untested" if share is None else "ok" if share >= MIN_ON_LAND else "mismatch"}
        if check["status"] == "mismatch":   # wrong map picture: never show it
            rec = {k: v for k, v in rec.items() if k not in ("image", "name", "credit")}
            rec["image"] = ""
            rec["name"] = ""
        rec.pop("mask", None)
    rec = dict(rec or {})
    rec.pop("base", None)      # never a map drawn from player movement: only a real picture of the map, or none
    rec.pop("base_size", None)
    if not rec.get("image"):
        rec.update(image="", credit="", name=rec.get("name") or "")
    avail = storage.drops_available() if hasattr(storage, "drops_available") else {}
    return {"window_id": window_id, "name": service.pretty(w.get("event_id") or "", window_id), "region": w["region"],
            "begin": w["begin"], "end": w["end"], "final": bool(w["final"]),
            "playlist": playlist, "game_type": meta.get("game_type"), "mode": meta.get("mode"), "build": build, "codename": codename,
            "label": label, "match_cap": meta.get("match_cap"), "goal": service.goal_of(meta),
            "map": rec, "map_check": check, "landings": (avail.get(window_id) or (0, 0))[0], "games": (avail.get(window_id) or (0, 0))[1],
            "note": (None if rec.get("image") else
                     f"No picture of this map is available yet{' (' + codename + ')' if codename else ''}: a map picture is only shown when it is a real image of that map.")}


def events():
    """Which tournaments have landing data."""
    return {k: {"landings": v[0], "games": v[1]} for k, v in storage.drops_available().items()}


# ---------------------------------------------------------------- the data, as arrays
def _arrays(window_id):
    hit = _cache.get(window_id)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    rows = storage.drops_rows(window_id)
    if not rows:
        raise ValueError("No landing data has been loaded for this tournament yet.")
    a = {"game": np.array([r[0] for r in rows], dtype=np.int16), "team": [r[1] for r in rows],
         "x": np.array([r[2] for r in rows], dtype=np.float32), "y": np.array([r[3] for r in rows], dtype=np.float32),
         "poi": [r[4] or "" for r in rows], "placement": np.array([r[5] or 0 for r in rows], dtype=np.int16),
         "points": np.array([r[6] or 0 for r in rows], dtype=np.int32), "rank": np.array([r[7] or 0 for r in rows], dtype=np.int32),
         "win": np.array([r[8] or 0 for r in rows], dtype=np.int8)}
    lobby = {int(g): max(1, int(a["placement"][a["game"] == g].max())) for g in np.unique(a["game"])}
    a["lobby"] = np.array([lobby[int(g)] for g in a["game"]], dtype=np.int16)
    a["poi_arr"] = np.array(a["poi"], dtype=object)
    while len(_cache) >= 3:
        _cache.pop(next(iter(_cache)))
    _cache[window_id] = (time.time(), a)
    return a


def _sel(a, game):
    return (a["game"] == game) if game else np.ones(len(a["game"]), dtype=bool)


def _stats(a, mask, top):
    n = int(mask.sum())
    if not n:
        return {"landings": 0}
    pl, pts, rk, lob = a["placement"][mask], a["points"][mask], a["rank"][mask], a["lobby"][mask]
    q = (rk > 0) & (rk <= top)
    return {"landings": n, "qualifier_landings": int(q.sum()), "qualifier_share": round(float(q.mean()), 4),
            "avg_placement": round(float(pl.mean()), 2), "avg_points": round(float(pts.mean()), 2),
            "win_rate": round(float(a["win"][mask].mean()), 4),
            "top_quarter_rate": round(float((pl <= np.maximum(1, lob // 4)).mean()), 4),
            "early_exit_rate": round(float((pl > lob * 0.75).mean()), 4),
            "avg_placement_pct": round(float((pl / lob).mean()), 4)}


# ---------------------------------------------------------------- heatmap, areas, named locations
def grid(window_id, top=100, game=0, size=GRID):
    """Landing counts in size x size cells for everyone and for teams that finished in the top `top`."""
    a = _arrays(window_id)
    m = _sel(a, game)
    ix = np.clip((a["x"] * size).astype(int), 0, size - 1)
    iy = np.clip((a["y"] * size).astype(int), 0, size - 1)
    cell = iy * size + ix
    q = (a["rank"] > 0) & (a["rank"] <= top)

    def sparse(mask):
        u, c = np.unique(cell[mask], return_counts=True)
        return [[int(i), int(n)] for i, n in zip(u, c)]
    return {"size": size, "all": sparse(m), "q": sparse(m & q), "total": int(m.sum()), "qualifier_landings": int((m & q).sum()),
            "games": sorted(int(g) for g in np.unique(a["game"]) if g > 0), "top": top}


def _in_poly(x, y, poly):
    """Vectorised point-in-polygon (ray casting); poly is a list of [x, y]."""
    inside = np.zeros(len(x), dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        cross = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        inside ^= cross
        j = i
    return inside


def area(window_id, poly, top=100, game=0):
    """Everything about the teams that landed inside a hand-drawn region."""
    a = _arrays(window_id)
    poly = [[float(p[0]), float(p[1])] for p in poly][:80]
    if len(poly) < 3:
        raise ValueError("Draw an area with at least three corners.")
    base = _sel(a, game)
    mask = base & _in_poly(a["x"], a["y"], poly)
    out = {"area": _stats(a, mask, top), "everywhere": _stats(a, base, top)}
    out["area"]["share_of_landings"] = round(out["area"]["landings"] / max(1, out["everywhere"]["landings"]), 4)
    qm = (a["rank"] > 0) & (a["rank"] <= top)
    out["area"]["share_of_qualifier_landings"] = round(int((mask & qm).sum()) / max(1, int((base & qm).sum())), 4)
    idx = np.where(mask)[0]
    by_game = {}
    for g in np.unique(a["game"][idx]):
        by_game[int(g)] = int((a["game"][idx] == g).sum())
    out["by_game"] = by_game
    out["loot"] = _area_loot(window_id, a, mask, base, poly)
    pois = {}
    for p in a["poi_arr"][idx]:
        if p:
            pois[p] = pois.get(p, 0) + 1
    out["pois"] = sorted(([k, v] for k, v in pois.items()), key=lambda kv: -kv[1])[:6]
    # the best-scoring teams that landed here
    best = idx[np.argsort(-a["points"][idx])[:10]] if len(idx) else []
    ids = [t for i in best for t in a["team"][i].split("+") if HEX32.match(t)]
    names = insights._name_map(ids) if ids else {}
    out["best"] = [{"team": " + ".join(names.get(t, t[:8]) if HEX32.match(t) else t for t in a["team"][i].split("+")),
                    "game": int(a["game"][i]), "points": int(a["points"][i]), "placement": int(a["placement"][i]), "rank": int(a["rank"][i])} for i in best]
    return out


def pois(window_id, top=100, game=0):
    """The named landing spots, compared."""
    a = _arrays(window_id)
    base = _sel(a, game)
    qm = (a["rank"] > 0) & (a["rank"] <= top)
    total, qtotal = int(base.sum()), int((base & qm).sum())
    rows = []
    for name in sorted({p for p in a["poi"] if p}):
        m = base & (a["poi_arr"] == name)
        s = _stats(a, m, top)
        if not s["landings"]:
            continue
        s.update(name=name, share_of_landings=round(s["landings"] / max(1, total), 4),
                 share_of_qualifier_landings=round(s["qualifier_landings"] / max(1, qtotal), 4),
                 x=round(float(a["x"][m].mean()), 4), y=round(float(a["y"][m].mean()), 4))
        rows.append(s)
    rows.sort(key=lambda r: -r["landings"])
    return {"pois": rows, "total": total, "baseline": _stats(a, base, top)}


# ---------------------------------------------------------------- loading data (owner only)
def ingest(body):
    """Store landing rows. See docs/dropspots-data.md for the format."""
    wid = body.get("window_id")
    w = storage.get_window(wid)
    if not w:
        raise ValueError("Unknown window_id")
    raw = body.get("drops") or []
    if not isinstance(raw, list) or (not raw and not body.get("sessions_done")):
        raise ValueError("drops must be a non-empty list")
    if len(raw) > 20000:
        raise ValueError("Send at most 20,000 rows per request; use append for the rest.")
    world = body.get("coords") == "world"
    b = body.get("bounds")
    if world and not (isinstance(b, list) and len(b) == 4 and b[1] != b[0] and b[3] != b[2]):
        raise ValueError("coords 'world' needs bounds [minX, maxX, minY, maxY]")
    flip = bool(body.get("flip_y"))

    def unit(x, y):
        if world:
            x, y = (x - b[0]) / (b[1] - b[0]), (y - b[2]) / (b[3] - b[2])
        return x, (1 - y if flip else y)
    rank_of = {}
    if w["final"]:
        for r, accts in enumerate(w.get("players") or [], start=1):
            for acct in accts:
                rank_of[acct] = r
    rl = (w.get("meta") or {}).get("rules") or []
    rows, skipped = [], 0
    for d in raw:
        try:
            x, y = unit(float(d["x"]), float(d["y"]))
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if not (math.isfinite(x) and math.isfinite(y)) or not (0 <= x <= 1 and 0 <= y <= 1):
            skipped += 1
            continue
        team = str(d.get("team") or "")[:140]
        place = int(d.get("placement") or 0)
        pts = d.get("points")
        if pts is None and rl and d.get("elims") is not None:
            pts = rules.game_points(rl, {rules.STATS[0]: place, rules.STATS[1]: int(d["elims"]), rules.STATS[2]: 1 if d.get("win") else 0})
        rank = int(d.get("rank") or 0) or min((rank_of[t] for t in team.split("+") if t in rank_of), default=0)
        rows.append((int(d.get("game") or 1), team, x, y, str(d.get("poi") or "")[:60], place, int(pts or 0), rank, 1 if d.get("win") else 0))
    if not rows and not body.get("sessions_done"):
        raise ValueError("No usable rows (coordinates must be inside the map).")
    if rows:
        storage.drops_replace(wid, rows, append=bool(body.get("append")))
    m = body.get("map")
    if isinstance(m, dict):
        old = (storage.drop_map_get(wid) if hasattr(storage, "drop_map_get") else None) or {}
        pois_ = old.get("pois") or []
        if m.get("pois"):
            pois_ = []
            for p in (m.get("pois") or [])[:200]:
                try:
                    px, py = unit(float(p["x"]), float(p["y"]))
                    pois_.append({"name": str(p["name"])[:60], "x": px, "y": py, "r": float(p.get("r") or 0.03)})
                except (KeyError, TypeError, ValueError):
                    continue
        img = str(m.get("image") or old.get("image") or "")
        rec = {"name": str(m.get("name") or old.get("name") or "")[:80], "image": img if img.startswith("https://") else "", "pois": pois_,
               "credit": str(m.get("credit") or old.get("credit") or "")[:120]}
        # a map drawn from where players moved (no outside image needed): cells of a BASE x BASE grid with a visit count
        base = dict(old.get("base") or {})
        add = m.get("base")
        if isinstance(add, dict) and isinstance(add.get("cells"), list):
            for cell, n in add["cells"][:BASE * BASE]:
                if 0 <= int(cell) < BASE * BASE:
                    base[str(int(cell))] = base.get(str(int(cell)), 0) + int(n)
        if base:
            rec["base"] = base
            rec["base_size"] = BASE
        storage.drop_map_set(wid, rec)
    if body.get("reset"):   # start this tournament over (landings were replaced above): forget finished matches and chest counts
        storage.kv_set("drops_done:" + wid, {"sessions": []})
        storage.kv_set(_atlas_key(w), {"size": CHEST, "matches": 0, "cells": {}})
        _atlas_cache.pop(_atlas_key(w), None)
    ch = body.get("chests")
    if isinstance(ch, dict) and isinstance(ch.get("cells"), list):
        key = _atlas_key(w)
        atlas = storage.kv_get(key) or {"size": CHEST, "matches": 0, "cells": {}}
        atlas["matches"] = int(atlas.get("matches") or 0) + max(0, int(ch.get("matches") or 0))
        cells = atlas.setdefault("cells", {})
        for cell, n in ch["cells"][:CHEST * CHEST]:
            if 0 <= int(cell) < CHEST * CHEST and int(n) > 0:
                cells[str(int(cell))] = cells.get(str(int(cell)), 0) + int(n)
        storage.kv_set(key, atlas)
        _atlas_cache.pop(key, None)
    done = body.get("sessions_done")
    if isinstance(done, list):
        k = "drops_done:" + wid
        cur = set((storage.kv_get(k) or {}).get("sessions") or [])
        cur |= {str(s)[:40] for s in done[:2000]}
        storage.kv_set(k, {"sessions": sorted(cur)})
    _cache.pop(wid, None)
    return {"ok": True, "stored": len(rows), "skipped": skipped}


# ---------------------------------------------------------------- chests: where they are and how often they are looted
# The replay has no chest objects, but when a player opens a chest its 5 or so loot items appear together at one spot.
# The landing tool finds those bursts (and removes player-death drops); the worker counts, per map cell, in how many
# matches a chest was opened during the first minutes. A chest is a spot where that keeps happening; its lootage rate is
# the share of matches in which it was opened early.
def _code(w):
    import re
    pl = (w.get("meta") or {}).get("playlist") or ""
    m = re.search(r"SourSpawn|BlastBerry|DashBerry|PiperBoot|JumpBear", pl, re.I)
    return m.group(0) if m else pl


def _atlas_key(w):
    return "chests:" + _code(w)


MIN_MATCHES = 20      # chest rates need at least this many matches behind them


_atlas_cache = {}      # key -> (time, atlas): the chest counts are a few hundred KB, do not read them on every request


def _sites(w):
    """Chest sites of the map this tournament was played on: [{x, y, rate, chests}] with x, y in 0-1 map units."""
    key = _atlas_key(w)
    hit = _atlas_cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        atlas = hit[1]
    else:
        atlas = storage.kv_get(key) or {}
        _atlas_cache[key] = (time.time(), atlas)
    M = int(atlas.get("matches") or 0)
    if M < MIN_MATCHES or not atlas.get("cells"):
        return [], M
    n = int(atlas.get("size") or CHEST)
    C = np.zeros((n, n), dtype=np.float32)
    for k, v in atlas["cells"].items():
        C[int(k) // n, int(k) % n] = v
    P = np.pad(C, 1)
    S = sum(P[dy:dy + n, dx:dx + n] for dy in range(3) for dx in range(3))     # 3x3 sum: a chest's openings spread over neighbouring cells
    P2 = np.pad(S, 2, constant_values=-1)
    peak = np.ones_like(S, dtype=bool)
    for dy in range(5):
        for dx in range(5):
            if dy == 2 and dx == 2:
                continue
            peak &= S >= P2[dy:dy + n, dx:dx + n]
    thr = max(3.0, 0.05 * M)                      # opened in at least 5% of matches (and 3 times): not a one-off drop
    ys, xs = np.nonzero(peak & (S >= thr))
    out, taken = [], set()
    for y, x in sorted(zip(ys.tolist(), xs.tolist()), key=lambda p: -S[p[0], p[1]]):
        if any(abs(x - a) <= 2 and abs(y - b) <= 2 for a, b in taken):
            continue                              # equal-height neighbours: keep one
        taken.add((x, y))
        r = float(S[y, x]) / M
        k = max(1, int(round(r))) if r > 1.4 else 1   # more than one opening per match at one spot: two chests close together
        out.append({"x": round((x + 0.5) / n, 4), "y": round((y + 0.5) / n, 4), "rate": round(min(1.0, r / k), 3), "chests": k})
    return out, M


def loot(window_id):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    sites, M = _sites(w)
    return {"matches": M, "sites": sites, "min_matches": MIN_MATCHES,
            "chests": sum(s["chests"] for s in sites),
            "note": None if sites else f"Chest positions need at least {MIN_MATCHES} processed matches of this map (have {M})."}


def _label(u, v):
    return f"{chr(65 + min(9, int(u * 10)))}{min(9, int(v * 10)) + 1}"


TEAM = {"solo": 1, "duos": 2, "trios": 3, "squads": 4}


def areas(window_id, top=100, game=0, radius=0.055, min_chests=4):
    """Spots around chest clusters: how many chests, how often they are looted early, how many players land there per
    game, and a loot score = chests / (players + 1). Sorted by that score: the most loot for the fewest players first."""
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    sites, M = _sites(w)
    if not sites:
        raise ValueError(f"Chest positions need at least {MIN_MATCHES} processed matches of this map (have {M}).")
    a = _arrays(window_id)
    done = (storage.kv_get("drops_done:" + window_id) or {}).get("sessions") or []
    matches = max(1, len(done))
    team_size = TEAM.get((w.get("meta") or {}).get("mode"), 1)
    per_match = len(a["game"]) / matches                       # teams per match
    base = _sel(a, game)
    nbase = max(1, int(base.sum()))
    left = list(range(len(sites)))
    out = []
    while left:
        near_of = lambda i: [j for j in left if (sites[i]["x"] - sites[j]["x"]) ** 2 + (sites[i]["y"] - sites[j]["y"]) ** 2 <= radius ** 2]
        seed = max(left, key=lambda i: len(near_of(i)))
        mem = near_of(seed)
        left = [j for j in left if j not in mem]
        ch = sum(sites[j]["chests"] for j in mem)
        cx = sum(sites[j]["x"] * sites[j]["chests"] for j in mem) / ch
        cy = sum(sites[j]["y"] * sites[j]["chests"] for j in mem) / ch
        rate = sum(sites[j]["rate"] * sites[j]["chests"] for j in mem) / ch
        reach = radius + 0.01
        near = base & ((a["x"] - cx) ** 2 + (a["y"] - cy) ** 2 <= reach ** 2)
        landings = int(near.sum())
        teams = landings / nbase * per_match                   # average teams landing here per game
        players = teams * team_size
        s = _stats(a, near, top)
        out.append({"label": _label(cx, cy), "x": round(cx, 4), "y": round(cy, 4), "r": round(reach, 3), "chests": ch,
                    "lootage": round(rate, 3), "landings": landings, "teams_per_game": round(teams, 2),
                    "players_per_game": round(players, 2), "chests_per_player": round(ch / max(players, 0.25), 2),
                    "score": round(ch / (players + 1), 2),   # loot per crowd: many chests AND few players (an empty corner with 3 chests is not the best pick)
                    "free_chests": round(ch * (1 - rate), 1),
                    "qualifier_share": s.get("qualifier_share"), "avg_points": s.get("avg_points"), "avg_placement_pct": s.get("avg_placement_pct")})
    out = [o for o in out if o["chests"] >= min_chests]
    groups = {}
    for o in out:
        groups.setdefault(o["label"], []).append(o)
    for label, g in groups.items():          # several areas in one grid square: A1a, A1b, ... from left to right
        if len(g) > 1:
            for n, o in enumerate(sorted(g, key=lambda o: (o["x"], o["y"]))):
                o["label"] = label + chr(97 + n)
    out.sort(key=lambda o: -o["score"])
    return {"areas": out, "matches": matches, "chest_matches": M, "team_size": team_size,
            "teams_per_match": round(per_match, 1), "game": game,
            "lobby": (w.get("meta") or {}).get("lobby") or config.LOBBY.get(((w.get("meta") or {}).get("game_type"), (w.get("meta") or {}).get("mode")))
            or int(a["placement"].max())}      # size unknown (Reload solo): the worst placement seen


def _area_loot(window_id, a, mask, base, poly):
    """Chests inside a drawn area and how crowded it is: None when chest positions are not known yet."""
    w = storage.get_window(window_id)
    sites, M = _sites(w)
    if not sites:
        return None
    sx = np.array([s["x"] for s in sites], dtype=np.float32)
    sy = np.array([s["y"] for s in sites], dtype=np.float32)
    inside = _in_poly(sx, sy, poly)
    chests = int(sum(s["chests"] for s, i in zip(sites, inside) if i))
    rate = (sum(s["rate"] * s["chests"] for s, i in zip(sites, inside) if i) / chests) if chests else None
    done = (storage.kv_get("drops_done:" + window_id) or {}).get("sessions") or []
    matches = max(1, len(done))
    per_match = len(a["game"]) / matches
    teams = float(mask.sum()) / max(1, int(base.sum())) * per_match
    players = teams * TEAM.get((w.get("meta") or {}).get("mode"), 1)
    return {"chests": chests, "lootage": None if rate is None else round(rate, 3), "teams_per_game": round(teams, 2),
            "players_per_game": round(players, 2), "chests_per_player": round(chests / max(players, 0.25), 2) if chests else 0,
            "free_chests": round(chests * (1 - rate), 1) if chests else 0, "chest_matches": M}
