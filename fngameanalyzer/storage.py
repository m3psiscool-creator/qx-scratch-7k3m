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
 entrants INTEGER, points TEXT, games TEXT, top TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS series(window_id TEXT, ts REAL, d TEXT);
CREATE TABLE IF NOT EXISTS names(account_id TEXT PRIMARY KEY, name TEXT);
"""


def db():
    c = sqlite3.connect(config.DB_FILE)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for table, col in (("windows", "meta"), ("windows", "sessions"), ("windows", "players"),
                       ("snapshots", "top"), ("windows", "deep"), ("snapshots", "deep")):  # added later; migrate old databases
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
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
        c.execute("UPDATE windows SET entrants=?,points=?,games=?,sessions=?,players=?,deep=?,final=1"
                  " WHERE window_id=?",
                  (lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(lb.get("sessions", [])), json.dumps(lb.get("players", [])),
                   json.dumps(lb.get("deep", {})), window_id))


def _series_point(lb):
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
        c.execute("INSERT INTO snapshots(window_id,ts,entrants,points,games,top,deep) VALUES(?,?,?,?,?,?,?)",
                  (window_id, ts, lb["entrants"], json.dumps(lb["points"]), json.dumps(lb["games"]),
                   json.dumps(top), json.dumps(lb.get("deep", {}))))
        c.execute("INSERT INTO series VALUES(?,?,?)",
                  (window_id, ts, json.dumps({"p": _series_point(lb), "e": lb["entrants"]})))


def set_deep(window_id, deep):
    with db() as c:
        c.execute("UPDATE windows SET deep=? WHERE window_id=?", (json.dumps(deep), window_id))


def series(window_id):
    with db() as c:
        rows = c.execute("SELECT ts,d FROM series WHERE window_id=? ORDER BY ts", (window_id,)).fetchall()
    return [{"ts": r[0], **json.loads(r[1])} for r in rows]


def prune(days=3):
    return 0   # local database: keep everything


def deep_missing(limit=1):
    with db() as c:
        rows = c.execute("SELECT window_id,event_id FROM windows WHERE final=1 AND "
                         "(deep IS NULL OR deep='' OR deep='{}') ORDER BY end DESC LIMIT ?", (limit,))
        return [{"window_id": r[0], "event_id": r[1]} for r in rows]


def _w(r):
    d = dict(r)
    d["points"] = json.loads(d["points"]) if d["points"] else []
    d["games"] = json.loads(d["games"]) if d["games"] else []
    d["sessions"] = json.loads(d["sessions"]) if d.get("sessions") else []
    d["players"] = json.loads(d["players"]) if d.get("players") else []
    d["deep"] = json.loads(d["deep"]) if d.get("deep") else {}
    d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
    return d


def windows(final=None, category=None, light=False):
    q = "SELECT * FROM windows" + ("" if final is None else f" WHERE final={int(final)}")
    with db() as c:
        out = [_w(r) for r in c.execute(q + " ORDER BY end DESC")]
    if category:
        from . import classify
        out = [w for w in out if classify.of(w) == category]
    return out


def get_window(window_id):
    with db() as c:
        r = c.execute("SELECT * FROM windows WHERE window_id=?", (window_id,)).fetchone()
    return _w(r) if r else None


def snapshots(window_id, last=None, light=False):
    q = "SELECT * FROM snapshots WHERE window_id=? ORDER BY ts" + (" DESC LIMIT ?" if last else "")
    with db() as c:
        rows = c.execute(q, (window_id, last) if last else (window_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["points"] = json.loads(d["points"])
            d["games"] = json.loads(d["games"])
            d["top"] = json.loads(d["top"]) if d.get("top") else []
            d["deep"] = json.loads(d["deep"]) if d.get("deep") else {}
            out.append(d)
    return out[::-1] if last else out


def snapshot_stats(window_id):
    with db() as c:
        r = c.execute("SELECT count(*),min(ts),max(ts) FROM snapshots WHERE window_id=?",
                      (window_id,)).fetchone()
    return {"count": r[0], "first": r[1], "last": r[2]}


def window_list():
    """Windows without the big columns."""
    return [{k: v for k, v in w.items() if k not in ("points", "games", "sessions", "players")}
            for w in windows()]


def kv_get(k):
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else None


def kv_set(k, v):
    with db() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (k, json.dumps(v)))


import contextlib  # noqa: E402


@contextlib.contextmanager
def locked(name="auth"):
    yield  # single local process: no lock needed


def names_get(ids):
    with db() as c:
        return {r[0]: r[1] for r in c.execute("SELECT account_id,name FROM names") if r[0] in set(ids)}


def names_set(d):
    with db() as c:
        for k, v in d.items():
            c.execute("INSERT INTO names VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET name=excluded.name",
                      (k, v))


def names_search(q, limit=20):
    with db() as c:
        return c.execute("SELECT account_id,name FROM names WHERE name LIKE ? LIMIT ?", ("%" + q + "%", limit)).fetchall()


def add_predictions(rows):
    pass


def predictions_for(window_id):
    return []


def predictions_all():
    return []


def counts():
    return {"windows": len(windows())}


import os as _os  # noqa: E402



def player_rows():
    out = []
    for w in windows(final=True):
        rows = []
        for rank, accts in enumerate(w.get("players") or [], start=1):
            sess = w["sessions"][rank - 1] if rank <= len(w["sessions"]) else []
            plc = [g[0] for g in sess if g and g[0]]
            for a in accts:
                rows.append([a, rank, w["points"][rank - 1], w["games"][rank - 1],
                             sum(1 for g in sess if len(g) > 2 and g[2]), sum(g[1] for g in sess if len(g) > 1),
                             round(sum(plc) / len(plc), 1) if plc else None])
        out.append({"window_id": w["window_id"], "event_id": w["event_id"], "family": w["family"],
                    "region": w["region"], "end": w["end"], "entrants": w.get("entrants"),
                    "meta": w["meta"], "prow": rows})
    return out


def egress_flush():
    pass


def egress_month():
    return 0




def live_windows(now, after):
    return [w for w in window_list() if not w["final"] and w["begin"] <= now and w["end"] >= now - after]


def ended_unfinished(now, after, limit=8):
    out = [w for w in window_list() if not w["final"] and w["end"] < now - after]
    return sorted(out, key=lambda w: -w["end"])[:limit]


def attach_sessions(ws):
    return ws


def timed_missing(limit=1):
    return []


def fill_timed(window_id):
    pass


def recent_top_accounts(windows=20, per=120):
    return []


def egress_bytes():
    return 0


def _flat_player_rows():
    for w in player_rows():
        ent = min(w.get("entrants") or 10000, 10000)
        from . import classify
        for a, rank, pts, games, wins, elims, avg in w["prow"]:
            yield w, classify.of(w), a, rank, pts, games, wins, elims, avg, round(100 * rank / ent, 2)


def top_players_sql(limit=50, category=None, min_events=3):
    import statistics
    by = {}
    for w, cat, a, rank, *_rest, pct in _flat_player_rows():
        if category in (None, "", cat):
            by.setdefault(a, []).append((pct, rank))
    out = [{"id": a, "events": len(v), "avg_top_pct": round(statistics.mean(p for p, _ in v), 2),
            "best": min(r for _, r in v)} for a, v in by.items() if len(v) >= min_events]
    return sorted(out, key=lambda x: x["avg_top_pct"])[:limit]


def player_events(account_id):
    out = []
    for w, cat, a, rank, pts, games, wins, elims, avg, pct in _flat_player_rows():
        if a == account_id:
            out.append({"window_id": w["window_id"], "event_id": w["event_id"], "family": w["family"],
                        "region": w["region"], "end": w["end"], "category": cat, "rank": rank, "points": pts,
                        "games": games, "wins": wins, "elims": elims, "avg_place": avg, "pct": pct})
    return sorted(out, key=lambda x: -x["end"])


def player_event_counts(ids):
    ids, out = set(ids), {}
    for w, cat, a, *_ in _flat_player_rows():
        if a in ids:
            out[a] = out.get(a, 0) + 1
    return out


def player_form_sql(ids, category):
    import statistics
    ids, by = set(ids), {}
    for w, cat, a, rank, *_ in _flat_player_rows():
        if a in ids and cat == category:
            by.setdefault(a, []).append(rank)
    return {a: {"events": len(v), "best": min(v), "median": statistics.median(v)} for a, v in by.items()}


def status_counts():
    import time as _t
    now, out = _t.time(), {"finished": 0, "live": 0, "upcoming": 0, "not collected yet": 0}
    for w in window_list():
        if w["final"]:
            out["finished"] += 1
        elif w["begin"] <= now <= w["end"]:
            out["live"] += 1
        elif w["begin"] > now:
            out["upcoming"] += 1
        elif w["end"] < now:
            out["not collected yet"] += 1
    return out


# Must stay last: on the hosted site every function above is replaced by its Postgres version.
if (_os.environ.get("FNGA_DB_URL") or _os.environ.get("NEON2_POSTGRES_URL")
        or _os.environ.get("POSTGRES_URL") or _os.environ.get("DATABASE_URL")):
    from .storage_pg import *  # noqa: F401,F403,E402
