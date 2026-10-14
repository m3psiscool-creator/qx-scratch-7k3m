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
 category TEXT, prow TEXT, timed TEXT);
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
          "ALTER TABLE windows ADD COLUMN IF NOT EXISTS timed TEXT",
          "ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS deep TEXT"]
_ready = False
_lock = threading.Lock()
_EG = {"bytes": 0, "by": {}}   # bytes read out of the database by this process (approximate), by query


def _count(rows, sql=""):
    n = 0
    for r in rows:
        for v in r:
            n += len(v) if isinstance(v, str) else (8 if v is not None else 0)
    _EG["bytes"] += n
    tag = " ".join(str(sql).split())[:70]
    _EG["by"][tag] = _EG["by"].get(tag, 0) + n


class _CC(psycopg.Cursor):
    def execute(self, query, params=None, **kw):
        self._sql = query if isinstance(query, str) else ""
        return super().execute(query, params, **kw)

    def fetchall(self):
        rows = super().fetchall()
        _count(rows, getattr(self, "_sql", ""))
        return rows

    def fetchone(self):
        r = super().fetchone()
        if r:
            _count([r], getattr(self, "_sql", ""))
        return r


def db():
    global _ready
    c = psycopg.connect(URL, autocommit=True, prepare_threshold=None, cursor_factory=_CC)
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
    _WL["rows"] = None   # the event list is re-read (once) after a sync


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


def timed_from(sessions, rule_list, begin):
    """Per player a flat list [seconds since window start, points of that game, ...]: the only part of
    the game history the live simulation needs, about a third of the size of the raw sessions."""
    from . import rules
    out = []
    for sess in sessions:
        row = []
        for g in sess:
            if len(g) > 3 and g[3]:
                row += [int(g[3] - begin), rules.game_points(rule_list, rules.session_stats(g))]
        out.append(row)
    return out


def save_final(window_id, lb):
    with db() as c:
        r = c.execute("SELECT begin_ts, meta FROM windows WHERE window_id=%s", (window_id,)).fetchone()
        rule_list = (_j(r[1], {}) if r else {}).get("rules") or []
        timed = timed_from(lb.get("sessions", []), rule_list, r[0]) if r else []
        c.execute("UPDATE windows SET entrants=%s,points=%s,games=%s,sessions=%s,players=%s,deep=%s,prow=%s,timed=%s,final=1"
                  " WHERE window_id=%s",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(lb.get("sessions", [])), json.dumps(lb.get("players", [])),
                   json.dumps(lb.get("deep", {})), json.dumps(_player_rows(lb)), json.dumps(timed, separators=(",", ":")),
                   window_id))
    _after_final(window_id)


def timed_missing(limit=1):
    with db() as c:
        return [r[0] for r in c.execute("SELECT window_id FROM windows WHERE final=1 AND "
                                        "(timed IS NULL OR timed='') ORDER BY end_ts DESC LIMIT %s", (limit,)).fetchall()]


def fill_timed(window_id):
    """One-off: compute the compact timed points for a window saved before that column existed."""
    with db() as c:
        r = c.execute("SELECT begin_ts, meta, sessions FROM windows WHERE window_id=%s", (window_id,)).fetchone()
        if not r:
            return
        timed = timed_from(_j(r[2], []), (_j(r[1], {})).get("rules") or [], r[0])
        c.execute("UPDATE windows SET timed=%s WHERE window_id=%s",
                  (json.dumps(timed, separators=(",", ":")), window_id))
    _HEAVY.pop(window_id, None)


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


def live_windows(now, after):
    """Unfinished windows that have started and are not yet past end + `after` (tiny query)."""
    with db() as c:
        rows = c.execute(f"SELECT window_id,event_id,family,region,begin_ts,end_ts,entrants,final,{SLIM} FROM windows "
                         "WHERE final=0 AND begin_ts<=%s AND end_ts>=%s", (now, now - after)).fetchall()
    return [_row(r, False) for r in rows]


