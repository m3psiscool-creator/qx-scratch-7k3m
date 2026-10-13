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
    for col in ("meta", "sessions"):  # added later; migrate old databases
        try:
            c.execute(f"ALTER TABLE windows ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    return c


def upsert_window(w):
    with db() as c:
        c.execute("""INSERT INTO windows(window_id,event_id,family,region,begin,end,meta)
                     VALUES(:window_id,:event_id,:family,:region,:begin,:end,:meta)
                     ON CONFLICT(window_id) DO UPDATE SET
                       begin=excluded.begin, end=excluded.end, meta=excluded.meta""",
                  {**w, "meta": json.dumps(w.get("meta") or {})})


def save_final(window_id, lb):
    with db() as c:
        c.execute("UPDATE windows SET entrants=?,points=?,games=?,sessions=?,final=1"
                  " WHERE window_id=?",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(lb.get("sessions", [])), window_id))


def save_snapshot(window_id, lb, ts=None):
    with db() as c:
        c.execute("INSERT INTO snapshots(window_id,ts,entrants,points,games) VALUES(?,?,?,?,?)",
                  (window_id, ts or time.time(), lb["entrants"],
                   json.dumps(lb["points"]), json.dumps(lb["games"])))


def _w(r):
    d = dict(r)
    d["points"] = json.loads(d["points"]) if d["points"] else []
    d["games"] = json.loads(d["games"]) if d["games"] else []
    d["sessions"] = json.loads(d["sessions"]) if d.get("sessions") else []
    d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
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
