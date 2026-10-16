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
    # the big Battle Royale island (events with no Reload codename); its light-blue shallows count as water in the outline, hence the lower bar
    "BR": {"name": "Battle Royale island", "image": "/maps/br-island.jpg", "mask": "br-island", "min_on_land": 0.85, "rot": 1,
           "credit": "Map: Battle Royale island, Epic Games (overview image from fortnite-api.com)"},
}
# Maps read straight from the game files (the minimap texture Epic ships, see tools/mapfit/mapdump): the raw picture is sent as it is
# and the page turns it into the 0-1 frame with "fit" = {k: quarter turns counter-clockwise, L: width of the picture in frames,
# cx, cy: centre of the picture in the frame}. A map with a fit that was measured is listed here; a map without one is fitted
# from its real landings once enough exist (_auto_fit) and shown only when that fit is clear.
# Fits are measured twice: on the landings (land / sea) and then refined on the chest sites, which sit on buildings (tools/mapfit/align_chests.py):
# the width comes out about 1.58-1.60 frames for every Reload map. rot = quarter turns clockwise of the stored frame (see _turn).
_ROT = {"SourSpawn": 1, "PiperBoot": 2}
_RAW = {"BlastBerry": ("raw-blastberry", "Venture", {"k": 0, "L": 1.59, "cx": 0.507, "cy": 0.423}, 0.86),
        "SourSpawn": ("raw-nitemare", "Nitemare Island", {"k": 0, "L": 1.591, "cx": 0.4641, "cy": 0.5028}, 0.9),   # re-fitted on fortnite.gg chest icons (tools/mapfit/validate_fortnitegg.py)
        "PiperBoot": ("raw-surfcity", "Surf City V1", {"k": 0, "L": 1.5846, "cx": 0.4985, "cy": 0.5034}, 0.9),   # re-fitted on fortnite.gg chest icons
        "DashBerry": ("raw-dashberry", "Springfield", None, None),
        "ForbiddenBlastBerry": ("raw-forbiddenblastberry", "Venture (Blitz)", None, None),
        "MatchMist": ("raw-matchmist", "Elite Stronghold", None, None),
        "PunchBerry": ("raw-punchberry", "Oasis", None, None),
        "RopeSmile": ("raw-ropesmile", "RopeSmile", None, None),
        "TigerRanch": ("raw-tigerranch", "Slurp Rush", None, None),
        "TimberStake": ("raw-timberstake", "Squid Grounds", None, None)}
for _c, (_f, _n, _fit, _min) in _RAW.items():
    MAPS[_c] = {"name": _n, "raw": "/maps/%s.jpg" % _f, "mask": _f, "credit": "Map: %s, Epic Games (map texture from the game files)" % _n}
    if _fit:
        MAPS[_c]["fit"] = _fit
        MAPS[_c]["rot"] = _ROT.get(_c, 0)
    if _min:
        MAPS[_c]["min_on_land"] = _min
CODENAMES = ("ForbiddenBlastBerry", "SourSpawn", "BlastBerry", "DashBerry", "PiperBoot", "JumpBear", "MatchMist", "PunchBerry", "RopeSmile",
             "TigerRanch", "TimberStake")
# The loaders store landings in the game's own frame (u = east, v = south). Each map is shown the way the game draws it (north up, like the
# in-game map and fortnite.gg), which is that frame turned a whole number of quarter turns clockwise: MAPS[code]["rot"] for the maps we turned by
# hand, and for a raw texture the turn the landings fit found (kv maprot:<code>). _turn applies it to points; _arrays and _sites use it.
MIN_ON_LAND = 0.93


def _turn(x, y, n):
    """Points of the stored frame turned n quarter turns clockwise."""
    n %= 4
    if n == 0:
        return x, y
    if n == 1:
        return 1 - y, x
    if n == 2:
        return 1 - x, 1 - y
    return y, 1 - x


def _known_of(w):
    code = _code(w)
    return code, (MAPS.get(code) or (MAPS["BR"] if (w.get("meta") or {}).get("game_type") == "br" else None))