def ended_unfinished(now, after, limit=8):
    """Unfinished windows that ended more than `after` seconds ago, newest first (backfill queue)."""
    with db() as c:
        rows = c.execute(f"SELECT window_id,event_id,family,region,begin_ts,end_ts,entrants,final,{SLIM} FROM windows "
                         "WHERE final=0 AND end_ts<%s AND NOT EXISTS (SELECT 1 FROM kv WHERE kv.k = 'empty:' || windows.window_id) "
                         "ORDER BY end_ts DESC LIMIT %s", (now - after, limit)).fetchall()
    return [_row(r, False) for r in rows]


_WL = {"t": 0, "rows": None}
LIST_TTL = 600
# the event list without the heavy parts of meta (scoring rules and reward tiers)
SLIM = ("(jsonb_set(COALESCE(meta,'{}')::jsonb - 'rules', '{rewards}', "
        "COALESCE(COALESCE(meta,'{}')::jsonb->'rewards','{}'::jsonb) - 'tiers'))::text")


def window_list():
    """Every window, slim rows, cached 5 minutes (read by every collector pass and page)."""
    if _WL["rows"] is not None and time.time() - _WL["t"] < LIST_TTL:
        return _WL["rows"]
    with db() as c:
        rows = c.execute(f"SELECT window_id,event_id,family,region,begin_ts,end_ts,entrants,final,{SLIM} "
                         "FROM windows ORDER BY end_ts DESC").fetchall()
    _WL.update(t=time.time(), rows=[_row(r, False) for r in rows])
    return _WL["rows"]


def _row_light(r):
    d = {"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "begin": r[4],
         "end": r[5], "entrants": r[6], "final": r[7], "meta": _j(r[8], {})}
    d.update(points=_j(r[9], []), games=_j(r[10], []), deep=_j(r[11], {}))
    return d


_LIGHT = {}          # category ("" = all) -> (time, finished windows without sessions/players)
_HEAVY = {}          # window_id -> {"sessions", "players"} of the most recent finished windows
_GW = {}             # window_id -> finished window (immutable once final)
LIGHT_TTL = 3600
HEAVY_RECENT = 8    # the model only replays the newest events of a class game by game
_PR = {"t": 0, "rows": None}


def _light_rows(category, limit=None):
    key = (category or "", limit)
    hit = _LIGHT.get(key)
    if hit and time.time() - hit[0] < LIGHT_TTL:
        return hit[1]
    q = f"SELECT {COLS},points,games,deep FROM windows WHERE final=1" + (" AND category=%s" if category else "") + \
        " ORDER BY end_ts DESC" + (f" LIMIT {int(limit)}" if limit else "")
    with db() as c:
        rows = [_row_light(r) for r in c.execute(q, (category,) if category else ()).fetchall()]
    _LIGHT[key] = (time.time(), rows)
    return rows


def _heavy(ids):
    """The compact timed points of these windows (a third of the raw sessions)."""
    need = [i for i in ids if i not in _HEAVY]
    if need:
        with db() as c:
            for wid, timed in c.execute("SELECT window_id,timed FROM windows WHERE window_id = ANY(%s)",
                                        (need,)).fetchall():
                _HEAVY[wid] = {"timed": _j(timed, None)}
        while len(_HEAVY) > 40:
            _HEAVY.pop(next(iter(_HEAVY)))
    return {i: _HEAVY.get(i) for i in ids}


_SESS = {}


def attach_sessions(ws):
    """Load the raw per-game history (placements, eliminations) for these windows. Only needed when a
    class has no same-format history and old games must be re-scored under new rules."""
    need = [w["window_id"] for w in ws if w["window_id"] not in _SESS and not w.get("sessions")]
    if need:
        with db() as c:
            for wid, sess, pl in c.execute("SELECT window_id,sessions,players FROM windows WHERE window_id = ANY(%s)",
                                           (need,)).fetchall():
                _SESS[wid] = {"sessions": _j(sess, []), "players": _j(pl, [])}
        while len(_SESS) > 12:
            _SESS.pop(next(iter(_SESS)))
    for w in ws:
        if w["window_id"] in _SESS:
            w.update(_SESS[w["window_id"]])
    return ws


