"""Event class: '<reload|br> [zb] <solo|duo|trio|squads> [mobile]', e.g. 'reload zb duo'.

History is only ever compared within the same class."""
import re

from . import config

MODES = {"solo": "solo", "duos": "duo", "trios": "trio", "squads": "squads"}
ZB_RE = re.compile(r"zb|nobuild|zerobuild", re.I)


def category(event_id, window_id, playlist, game_type, mode):
    text = f"{event_id} {window_id} {playlist}"
    parts = [game_type or "br"]
    if ZB_RE.search(text):
        parts.append("zb")
    parts.append(MODES.get(mode, mode or "?"))
    if "mobile" in text.lower():
        parts.append("mobile")
    return " ".join(parts)


def of(w):
    """Class of a stored window (computed if an older row has none)."""
    m = w.get("meta") or {}
    return m.get("category") or category(w.get("event_id") or "", w.get("window_id") or "",
                                         m.get("playlist"), m.get("game_type"), m.get("mode"))


def goal_of(meta):
    """The rank an event is really about: last place with cosmetics, else last paid place, else the
    advancement cutoff. Stored in meta at sync time so slim rows already carry it."""
    if (meta or {}).get("goal"):
        return meta["goal"]
    tiers = ((meta or {}).get("rewards") or {}).get("tiers") or []
    rank = [t for t in tiers if t["kind"] == "rank"]
    kinds = lambda t: {i["type"] for i in t["items"]}
    items = [t for t in rank if "item" in kinds(t)]
    if items:
        t = max(items, key=lambda x: x["upto"])
        what = ", ".join(sorted({i["kind"] for i in t["items"] if i["type"] == "item"}))
        return {"rank": t["upto"], "kind": "cosmetics", "label": f"last place that wins the cosmetics ({what})"}
    cash = [t for t in rank if "cash" in kinds(t)]
    if cash:
        t = max(cash, key=lambda x: x["upto"])
        usd = [i["usd"] for i in t["items"] if i["type"] == "cash"]
        return {"rank": t["upto"], "kind": "cash", "label": f"last paid place (${usd[0]:,})" if usd else "last paid place"}
    adv = [t for t in rank if "advance" in kinds(t)]
    if adv:
        t = min(adv, key=lambda x: x["upto"])
        return {"rank": t["upto"], "kind": "advance", "label": "cutoff to advance"}
    return None
