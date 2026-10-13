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