def _after_final(window_id):
    """A window just finished: update this process's caches in place instead of re-reading them."""
    for w in _WL["rows"] or []:
        if w["window_id"] == window_id:
            w["final"] = 1
    _PR["rows"] = None
    if not _LIGHT:
        return
    with db() as c:
        r = c.execute(f"SELECT {COLS},points,games,deep,category FROM windows WHERE window_id=%s", (window_id,)).fetchone()
    if not r:
        return
    light, cat = _row_light(r), r[12]
    for key, (ts, rows) in list(_LIGHT.items()):
        if key[0] in ("", cat):
            rows = [w for w in rows if w["window_id"] != window_id] + [light]
            rows = sorted(rows, key=lambda w: -w["end"])
            _LIGHT[key] = (ts, rows[:key[1]] if key[1] else rows)
    _GW.pop(window_id, None)


def windows(final=None, category=None, light=False):
    """Finished windows (final=True): slim rows for all of them, plus sessions/players for only the
    newest HEAVY_RECENT. Cached, and updated in place when a window finishes."""
    if final is True:
        if light:
            return _light_rows(category)
        rows = _light_rows(category, 30 if category else 60)
        heavy = _heavy([w["window_id"] for w in rows[:HEAVY_RECENT]])
        return [({**w, **heavy[w["window_id"]], "sessions": [], "players": []}
                 if i < HEAVY_RECENT and heavy.get(w["window_id"]) and heavy[w["window_id"]].get("timed") is not None
                 else {**w, "sessions": [], "players": [], "timed": None}) for i, w in enumerate(rows)]
    where = [] if final is None else [f"final={int(final)}"]
    if category:
        where.append("category=%s")
    q = f"SELECT {FULL} FROM windows" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY end_ts DESC"
    with db() as c:
        return [_row(r) for r in c.execute(q, (category,) if category else ()).fetchall()]


def player_rows():
    """Compact per-event player results (for the player pages), cached for an hour."""
    if _PR["rows"] is not None and time.time() - _PR["t"] < LIGHT_TTL:
        return _PR["rows"]
    with db() as c:
        rows = c.execute("SELECT window_id,event_id,family,region,end_ts,entrants,meta,prow FROM windows "
                         "WHERE final=1 AND prow IS NOT NULL ORDER BY end_ts DESC").fetchall()
    out = [{"window_id": r[0], "event_id": r[1], "family": r[2], "region": r[3], "end": r[4],
            "entrants": r[5], "meta": _j(r[6], {}), "prow": _j(r[7], [])} for r in rows]
    _PR.update(t=time.time(), rows=out)
    return out


def get_window(window_id):
    hit = _GW.get(window_id)
    if hit:
        return hit
    with db() as c:
        r = c.execute(f"SELECT {FULL} FROM windows WHERE window_id=%s", (window_id,)).fetchone()
    w = _row(r) if r else None
    if w and w["final"]:
        if len(_GW) > 20:
            _GW.pop(next(iter(_GW)))
        _GW[window_id] = w
    return w


_SNAP = {}


def snapshots(window_id, last=None, light=False):
    if last == 1:   # the newest board is read many times per pass: share it for 20 seconds
        hit = _SNAP.get(window_id)
        if hit and time.time() - hit[0] < 20:
            return hit[1]
        out = _snapshots(window_id, last)
        _SNAP[window_id] = (time.time(), out)
        return out
    return _snapshots(window_id, last)


def _snapshots(window_id, last=None):
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


def egress_flush():
    """Add this process's bytes-read counter to this month's total (kept in the database)."""
    n = _EG["bytes"]
    if n < 300_000:
        return
    by = sorted(_EG["by"].items(), key=lambda x: -x[1])[:6]
    _EG["bytes"] = 0
    _EG["by"] = {}
    key = "egress:" + time.strftime("%Y-%m")
    kv_set(key, (kv_get(key) or 0) + n)
    # keep the last few heavy-hitters so they can be shown on the Status page
    log = kv_get("egress_by") or []
    kv_set("egress_by", ([{"at": time.time(), "mb": round(n / 1e6, 2), "by": [[k, round(v / 1e6, 2)] for k, v in by]}] + log)[:12])


def egress_month():
    return kv_get("egress:" + time.strftime("%Y-%m")) or 0


