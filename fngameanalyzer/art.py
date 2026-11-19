"""Tournament artwork: Epic's own public tournament list (no login, no database).

Every tournament Epic shows in the game's competitive tab has a background picture on Epic's CDN plus two brand
colours. `compact()` returns them in a small shape the site matches to its own events (see `artFor` in web/lib.js).
The pictures themselves are never copied: the browser loads them straight from Epic's CDN."""
import json
import re
import time
import urllib.request

URL = "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/tournamentinformation"
HOST = "https://cdn2.unrealengine.com/"
TTL = 6 * 3600
_C = {"t": 0, "v": None}
_REGION_TAIL = re.compile(r"(nac|naw|nae|eu|br|asia|me|oce)$", re.I)
_HEX = re.compile(r"^[0-9a-fA-F]{6}$")


def _fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; fan-site)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def build(raw):
    """raw page -> {"imgs": [url, ...], "items": [[season, key, title, img_index, colour1, colour2], ...]}"""
    imgs, index, items, seen = [], {}, [], set()
    for key, v in raw.items():
        ti = v.get("tournament_info") if isinstance(v, dict) else None
        m = re.match(r"^s(\d{2})(.+)$", key, re.I)
        if not ti or not m or key.endswith("Copy") or "testing" in key.lower():
            continue
        rest = m.group(2)
        if _REGION_TAIL.search(rest) and rest.lower() not in ("eu",):
            continue   # per-region duplicates of the same cup
        img = ti.get("tournament_view_background_image") or ti.get("playlist_tile_image") or ti.get("square_poster_image")
        if not img or not img.startswith(HOST):
            continue
        sig = (int(m.group(1)), rest.lower())
        if sig in seen:
            continue
        seen.add(sig)
        if img not in index:
            index[img] = len(imgs)
            imgs.append(img)
        col = lambda k: ti.get(k) if _HEX.match(str(ti.get(k) or "")) else ""
        items.append([int(m.group(1)), rest.lower(), (ti.get("title_line_1") or "").strip(), index[img],
                      col("background_left_color"), col("background_right_color")])
    items.sort(key=lambda x: -x[0])
    return {"imgs": imgs, "items": items}


def compact():
    now = time.time()
    if _C["v"] is not None and now - _C["t"] < TTL:
        return _C["v"]
    try:
        _C["v"] = build(_fetch())
        _C["t"] = now
    except Exception:
        if _C["v"] is None:
            return {"imgs": [], "items": [], "error": "Epic's tournament list is not reachable"}
    return _C["v"]
