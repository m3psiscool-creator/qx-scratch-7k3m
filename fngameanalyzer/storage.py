import json
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows(
 window_id TEXT PRIMARY KEY, event_id TEXT, family TEXT, region TEXT,
 begin REAL, end REAL, entrants INTEGER, points TEXT, games TEXT, final INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS snapshots(
 id INTEGER PRIMARY KEY AUTOINCREMENT, window_id TEXT, ts REAL,
 entrants INTEGER, points TEXT, games TEXT);
"""


def db():
    c = sqlite3.connect(config.DB_FILE)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def upsert_window(w):
    with db() as c:
        c.execute("""INSERT INTO windows(window_id,event_id,family,region,begin,end)
                     VALUES(:window_id,:event_id,:family,:region,:begin,:end)
                     ON CONFLICT(window_id) DO UPDATE SET end=excluded.end""", w)


def save_final(window_id, lb):
    with db() as c:
        c.execute("UPDATE windows SET entrants=?,points=?,games=?,final=1 WHERE window_id=?",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]), window_id))


def save_snapshot(window_id, lb, ts=None):
    with db() as c:
        c.execute("INSERT INTO snapshots(window_id,ts,entrants,points,games) VALUES(?,?,?,?,?)",
                  (window_id, ts or time.time(), lb["entrants"],
                   json.dumps(lb["points"]), json.dumps(lb["games"])))


def _w(r):
    d = dict(r)
    d["points"] = json.loads(d["points"]) if d["points"] else []
    d["games"] = json.loads(d["games"]) if d["games"] else []
    return d


def windows(final=None):
    q = "SELECT * FROM windows" + ("" if final is None else f" WHERE final={int(final)}")
    with db() as c:
        return [_w(r) for r in c.execute(q + " ORDER BY end DESC")]


def get_window(window_id):
    with db() as c:
        r = c.execute("SELECT * FROM windows WHERE window_id=?", (window_id,)).fetchone()
    return _w(r) if r else None


def snapshots(window_id):
    with db() as c:
        rows = c.execute("SELECT * FROM snapshots WHERE window_id=? ORDER BY ts", (window_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["points"] = json.loads(d["points"])
            d["games"] = json.loads(d["games"])
            out.append(d)
    return out