def recent_top_accounts(windows=20, per=120):
    """Accounts of the best finishers of the newest events (for name lookups), read slice-by-slice in SQL."""
    with db() as c:
        rows = c.execute("SELECT jsonb_path_query_array(prow::jsonb, %s)::text FROM windows "
                         "WHERE final=1 AND prow IS NOT NULL ORDER BY end_ts DESC LIMIT %s",
                         (f"$[0 to {int(per)}]", windows)).fetchall()
    return [x[0] for r in rows for x in json.loads(r[0])]


def egress_bytes():
    return _EG["bytes"]


_PR_ROWS = """
  SELECT w.window_id, w.entrants, w.category, e.value AS r
  FROM windows w, LATERAL jsonb_array_elements(w.prow::jsonb) AS e(value)
  WHERE w.final = 1 AND w.prow IS NOT NULL"""


def top_players_sql(limit=50, category=None, min_events=3):
    """Strongest players (average finishing share of the field). Computed inside the database,
    only the answer comes back."""
    q = f"""WITH rows AS ({_PR_ROWS}{" AND w.category = %s" if category else ""})
            SELECT r->>0, count(*), avg((r->>1)::float * 100 / LEAST(COALESCE(entrants, 10000), 10000)),
                   min((r->>1)::int)
            FROM rows GROUP BY 1 HAVING count(*) >= %s ORDER BY 3 LIMIT %s"""
    args = ((category,) if category else ()) + (min_events, limit)
    with db() as c:
        return [{"id": r[0], "events": r[1], "avg_top_pct": round(r[2], 2), "best": r[3]}
                for r in c.execute(q, args).fetchall()]


def player_events(account_id):
    """Every top-1000 finish of one player, read straight out of the stored player rows."""
    with db() as c:
        rows = c.execute(
            """SELECT w.window_id, w.event_id, w.family, w.region, w.end_ts, w.entrants, w.category,
                      jsonb_path_query(w.prow::jsonb, 'strict $[*] ? (@[0] == $a)', jsonb_build_object('a', %s::text))::text
               FROM windows w
               WHERE w.final = 1 AND w.prow IS NOT NULL
                 AND w.prow::jsonb @> jsonb_build_array(jsonb_build_array(%s::text))
               ORDER BY w.end_ts DESC""", (account_id, account_id)).fetchall()
    out = []
    for wid, eid, fam, reg, end, ent, cat, r in rows:
        a, rank, pts, games, wins, elims, avg = json.loads(r)
        out.append({"window_id": wid, "event_id": eid, "family": fam, "region": reg, "end": end,
                    "category": cat, "rank": rank, "points": pts, "games": games, "wins": wins,
                    "elims": elims, "avg_place": avg,
                    "pct": round(100 * rank / min(ent or 10000, 10000), 2)})
    return out


def player_event_counts(ids):
    if not ids:
        return {}
    with db() as c:
        rows = c.execute(f"""WITH rows AS ({_PR_ROWS}) SELECT r->>0, count(*) FROM rows
                             WHERE r->>0 = ANY(%s) GROUP BY 1""", (list(ids),)).fetchall()
    return dict(rows)


def player_form_sql(ids, category):
    """Past events, best and median finish of these players within one event class."""
    if not ids:
        return {}
    with db() as c:
        rows = c.execute(f"""WITH rows AS ({_PR_ROWS} AND w.category = %s)
                             SELECT r->>0, count(*), min((r->>1)::int),
                                    percentile_cont(0.5) WITHIN GROUP (ORDER BY (r->>1)::int)
                             FROM rows WHERE r->>0 = ANY(%s) GROUP BY 1""", (category, list(ids))).fetchall()
    return {a: {"events": n, "best": b, "median": m} for a, n, b, m in rows}


def status_counts():
    now = time.time()
    with db() as c:
        r = c.execute("""SELECT count(*) FILTER (WHERE final = 1),
                                count(*) FILTER (WHERE final = 0 AND begin_ts <= %s AND end_ts >= %s),
                                count(*) FILTER (WHERE final = 0 AND begin_ts > %s),
                                count(*) FILTER (WHERE final = 0 AND end_ts < %s) FROM windows""",
                      (now, now, now, now)).fetchone()
    return {"finished": r[0], "live": r[1], "upcoming": r[2], "not collected yet": r[3]}