def _rot_of(w):
    """Quarter turns clockwise that put this tournament's map the way the game draws it."""
    code, known = _known_of(w)
    if not known:
        return 0
    if "rot" in known:
        return known["rot"]
    return int(storage.kv_get("maprot:" + code) or 0)     # a registered picture is only shown while at least this share of the real landings is on its land
_masks = {}
WIDE = (-0.7, 1.7)     # stored coordinates may lie outside the old 0-1 frame: the islands are bigger than the frame the loaders used


def _view(code):
    """(x0, y0, s): the square of the turned frame that holds ALL the land of a map with a measured picture fit (plus a small margin).
    The site works in this square: 0-1 is the whole island, so nothing of the map is cut off and the grid A1-J10 covers all of it."""
    known = MAPS.get(code)
    if not known or not known.get("fit") or not known.get("mask"):
        return (0.0, 0.0, 1.0)
    if code not in _views:
        m = _land_mask(known["mask"])
        n = m.shape[0]
        cols, rows = np.cumsum(m.sum(axis=0)), np.cumsum(m.sum(axis=1))
        tot = cols[-1]
        lo = lambda c: int(np.searchsorted(c, tot * 0.0005))
        hi = lambda c: int(np.searchsorted(c, tot * 0.9995))
        f = known["fit"]
        fx = lambda u: f["cx"] + (u / n - 0.5) * f["L"]
        fy = lambda v: f["cy"] + (v / n - 0.5) * f["L"]
        x0, x1, y0, y1 = fx(lo(cols)), fx(hi(cols) + 1), fy(lo(rows)), fy(hi(rows) + 1)
        side = min(f["L"], max(x1 - x0, y1 - y0) * 1.06 + 0.01)
        _views[code] = (round((x0 + x1) / 2 - side / 2, 4), round((y0 + y1) / 2 - side / 2, 4), round(side, 4))
    return _views[code]


_views = {}


def _vwin(w):
    code, known = _known_of(w) if w else (None, None)
    return _view(code) if known else (0.0, 0.0, 1.0)


def _fit_view(fit, v):
    """A picture fit (turned frame) expressed in the view square."""
    return {**fit, "L": round(fit["L"] / v[2], 4), "cx": round((fit["cx"] - v[0]) / v[2], 4), "cy": round((fit["cy"] - v[1]) / v[2], 4)}


def _land_mask(name):
    """Land/water outline that goes with a map picture (tools/mapfit/make_mask.py), as a boolean array."""
    if name not in _masks:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "maps", name + ".mask.json")
        d = json.load(open(path))
        _masks[name] = np.array([[c == "1" for c in row] for row in d["rows"]], dtype=bool)
    return _masks[name]


_oriented = {}


def _oriented_mask(name, k):
    if (name, k) not in _oriented:
        _oriented[(name, k)] = np.rot90(_land_mask(name), k)
    return _oriented[(name, k)]


def _hits(m, fit, x, y):
    n = m.shape[0]
    iu = (x - fit["cx"]) / fit["L"] + 0.5
    iv = (y - fit["cy"]) / fit["L"] + 0.5
    ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
    return m[np.clip((iv * n).astype(int), 0, n - 1), np.clip((iu * n).astype(int), 0, n - 1)] & ok


def _on_land(m, fit, x, y):
    """Share of the points (frame coordinates) that fall on land of a raw picture placed with fit."""
    return float(_hits(m, fit, x, y).mean())


def _loglik(m, fit, x, y):
    """Mean log-likelihood of the landings if they are spread evenly over the picture's land (a picture that is too big or too small scores low)."""
    return float(np.log((_hits(m, fit, x, y).astype(float) + 0.02) / (m.mean() * fit["L"] ** 2 + 0.02)).mean())


