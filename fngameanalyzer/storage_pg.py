"""Postgres storage (Neon via Vercel). Same functions as storage.py (sqlite, used locally)."""
import contextlib
import json
import os
import threading
import time

import psycopg

URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows(
 window_id TEXT PRIMARY KEY, event_id TEXT, family TEXT, region TEXT,
 begin_ts DOUBLE PRECISION, end_ts DOUBLE PRECISION, entrants INTEGER,
 points TEXT, games TEXT, sessions TEXT, players TEXT, meta TEXT, final INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS snapshots(
 id SERIAL PRIMARY KEY, window_id TEXT, ts DOUBLE PRECISION,
 entrants INTEGER, points TEXT, games TEXT, top TEXT);
CREATE INDEX IF NOT EXISTS snap_win ON snapshots(window_id, ts);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS names(account_id TEXT PRIMARY KEY, name TEXT);
"""
_ready = False
_cache = {"t": 0, "rows": None}
_lock = threading.Lock()


def db():
    global _ready
    c = psycopg.connect(URL, autocommit=True, prepare_threshold=None)
    if not _ready:
        c.execute(SCHEMA)
        _ready = True
    return c


def _j(s, default):
    return json.loads(s) if s else default


def _row(r, full=True):
    d = {"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "begin": r[4],
         "end": r[5], "entrants": r[6], "final": r[7], "meta": _j(r[8], {})}
    if full:
        d.update(points=_j(r[9], []), games=_j(r[10], []), sessions=_j(r[11], []),
                 players=_j(r[12], []))
    return d


COLS = "window_id,event_id,family,region,begin_ts,end_ts,entrants,final,meta"
FULL = COLS + ",points,games,sessions,players"


def upsert_window(w):
    with db() as c:
        c.execute("""INSERT INTO windows(window_id,event_id,family,region,begin_ts,end_ts,meta)
                     VALUES(%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT(window_id) DO UPDATE SET
                       begin_ts=excluded.begin_ts, end_ts=excluded.end_ts, meta=excluded.meta""",
                  (w["window_id"], w["event_id"], w["family"], w["region"], w["begin"], w["end"],
                   json.dumps(w.get("meta") or {})))


def save_final(window_id, lb):
    with db() as c:
        c.execute("UPDATE windows SET entrants=%s,points=%s,games=%s,sessions=%s,players=%s,final=1"
                  " WHERE window_id=%s",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(lb.get("sessions", [])), json.dumps(lb.get("players", [])), window_id))
    _cache["rows"] = None


def save_snapshot(window_id, lb, ts=None):
    top = [{"rank": i + 1, "players": lb["players"][i], "points": lb["points"][i],
            "games": lb["games"][i]} for i in range(min(60, len(lb["points"])))
           ] if lb.get("players") else []
    with db() as c:
        c.execute("INSERT INTO snapshots(window_id,ts,entrants,points,games,top) VALUES(%s,%s,%s,%s,%s,%s)",
                  (window_id, ts or time.time(), lb["entrants"], json.dumps(lb["points"]),
                   json.dumps(lb["games"]), json.dumps(top)))


def window_list():
    """Windows without the big columns."""
    with db() as c:
        return [_row(r, False) for r in c.execute(
            f"SELECT {COLS} FROM windows ORDER BY end_ts DESC").fetchall()]


def windows(final=None):
    if final is True and _cache["rows"] is not None and time.time() - _cache["t"] < 300:
        return _cache["rows"]
    q = f"SELECT {FULL} FROM windows" + ("" if final is None else f" WHERE final={int(final)}")
    with db() as c:
        rows = [_row(r) for r in c.execute(q + " ORDER BY end_ts DESC").fetchall()]
    if final is True:
        _cache.update(t=time.time(), rows=rows)
    return rows


def get_window(window_id):
    with db() as c:
        r = c.execute(f"SELECT {FULL} FROM windows WHERE window_id=%s", (window_id,)).fetchone()
    return _row(r) if r else None


def snapshots(window_id, last=None, light=False):
    q = "SELECT ts,entrants,points,games,top FROM snapshots WHERE window_id=%s ORDER BY ts" + (
        " DESC LIMIT %s" if last else "")
    with db() as c:
        rows = c.execute(q, (window_id, last) if last else (window_id,)).fetchall()
    out = [{"ts": r[0], "entrants": r[1], "points": json.loads(r[2]), "games": json.loads(r[3]),
            "top": json.loads(r[4]) if r[4] else []} for r in rows]
    return out[::-1] if last else out


def snapshot_stats(window_id):
    with db() as c:
        r = c.execute("SELECT count(*),min(ts),max(ts) FROM snapshots WHERE window_id=%s",
                      (window_id,)).fetchone()
    return {"count": r[0], "first": r[1], "last": r[2]}


def kv_get(k):
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=%s", (k,)).fetchone()
    return json.loads(r[0]) if r else None


def kv_set(k, v):
    with db() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(%s,%s) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (k, json.dumps(v)))


@contextlib.contextmanager
def locked(name="auth"):
    """Cross-process lock (transaction-level advisory lock; works behind poolers)."""
    c = psycopg.connect(URL, prepare_threshold=None)  # not autocommit: one transaction
    try:
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))
        yield
        c.commit()
    finally:
        c.close()


def names_get(ids):
    if not ids:
        return {}
    with db() as c:
        return dict(c.execute("SELECT account_id,name FROM names WHERE account_id = ANY(%s)",
                              (list(ids),)).fetchall())


def names_set(d):
    with db() as c:
        for k, v in d.items():
            c.execute("INSERT INTO names VALUES(%s,%s) ON CONFLICT(account_id) DO UPDATE SET name=excluded.name",
                      (k, v))
