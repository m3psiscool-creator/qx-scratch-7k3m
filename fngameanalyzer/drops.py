"""Dropspots: where teams landed in a tournament and what happened to them afterwards.

Epic's leaderboard has no location data, so landing rows come from a loader (the owner-only endpoint
/api/admin/drops, see docs/dropspots-data.md). This module stores them, aggregates them for the map and
describes the map an event is played on."""
import math
import re
import time

import numpy as np

from . import classify, insights, rules, service, storage

GRID = 96
BASE = 128           # resolution of the background map drawn from player movement
_cache = {}          # window_id -> (time, arrays); a tournament is a few tens of thousands of rows
CACHE_TTL = 300
HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------- what map is this event played on
# Maps we have a picture for, by the codename in the playlist id. The picture is drawn in the same 0-1 frame as the
# landings (north-up is NOT assumed: it is the picture rotated/scaled to match the game's own coordinates, see
# docs/dropspots-data.md "Map pictures"). Picture: Epic Games' overview image of the map, via the Fortnite Wiki.
MAPS = {
    "SourSpawn": {"name": "Nitemare Island", "image": "/maps/nitemare-island.jpg",
                  "credit": "Map: Nitemare Island, Epic Games (overview image from the Fortnite Wiki)"},
}


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
    if known:   # a known map picture wins over the background drawn from player movement
        rec = {**(rec or {}), **known}
        rec.pop("base", None)
    avail = storage.drops_available() if hasattr(storage, "drops_available") else {}
    return {"window_id": window_id, "name": service.pretty(w.get("event_id") or "", window_id), "region": w["region"],
            "begin": w["begin"], "end": w["end"], "final": bool(w["final"]),
            "playlist": playlist, "game_type": meta.get("game_type"), "mode": meta.get("mode"), "build": build, "codename": codename,
            "label": label, "match_cap": meta.get("match_cap"), "goal": service.goal_of(meta),
            "map": rec, "landings": (avail.get(window_id) or (0, 0))[0], "games": (avail.get(window_id) or (0, 0))[1],
            "note": ("The map is named by whoever loads the landing data. Epic's event data only says which playlist the event uses."
                     if not rec else None)}


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
            "games": sorted(int(g) for g in np.unique(a["game"])), "top": top}


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
    done = body.get("sessions_done")
    if isinstance(done, list):
        k = "drops_done:" + wid
        cur = set((storage.kv_get(k) or {}).get("sessions") or [])
        cur |= {str(s)[:40] for s in done[:2000]}
        storage.kv_set(k, {"sessions": sorted(cur)})
    _cache.pop(wid, None)
    return {"ok": True, "stored": len(rows), "skipped": skipped}