def _auto_fit(code, known, a):
    """Find how a raw map picture sits in the frame from real landings: 4 quarter turns x centre, the width fixed at the
    1.55 every Reload map has. Accepted only when one turn is clearly better than the others and the landings lie on land."""
    x, y = a.get("x0", a["x"]).astype(float), a.get("y0", a["y"]).astype(float)   # the stored frame: the turn that puts the picture upright is what we find
    if len(x) < 300:
        return None
    if len(x) > 6000:
        i = np.random.default_rng(1).choice(len(x), 6000, replace=False)
        x, y = x[i], y[i]
    best = {}
    for k in range(4):
        m = _oriented_mask(known["mask"], k)
        top = None
        for cx in np.arange(0.35, 0.651, 0.025):
            for cy in np.arange(0.35, 0.651, 0.025):
                f = {"k": k, "L": 1.55, "cx": round(float(cx), 3), "cy": round(float(cy), 3)}
                sc = _loglik(m, f, x, y)
                if top is None or sc > top[0]:
                    top = (sc, f)
        best[k] = top
    order = sorted(best.values(), key=lambda t: -t[0])
    gap = order[0][0] - order[1][0]
    f = order[0][1]
    m = _oriented_mask(known["mask"], f["k"])
    top = (order[0][0], f)
    for L in np.arange(1.50, 1.601, 0.01):
        for cx in np.arange(f["cx"] - 0.025, f["cx"] + 0.0251, 0.005):
            for cy in np.arange(f["cy"] - 0.025, f["cy"] + 0.0251, 0.005):
                g = {"k": f["k"], "L": round(float(L), 3), "cx": round(float(cx), 3), "cy": round(float(cy), 3)}
                sc = _loglik(m, g, x, y)
                if sc > top[0]:
                    top = (sc, g)
    share = _on_land(m, top[1], x, y)
    if gap < 0.05 or share < known.get("min_on_land", MIN_ON_LAND) - 0.03:
        return None
    g = top[1]
    cx, cy = _turn(g["cx"], g["cy"], g["k"])     # shown turned k quarter turns clockwise: the picture is then upright (k = 0) and its centre moves with it
    return {"k": 0, "L": g["L"], "cx": round(float(cx), 3), "cy": round(float(cy), 3), "rot": int(g["k"]), "on_land": round(share, 3), "gap": round(gap, 3), "n": int(len(x))}


def _fit_of(code, known, window_id):
    """The fit of a raw picture: the measured one, the one stored from an earlier tournament, or one found now from the landings."""
    if known.get("fit"):
        return known["fit"]
    saved = storage.kv_get("mapfit:" + code)
    if saved:
        return saved
    try:
        a = _arrays(window_id)
    except ValueError:
        return None
    f = _auto_fit(code, known, a)
    if f:
        storage.kv_set("mapfit:" + code, f)
        storage.kv_set("maprot:" + code, f["rot"])
        _cache.clear()                           # the landings are turned differently from now on
    return f


