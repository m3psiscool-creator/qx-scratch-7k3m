"""Postgres storage (Neon via Vercel). Same functions as storage.py (sqlite, used locally)."""
import contextlib
import json
import os
import threading
import time

import psycopg

URL = (os.environ.get("FNGA_DB_URL") or os.environ.get("NEON2_POSTGRES_URL")
       or os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows(
 window_id TEXT PRIMARY KEY, event_id TEXT, family TEXT, region TEXT,
 begin_ts DOUBLE PRECISION, end_ts DOUBLE PRECISION, entrants INTEGER,
 points TEXT, games TEXT, sessions TEXT, players TEXT, meta TEXT, final INTEGER DEFAULT 0,
 category TEXT, prow TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
 id SERIAL PRIMARY KEY, window_id TEXT, ts DOUBLE PRECISION,
 entrants INTEGER, points TEXT, games TEXT, top TEXT);
CREATE INDEX IF NOT EXISTS snap_win ON snapshots(window_id, ts);
CREATE TABLE IF NOT EXISTS series(
 window_id TEXT, ts DOUBLE PRECISION, d TEXT);
CREATE INDEX IF NOT EXISTS series_win ON series(window_id, ts);
CREATE TABLE IF NOT EXISTS predictions(
 window_id TEXT, ts DOUBLE PRECISION, rank INTEGER, low INTEGER, likely INTEGER, safe INTEGER,
 progress DOUBLE PRECISION, cur DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS pred_win ON predictions(window_id, rank, ts);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS names(account_id TEXT PRIMARY KEY, name TEXT);
"""
ALTERS = ["ALTER TABLE windows ADD COLUMN IF NOT EXISTS deep TEXT",
          "ALTER TABLE windows ADD COLUMN IF NOT EXISTS category TEXT",
          "ALTER TABLE windows ADD COLUMN IF NOT EXISTS prow TEXT",
          "ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS deep TEXT"]
_ready = False
_cache = {"t": 0, "rows": None}
_lock = threading.Lock()


def db():
    global _ready
    c = psycopg.connect(URL, autocommit=True, prepare_threshold=None)
    if not _ready:
        c.execute(SCHEMA)
        for a in ALTERS:
            c.execute(a)
        _ready = True
    return c


def _j(s, default):
    return json.loads(s) if s else default


def _row(r, full=True):
    d = {"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "begin": r[4],
         "end": r[5], "entrants": r[6], "final": r[7], "meta": _j(r[8], {})}
    if full:
        d.update(points=_j(r[9], []), games=_j(r[10], []), sessions=_j(r[11], []),
                 players=_j(r[12], []), deep=_j(r[13], {}))
    return d


COLS = "window_id,event_id,family,region,begin_ts,end_ts,entrants,final,meta"
FULL = COLS + ",points,games,sessions,players,deep"


def upsert_window(w):
    with db() as c:
        from . import classify
        c.execute("""INSERT INTO windows(window_id,event_id,family,region,begin_ts,end_ts,meta,category)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT(window_id) DO UPDATE SET
                       begin_ts=excluded.begin_ts, end_ts=excluded.end_ts, meta=excluded.meta,
                       category=excluded.category""",
                  (w["window_id"], w["event_id"], w["family"], w["region"], w["begin"], w["end"],
                   json.dumps(w.get("meta") or {}), classify.of(w)))


def _player_rows(lb):
    """[account, rank, points, games, wins, elims, avg placement] for each entry (compact player history)."""
    rows = []
    for rank, accts in enumerate(lb.get("players") or [], start=1):
        sess = lb["sessions"][rank - 1] if rank <= len(lb.get("sessions") or []) else []
        plc = [g[0] for g in sess if g and g[0]]
        for a in accts:
            rows.append([a, rank, lb["points"][rank - 1], lb["games"][rank - 1],
                         sum(1 for g in sess if len(g) > 2 and g[2]), sum(g[1] for g in sess if len(g) > 1),
                         round(sum(plc) / len(plc), 1) if plc else None])
    return rows


def save_final(window_id, lb):
    with db() as c:
        c.execute("UPDATE windows SET entrants=%s,points=%s,games=%s,sessions=%s,players=%s,deep=%s,prow=%s,final=1"
                  " WHERE window_id=%s",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(lb.get("sessions", [])), json.dumps(lb.get("players", [])),
                   json.dumps(lb.get("deep", {})), json.dumps(_player_rows(lb)), window_id))


def _series_point(lb):
    from . import config
    d = {str(r): lb["points"][r - 1] for r in config.SERIES_RANKS if r <= len(lb["points"])}
    for r, v in (lb.get("deep") or {}).items():
        d[r] = v["points"]
    return d


def save_snapshot(window_id, lb, ts=None):
    ts = ts or time.time()
    top = [{"rank": i + 1, "players": lb["players"][i], "points": lb["points"][i],
            "games": lb["games"][i]} for i in range(min(60, len(lb["points"])))
           ] if lb.get("players") else []
    with db() as c:
        c.execute("INSERT INTO snapshots(window_id,ts,entrants,points,games,top,deep) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  (window_id, ts, lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(top), json.dumps(lb.get("deep", {}))))
        c.execute("INSERT INTO series(window_id,ts,d) VALUES(%s,%s,%s)",
                  (window_id, ts, json.dumps({"p": _series_point(lb), "e": lb["entrants"]})))


def set_deep(window_id, deep):
    with db() as c:
        c.execute("UPDATE windows SET deep=%s WHERE window_id=%s", (json.dumps(deep), window_id))


def series(window_id):
    """Compact points-by-rank history of a window: [{ts, p:{rank:points}, e: entrants}]."""
    with db() as c:
        rows = c.execute("SELECT ts,d FROM series WHERE window_id=%s ORDER BY ts", (window_id,)).fetchall()
    return [{"ts": r[0], **json.loads(r[1])} for r in rows]


def prune(days=3):
    """Drop full boards of snapshots for windows finished more than `days` days ago (series stays)."""
    cut = time.time() - days * 86400
    with db() as c:
        r = c.execute("DELETE FROM snapshots WHERE window_id IN "
                      "(SELECT window_id FROM windows WHERE final=1 AND end_ts<%s)", (cut,))
        return r.rowcount


def deep_missing(limit=1):
    with db() as c:
        rows = c.execute("SELECT window_id,event_id FROM windows WHERE final=1 AND "
                         "(deep IS NULL OR deep='' OR deep='{}') ORDER BY end_ts DESC LIMIT %s",
                         (limit,)).fetchall()
    return [{"window_id": r[0], "event_id": r[1]} for r in rows]


def window_list():
    """Windows without the big columns."""
    with db() as c:
        return [_row(r, False) for r in c.execute(
            f"SELECT {COLS} FROM windows ORDER BY end_ts DESC").fetchall()]


_wcache = {}


def _row_light(r):
    d = {"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "begin": r[4],
         "end": r[5], "entrants": r[6], "final": r[7], "meta": _j(r[8], {})}
    d.update(points=_j(r[9], []), games=_j(r[10], []), deep=_j(r[11], {}))
    return d


def windows(final=None, category=None, light=False):
    """Windows. `category` limits the heavy columns to one event class; `light` skips sessions and
    players. Finished windows are cached for 10 minutes (they only ever get added)."""
    key = (final, category, light)
    hit = _wcache.get(key)
    if final is True and hit and time.time() - hit[0] < 600:
        return hit[1]
    cols = COLS + (",points,games,deep" if light else ",points,games,sessions,players,deep")
    where = []
    if final is not None:
        where.append(f"final={int(final)}")
    if category:
        where.append("category=%s")
    q = f"SELECT {cols} FROM windows" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY end_ts DESC"
    with db() as c:
        rows = c.execute(q, (category,) if category else ()).fetchall()
    out = [(_row_light if light else _row)(r) for r in rows]
    if final is True:
        _wcache[key] = (time.time(), out)
    return out


def player_rows():
    """Compact per-event player results (for the player pages) without the heavy columns."""
    with db() as c:
        rows = c.execute("SELECT window_id,event_id,family,region,end_ts,entrants,meta,prow FROM windows "
                         "WHERE final=1 AND prow IS NOT NULL ORDER BY end_ts DESC").fetchall()
    return [{"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "end": r[4],
             "entrants": r[5], "meta": _j(r[6], {}), "prow": _j(r[7], [])} for r in rows]


def get_window(window_id):
    with db() as c:
        r = c.execute(f"SELECT {FULL} FROM windows WHERE window_id=%s", (window_id,)).fetchone()
    return _row(r) if r else None


def snapshots(window_id, last=None, light=False):
    q = "SELECT ts,entrants,points,games,top,deep FROM snapshots WHERE window_id=%s ORDER BY ts" + (
        " DESC LIMIT %s" if last else "")
    with db() as c:
        rows = c.execute(q, (window_id, last) if last else (window_id,)).fetchall()
    out = [{"ts": r[0], "entrants": r[1], "points": json.loads(r[2]), "games": json.loads(r[3]),
            "top": json.loads(r[4]) if r[4] else [], "deep": json.loads(r[5]) if r[5] else {}}
           for r in rows]
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


def names_search(q, limit=20):
    with db() as c:
        return c.execute("SELECT account_id,name FROM names WHERE name ILIKE %s ORDER BY length(name) LIMIT %s",
                         ("%" + q + "%", limit)).fetchall()


def add_predictions(rows):
    """rows: (window_id, ts, rank, low, likely, safe, progress, current)."""
    with db() as c:
        for r in rows:
            c.execute("INSERT INTO predictions VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", r)


def predictions_for(window_id):
    with db() as c:
        return [{"ts": r[0], "rank": r[1], "low": r[2], "likely": r[3], "safe": r[4], "progress": r[5],
                 "current": r[6]} for r in c.execute(
            "SELECT ts,rank,low,likely,safe,progress,cur FROM predictions WHERE window_id=%s ORDER BY ts",
            (window_id,)).fetchall()]


def predictions_all():
    with db() as c:
        return c.execute("SELECT window_id,ts,rank,low,likely,safe,progress FROM predictions").fetchall()


def counts():
    with db() as c:
        return {"windows": c.execute("SELECT count(*) FROM windows").fetchone()[0],
                "final": c.execute("SELECT count(*) FROM windows WHERE final=1").fetchone()[0],
                "snapshots": c.execute("SELECT count(*) FROM snapshots").fetchone()[0],
                "series": c.execute("SELECT count(*) FROM series").fetchone()[0],
                "predictions": c.execute("SELECT count(*) FROM predictions").fetchone()[0],
                "names": c.execute("SELECT count(*) FROM names").fetchone()[0],
                "deep_missing": c.execute("SELECT count(*) FROM windows WHERE final=1 AND (deep IS NULL OR deep='' OR deep='{}')").fetchone()[0],
                "db_mb": round(c.execute("SELECT pg_database_size(current_database())").fetchone()[0] / 1e6, 1)}