def picture_check(window_id, known, code=None):
    """Share of this tournament's landings that fall on land of the registered picture (None: no landings to test with)."""
    try:
        a = _arrays(window_id)
    except ValueError:
        return None
    if known.get("raw"):
        fit = _fit_of(code, known, window_id)
        if not fit:
            return None
        a = _arrays(window_id)
        return _on_land(_oriented_mask(known["mask"], fit["k"]), _fit_view(fit, a["view"]), a["x"].astype(float), a["y"].astype(float))
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
    codename = next((t for t in CODENAMES if t.lower() in playlist.lower()), None)
    label = "Reload map" if reload_ else "Battle Royale island"
    rec = storage.drop_map_get(window_id) if hasattr(storage, "drop_map_get") else None
    known = MAPS.get(codename) or (MAPS["BR"] if not reload_ and meta.get("game_type") == "br" else None)
    check = None
    if known:   # a known map picture wins over the background drawn from player movement, but only while the landings agree with it
        rec = {**(rec or {}), **known}
        share = picture_check(window_id, known, codename) if known.get("mask") else None
        need = known.get("min_on_land", MIN_ON_LAND)
        n_land = len(_arrays(window_id)["x"]) if share is not None else 0
        slack = 1.64 * math.sqrt(max(share, 0.0) * (1 - share) / max(n_land, 1)) if share is not None else 0   # a small sample may fall a little short by chance
        check = {"on_land": None if share is None else round(share, 3), "min": need,
                 "status": "untested" if share is None else "ok" if share + slack >= need else "mismatch"}
        if known.get("raw"):   # a raw game texture is only shown once its place in the frame is known and the landings agree with it
            fit = _fit_of(codename, known, window_id) if check["status"] == "ok" else None
            if fit:
                rec["image"] = known["raw"]
                rec["fit"] = _fit_view({k: fit[k] for k in ("k", "L", "cx", "cy")}, _view(codename))
            else:
                rec["image"] = ""
                rec["name"] = ""
                rec.pop("credit", None)
            rec.pop("raw", None)
        if check["status"] == "mismatch":   # wrong map picture: never show it
            rec = {k: v for k, v in rec.items() if k not in ("image", "name", "credit", "fit")}
            rec["image"] = ""
            rec["name"] = ""
        rec.pop("mask", None)
    rec = dict(rec or {})
    if rec.get("pois"):   # stored in the loader's frame: same turn as everything else
        nrot, vw = _rot_of(w), _view(codename)
        rec["pois"] = [{**p, "x": round((float(_turn(float(p["x"]), float(p["y"]), nrot)[0]) - vw[0]) / vw[2], 4), "y": round((float(_turn(float(p["x"]), float(p["y"]), nrot)[1]) - vw[1]) / vw[2], 4)} for p in rec["pois"]]
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
    row = next((r for r in storage.window_list() if r["window_id"] == window_id), None)
    x0 = np.array([r[2] for r in rows], dtype=np.float32)
    y0 = np.array([r[3] for r in rows], dtype=np.float32)
    nrot = _rot_of(row) if row else 0
    xt, yt = _turn(x0, y0, nrot)
    v = _vwin(row)
    xt, yt = (xt - v[0]) / v[2], (yt - v[1]) / v[2]
    keep = (xt >= 0) & (xt <= 1) & (yt >= 0) & (yt <= 1)         # the sea beyond the picture is not part of the map
    if not keep.all():
        rows = [r for r, k in zip(rows, keep) if k]
        x0, y0, xt, yt = x0[keep], y0[keep], xt[keep], yt[keep]
        if not rows:
            raise ValueError("No landing data has been loaded for this tournament yet.")
    a = {"view": v, "game": np.array([r[0] for r in rows], dtype=np.int16), "team": [r[1] for r in rows],
         "x": xt.astype(np.float32), "y": yt.astype(np.float32), "x0": x0, "y0": y0, "rot": nrot,
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
    # the teams that landed here with the best final rank in the event, with what they did from this spot
    ranked = [i for i in idx if a["rank"][i] > 0]
    groups = {}
    for i in ranked:
        groups.setdefault(a["team"][i], []).append(int(i))
    order = sorted(groups.items(), key=lambda kv: min(int(a["rank"][i]) for i in kv[1]))[:12]
    tids = [t for team, _ in order for t in team.split("+") if HEX32.match(t)]
    tnames = insights._name_map(tids) if tids else {}
    out["teams"] = [{"team": " + ".join(tnames.get(t, t[:8]) if HEX32.match(t) else t for t in team.split("+")),
                     "rank": min(int(a["rank"][i]) for i in ids_), "landings": len(ids_),
                     "games": sorted({int(a["game"][i]) for i in ids_ if a["game"][i] > 0})[:12],
                     "avg_points": round(float(np.mean([a["points"][i] for i in ids_])), 1),
                     "best_placement": int(min(a["placement"][i] for i in ids_))} for team, ids_ in order]
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
        if not (math.isfinite(x) and math.isfinite(y)) or not (WIDE[0] <= x <= WIDE[1] and WIDE[0] <= y <= WIDE[1]):
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
    m = re.search("|".join(CODENAMES), pl, re.I)
    return m.group(0) if m else pl


def _atlas_key(w):
    return "chests:" + _code(w)


MIN_MATCHES = 20      # chest rates need at least this many matches behind them


_atlas_cache = {}      # key -> (time, atlas): the chest counts are a few hundred KB, do not read them on every request


CTN_KINDS = ("chest", "rare", "ammo", "produce", "cash", "fishing")
CHEST_KINDS = ("chest", "rare")


def _map_key(w):
    """One key per map: its codename, or BR for the Battle Royale island (every BR playlist is the same map)."""
    code = _code(w)
    if code in CODENAMES:
        return code
    return "BR" if (w.get("meta") or {}).get("game_type") == "br" else code


def _ctn_key(w):
    return "ctn2:" + _map_key(w)      # v2: positions outside the old 0-1 frame are kept (v1 "ctn:" lost them)


def _kind(name):
    """What a placed container is, from the unique name the replay gives it."""
    if name.startswith("AlwaysSpawn_RareChest"):
        return "rare"
    if name.startswith(("Tiered_Chest", "AlwaysSpawn_NormalChest")):
        return "chest"
    if name.startswith("Tiered_Ammo"):
        return "ammo"
    if name.startswith("FoodBox_Produce"):
        return "produce"
    if "CashRegister" in name:
        return "cash"
    if name.startswith("Barrel_FishingRod"):
        return "fishing"
    return None


def _row_of(window_id):
    return next((r for r in storage.window_list() if r["window_id"] == window_id), None)


def add_containers(window_id, batch):
    """Container positions read from replays (worker/landings Containers.cs): batch = [{session, items: [[name, u, v], ...]}], u, v in the
    loaders frame. Per container name the site keeps how many matches it was searched in and up to 15 positions (the median is its place)."""
    w = _row_of(window_id)
    if not w:
        raise ValueError("Unknown window")
    key = _ctn_key(w)
    atlas = storage.kv_get(key) or {"M": 0, "done": [], "items": {}}
    done = set(atlas.get("done") or [])
    added = 0
    for b in batch or []:
        sid = str(b.get("session") or "")[:12]
        if not sid or sid in done:
            continue
        done.add(sid)
        atlas["M"] = int(atlas.get("M") or 0) + 1
        added += 1
        for name, u, v in b.get("items") or []:
            if _kind(str(name)) is None or not (WIDE[0] <= float(u) <= WIDE[1] and WIDE[0] <= float(v) <= WIDE[1]):
                continue
            it = atlas["items"].setdefault(str(name), {"n": 0, "p": []})
            it["n"] += 1
            it["p"].append([round(float(u), 4), round(float(v), 4)])
            if len(it["p"]) > 15:
                it["p"].pop(0)
    atlas["done"] = sorted(done)
    storage.kv_set(key, atlas)
    _atlas_cache.pop(key, None)
    return {"ok": True, "added": added, "matches": atlas["M"], "containers": len(atlas["items"])}


def _container_sites(w, kinds):
    def load(key):
        hit = _atlas_cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        atlas = storage.kv_get(key) or {}
        _atlas_cache[key] = (time.time(), atlas)
        return atlas
    new, old = load(_ctn_key(w)), load("ctn:" + _map_key(w))      # v2 keeps positions outside the old 0-1 frame; v1 lost them but has more matches
    M2, M1 = int(new.get("M") or 0), int(old.get("M") or 0)
    if M1 < MIN_MATCHES and M2 < MIN_MATCHES:
        return None, max(M1, M2)
    # a container seen in the older counts keeps its place and rate; the ones only the newer counts have (the ones outside the old frame) are added
    items = {n: (it, M1) for n, it in (old.get("items") or {}).items()} if M1 >= MIN_MATCHES else {}
    for n, it in (new.get("items") or {}).items():
        if n not in items and M2 >= 3:
            items[n] = (it, M2)
    nrot = _rot_of(w)
    out = []
    for name, (it, M) in items.items():
        kind = _kind(name)
        if kind not in kinds or not it.get("p"):
            continue
        u = float(np.median([p[0] for p in it["p"]]))
        v = float(np.median([p[1] for p in it["p"]]))
        x, y = _turn(u, v, nrot)
        out.append({"x": round(float(x), 4), "y": round(float(y), 4), "rate": round(min(1.0, it["n"] / M), 3), "chests": 1, "cls": kind})
    return out, max(M1, M2)


def _sites(w, frac=None, nms=1, smooth=0, kinds=CHEST_KINDS):
    got, M = _sites_turned(w, frac, nms, smooth, kinds)
    v = _vwin(w)
    if v != (0.0, 0.0, 1.0):
        got = [{**c, "x": round((c["x"] - v[0]) / v[2], 4), "y": round((c["y"] - v[1]) / v[2], 4)} for c in got]
        got = [c for c in got if -0.01 <= c["x"] <= 1.01 and -0.01 <= c["y"] <= 1.01]
    return got, M


def _sites_turned(w, frac=None, nms=1, smooth=0, kinds=CHEST_KINDS):
    """Chest sites of the map this tournament was played on: [{x, y, rate, chests}] with x, y in 0-1 map units. Real container positions
    (every placed chest, read from replays) when enough matches were processed, else peaks of the loot-burst map."""
    got, M = _container_sites(w, kinds)
    if got is not None:
        return got, M
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
    C = np.rot90(C, -_rot_of(w)).copy()           # same turn as the landings
    k = 2 * smooth + 1
    P = np.pad(C, smooth)
    S = sum(P[dy:dy + n, dx:dx + n] for dy in range(k) for dx in range(k))     # a chest's openings spread over neighbouring cells
    P2 = np.pad(S, nms, constant_values=-1)
    peak = np.ones_like(S, dtype=bool)
    for dy in range(2 * nms + 1):
        for dx in range(2 * nms + 1):
            if dy == nms and dx == nms:
                continue
            peak &= S >= P2[dy:dy + n, dx:dx + n]
    # Placed chests are counted by the peaks of the opening map (one peak per chest: towns hold chests a few metres apart, so no wide
    # smoothing or merge radius). Calibrated on Nitemare Island: this gives about 470 sites, the number of chests the map has
    # (437 distinct chest names seen across five replays; fortnite.gg lists about 470).
    thr = max(3.0, (frac if frac is not None else 0.01) * M)                      # opened in at least 1% of matches (and 3 times): not a one-off drop
    R3 = sum(np.pad(C, 1)[dy:dy + n, dx:dx + n] for dy in range(3) for dx in range(3))   # the chest's openings spread over a few cells: its rate uses all of them
    ys, xs = np.nonzero(peak & (S >= thr))
    out, taken = [], set()
    for y, x in sorted(zip(ys.tolist(), xs.tolist()), key=lambda p: -S[p[0], p[1]]):
        if any(abs(x - a) <= nms and abs(y - b) <= nms for a, b in taken):
            continue                              # equal-height neighbours: keep one
        taken.add((x, y))
        r = float(S[y, x]) / M
        k = max(1, int(round(r))) if r > 1.4 else 1   # more than one opening per match at one spot: two chests close together
        out.append({"x": round((x + 0.5) / n, 4), "y": round((y + 0.5) / n, 4), "rate": round(min(1.0, max(r, float(R3[y, x]) / M) / k), 3), "chests": k})
    return _on_land_only(w, out), M


def _on_land_only(w, sites):
    """A chest is never in the sea: drop the sites that fall in open water of the map's own land outline (a few metres of shore are allowed)."""
    try:
        code = _code(w)
        known = MAPS.get(code) or (MAPS["BR"] if (w.get("meta") or {}).get("game_type") == "br" else None)
        if not known or not known.get("mask") or not sites:
            return sites
        m = _land_mask(known["mask"])
        fit = {"cx": 0.5, "cy": 0.5, "L": 1.0}
        if known.get("raw"):
            fit = known.get("fit") or storage.kv_get("mapfit:" + code)
            if not fit:
                return sites
            m = _oriented_mask(known["mask"], fit["k"])
        grow = 3 if known is MAPS["BR"] else 2        # the BR outline treats shallows as water: allow more shore there
        n = m.shape[0]
        P = np.pad(m, grow)
        near = np.zeros_like(m)
        for dy in range(2 * grow + 1):
            for dx in range(2 * grow + 1):
                near |= P[dy:dy + n, dx:dx + n]
        x = np.array([c["x"] for c in sites], dtype=np.float32)
        y = np.array([c["y"] for c in sites], dtype=np.float32)
        keep = _hits(near, fit, x, y)
        return [c for c, k in zip(sites, keep) if k]
    except Exception:
        return sites


def loot(window_id, frac=None, nms=1, smooth=0, kinds=None):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    want = tuple(k for k in (kinds or CHEST_KINDS) if k in CTN_KINDS) or CHEST_KINDS
    sites, M = _sites(w, frac, nms, smooth, want)
    counts = {}
    for s_ in sites:
        counts[s_.get("cls", "chest")] = counts.get(s_.get("cls", "chest"), 0) + 1
    return {"matches": M, "view": list(_vwin(w)), "sites": sites, "min_matches": MIN_MATCHES, "kinds": counts, "exact": bool(sites and sites[0].get("cls")),
            "chests": sum(s["chests"] for s in sites if s.get("cls", "chest") in CHEST_KINDS),
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


# ---------------------------------------------------------------- the interactive map tab: every map with chest data
# Every map fortnite.gg lists, by the name the game uses: (key, name, mode, picture). The key is the playlist codename (or BR); the
# picture is the real map texture where the game files have it, else the wiki icon, else none. Matched to the game textures by their
# named locations and by looking at each map side by side (MatchMist = Elite Stronghold: ELITE EXPERIMENTS, TOP TIER TRAINING...).
CATALOG = [
    ("BR", "Battle Royale", "Battle Royale", "/maps/br-island.jpg"),
    ("OG", "OG", "OG", "/maps/og.jpg"),
    ("ForbiddenBlastBerry", "Venture", "Blitz", "/maps/raw-forbiddenblastberry.jpg"),
    ("Asteria", "Asteria Awakened", "Blitz", ""),
    ("Hawkins", "Stranger Things", "Blitz", "/maps/icon-hawkins.png"),
    ("Starfall", "Starfall Island", "Blitz", "/maps/icon-starfall.png"),
    ("Stark", "Stark Island", "Blitz", "/maps/icon-stark.png"),
    ("BlastBerry", "Venture", "Reload", "/maps/raw-blastberry.jpg"),
    ("PunchBerry", "Oasis", "Reload", "/maps/raw-punchberry.jpg"),
    ("TigerRanch", "Slurp Rush", "Reload", "/maps/raw-tigerranch.jpg"),
    ("TimberStake", "Squid Grounds", "Reload", "/maps/raw-timberstake.jpg"),
    ("PiperBoot", "Surf City V1", "Reload", "/maps/raw-surfcity.jpg"),
    ("SourSpawn", "Nitemare Island", "Reload", "/maps/raw-nitemare.jpg"),
    ("MatchMist", "Elite Stronghold", "Reload", "/maps/raw-matchmist.jpg"),
    ("DashBerry", "Springfield", "Reload", "/maps/raw-dashberry.jpg"),
]


def maps():
    """Every map with its picture, and for the ones we have chest data for the tournament to read its sites from."""
    avail = storage.drops_available()
    best = {}
    for w in storage.window_list():
        if w["window_id"] not in avail:
            continue
        key = _map_key(w)
        n = avail[w["window_id"]][0]
        if key not in best or n > best[key][0]:
            best[key] = (n, w)
    out = []
    for key, name, mode, picture in CATALOG:
        row = {"key": key, "name": name, "mode": mode, "image": picture, "window_id": None, "matches": 0, "chests": 0, "kinds": {}, "landings": 0}
        if key in best:
            n, w = best[key]
            sites, M = _sites(w, kinds=CTN_KINDS)
            if sites:
                kinds = {}
                for c in sites:
                    kinds[c.get("cls", "chest")] = kinds.get(c.get("cls", "chest"), 0) + 1
                row.update(window_id=w["window_id"], matches=M, landings=n, region=w["region"], kinds=kinds,
                           chests=sum(v for k, v in kinds.items() if k in CHEST_KINDS))
        out.append(row)
    return out
