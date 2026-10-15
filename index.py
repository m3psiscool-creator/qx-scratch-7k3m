"""Vercel entrypoint (FastAPI)."""
import hashlib
import hmac
import os
import re
import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from fngameanalyzer import auth, collector, config, drops, insights, me, service, storage, strategy

app = FastAPI()


# How long Vercel's cache may reuse an answer (seconds). Identical requests inside this window cost
# the database nothing, whoever asks and however often a page refreshes.
CACHE_TTL = {"/api/predict": 120, "/api/bubble": 120, "/api/home": 20, "/api/live": 15, "/api/windows": 60,
             "/api/window": 60, "/api/board": 30, "/api/series": 30, "/api/thresholds": 30,
             "/api/archive": 300, "/api/classes": 300, "/api/class": 300, "/api/fncs": 120,
             "/api/accuracy": 300, "/api/players": 300, "/api/player": 300,
             "/api/scoring": 600, "/api/profile": 600, "/api/pace": 300, "/api/safety": 120, "/api/ladder": 120, "/api/tempo": 600, "/api/me": 30, "/api/account": 600, "/api/sessions": 120, "/api/drops/events": 120, "/api/drops/info": 300, "/api/drops/grid": 120, "/api/drops/area": 120, "/api/drops/pois": 120, "/api/calendar.ics": 300, "/api/health": 30}


@app.middleware("http")
async def meter(request, call_next):
    resp = await call_next(request)
    ttl = CACHE_TTL.get(request.url.path)
    if request.url.path.startswith("/api/status"):
        resp.headers["Cache-Control"] = "no-store"
    if ttl and request.method == "GET" and resp.status_code == 200 and "x-admin-key" not in request.headers:
        resp.headers["Cache-Control"] = f"public, s-maxage={ttl}, stale-while-revalidate={ttl * 3}"
    try:
        storage.egress_flush()   # keeps a running total of data read from the database
    except Exception:
        pass
    return resp


def _is_admin(key):
    want = os.environ.get("ADMIN_KEY", "")
    return bool(want) and hmac.compare_digest(str(key or ""), want)


def _err(e, code=200):
    return JSONResponse({"error": str(e)}, status_code=code)


WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _file(name, ctype):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return Response(f.read(), media_type=ctype, headers={"Cache-Control": "public, max-age=60"})


@app.get("/", response_class=HTMLResponse)
def home_page():
    return _file("index.html", "text/html; charset=utf-8")


@app.get("/app.js")
def app_js():
    return _file("app.js", "application/javascript; charset=utf-8")


@app.get("/lib.js")
def lib_js():
    return _file("lib.js", "application/javascript; charset=utf-8")


@app.get("/strategy.js")
def strategy_js():
    return _file("strategy.js", "application/javascript; charset=utf-8")


@app.get("/maps/{name}")
def map_image(name: str):
    """Map pictures for the Dropspots tab (files in web/maps, fixed names only)."""
    if not re.fullmatch(r"[a-z0-9\-]+\.(jpg|png)", name):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = os.path.join(WEB, "maps", name)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    with open(path, "rb") as f:
        return Response(f.read(), media_type="image/jpeg" if name.endswith(".jpg") else "image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/drops.js")
def drops_js():
    return _file("drops.js", "application/javascript; charset=utf-8")


@app.get("/style.css")
def style_css():
    return _file("style.css", "text/css; charset=utf-8")


def _api(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        return _err(e)


@app.get("/api/home")
def api_home(region: str = ""):
    return _api(insights.home, region)


@app.get("/api/board")
def api_board(window: str, page: int = 0, q: str = ""):
    return _api(insights.board, window, page, q)


@app.get("/api/archive")
def api_archive():
    return _api(insights.archive)


@app.get("/api/classes")
def api_classes():
    return _api(insights.classes)


@app.get("/api/class")
def api_class(name: str):
    return _api(insights.class_detail, name)


@app.get("/api/player")
def api_player(id: str):
    return _api(insights.player, id)


@app.get("/api/players")
def api_players(q: str = "", category: str = ""):
    return _api(insights.player_search, q) if q else _api(insights.top_players, category or None)


@app.get("/api/fncs")
def api_fncs():
    return _api(insights.fncs)


@app.get("/api/accuracy")
def api_accuracy():
    return _api(insights.accuracy)


@app.get("/api/status_full")
def api_status_full():
    return _api(insights.status)


@app.get("/api/window")
def api_window(window: str):
    def f():
        w = storage.get_window(window)
        if not w:
            raise ValueError("Unknown window")
        return {**service.window_info(w), "siblings": service.siblings(window)}
    return _api(f)


@app.get("/api/scoring")
def api_scoring(window: str):
    return _api(strategy.scoring, window)


@app.get("/api/profile")
def api_profile(window: str, rank: int = 0):
    return _api(strategy.profile, window, rank or None)


@app.get("/api/pace")
def api_pace(window: str, rank: int, target: float = 0):
    return _api(strategy.pace, window, rank, target or None)


@app.get("/api/safety")
def api_safety(window: str, rank: int):
    return _api(strategy.safety, window, rank)


@app.get("/api/me")
def api_me(window: str, name: str = "", account: str = ""):
    return _api(me.lookup, window, name, account or None)


@app.get("/api/calendar.ics")
def api_calendar(request: Request, region: str = "", family: str = "", category: str = "", q: str = "", window: str = "", favs: str = ""):
    site = f"{request.url.scheme}://{request.headers.get('host', 'fn-game-analyzer.vercel.app')}"
    try:
        body = service.calendar_ics(site, region, family, category, q, window, favs)
    except Exception as e:
        return _err(e)
    return Response(body, media_type="text/calendar; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="fn-tournaments.ics"'})


@app.post("/api/feedback")
async def api_feedback(req: Request):
    """Anyone can send an idea or a bug; the owner reads them with the admin key. Rate limited per visitor."""
    try:
        body = await req.json()
    except Exception:
        return _err("Bad request")
    text = str(body.get("text", "")).strip()[:1200]
    if len(text) < 5:
        return _err("Write a few words first.")
    ip = (req.headers.get("x-forwarded-for", "") or "x").split(",")[0].strip()
    key = "fb_rate:" + hashlib.sha1(ip.encode()).hexdigest()[:16]
    rate = storage.kv_get(key) or {"t": [], }
    now = time.time()
    rate["t"] = [t for t in rate["t"] if now - t < 86400]
    if rate["t"] and now - rate["t"][-1] < 30:
        return _err("Please wait a few seconds before sending another.")
    if len(rate["t"]) >= 10:
        return _err("That is plenty for today, thank you.")
    rate["t"].append(now)
    storage.kv_set(key, rate)
    items = storage.kv_get("feedback") or []
    items.insert(0, {"at": now, "kind": str(body.get("kind", "idea"))[:12], "text": text, "page": str(body.get("page", ""))[:160]})
    storage.kv_set("feedback", items[:300])
    return {"ok": True}


@app.get("/api/feedback")
def api_feedback_list(x_admin_key: str = Header(default="")):
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return storage.kv_get("feedback") or []


@app.get("/api/drops/events")
def api_drops_events():
    return _api(drops.events)


@app.get("/api/drops/info")
def api_drops_info(window: str):
    return _api(drops.map_info, window)


@app.get("/api/drops/grid")
def api_drops_grid(window: str, top: int = 100, game: int = 0):
    return _api(drops.grid, window, max(1, top), game)


@app.get("/api/drops/pois")
def api_drops_pois(window: str, top: int = 100, game: int = 0):
    return _api(drops.pois, window, max(1, top), game)


@app.get("/api/drops/area")
def api_drops_area(window: str, poly: str, top: int = 100, game: int = 0):
    def f():
        pts = [p.split(",") for p in poly.split(";") if p][:80]
        return drops.area(window, [[float(x), float(y)] for x, y in pts], max(1, top), game)
    return _api(f)


@app.post("/api/admin/drops")
async def admin_drops(req: Request, x_admin_key: str = Header(default="")):
    """Owner only: load landing rows for one tournament (see docs/dropspots-data.md)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return drops.ingest(await req.json())
    except Exception as e:
        return _err(e)


@app.get("/api/admin/probe")
def admin_probe(window: str, rank: int = 1, x_admin_key: str = Header(default="")):
    """Owner only: shows what a leaderboard entry holds and whether replay storage answers for its session id."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import probe
    return _api(probe.run, window, rank)


@app.get("/api/admin/replay")
def admin_replay(session: str, max_ms: int = 0, x_admin_key: str = Header(default="")):
    """Owner/worker only: file list and signed download links of one tournament match replay."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import replays
    return _api(replays.links, session, max_ms)


@app.get("/api/admin/matches")
def admin_matches(window: str, pages: int = 100, x_admin_key: str = Header(default="")):
    """Owner/worker only: every match of a tournament window with its teams, and which are already turned into landings."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import replays
    return _api(replays.matches, window, max(1, min(pages, 100)))


@app.get("/api/sessions")
def api_sessions(window: str):
    return _api(service.sessions, window)


@app.get("/api/account")
def api_account(name: str):
    return _api(me.account, name)


@app.get("/api/tempo")
def api_tempo(window: str):
    return _api(strategy.tempo, window)


@app.get("/api/ladder")
def api_ladder(window: str):
    return _api(strategy.ladder, window)


@app.get("/api/health")
def health():
    """Tiny, CDN-cached check for the site banner: is the collector running and is the Epic login valid?"""
    try:
        tick = storage.kv_get("last_tick")
        s = auth.status()
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}
    idle = round(time.time() - tick["at"]) if tick else None
    return {"ok": bool(s.get("logged_in")) and (idle is not None and idle < 900), "logged_in": bool(s.get("logged_in")), "idle_s": idle}


@app.get("/api/status")
def status():
    try:
        s = auth.status()
        tick = storage.kv_get("last_tick")
    except Exception as e:  # database not connected yet
        return {"logged_in": False, "db_error": str(e)[:200], "login_url": config.LOGIN_URL}
    s["last_tick_age_s"] = round(time.time() - tick["at"]) if tick else None
    s["login_url"] = config.LOGIN_URL
    s["regions"] = config.TRACKED_REGIONS
    return s


@app.get("/api/windows")
def windows():
    try:
        return service.list_windows()
    except Exception as e:
        return _err(e)


@app.get("/api/predict")
def predict(window: str, top: int, entrants: str = "", approx: int = 0):
    try:
        return service.run_predict(window, top, int(entrants) if entrants else None, bool(approx))
    except Exception as e:
        return _err(e)


@app.get("/api/thresholds")
def thresholds(window: str):
    try:
        return service.thresholds(window)
    except Exception as e:
        return _err(e)


@app.get("/api/series")
def series(window: str):
    try:
        return service.series_view(window)
    except Exception as e:
        return _err(e)


@app.get("/api/bubble")
def bubble(window: str, rank: int = 0, approx: int = 0):
    return _api(service.bubble_view, window, rank or None, bool(approx))


@app.get("/api/live")
def live(window: str):
    try:
        return service.live_view(window)
    except Exception as e:
        return _err(e)


@app.post("/api/login")
async def login(req: Request):
    body = await req.json()
    if not _is_admin(body.get("key")):
        return {"ok": False, "error": "wrong admin key"}
    try:
        return {"ok": True, "account_id": auth.login(body["code"].strip().strip('"'))}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@app.get("/api/tick")
def tick(authorization: str = Header(default=""), x_admin_key: str = Header(default=""), sync: int = 0):
    secret = os.environ.get("CRON_SECRET", "")
    if not (secret and hmac.compare_digest(authorization, f"Bearer {secret}")) and not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return collector.run_tick(duration=int(os.environ.get("TICK_SECONDS", "25")), force_sync=bool(sync))


@app.post("/api/admin/window")
async def seed_window(req: Request, x_admin_key: str = Header(default="")):
    """Load one finished window (used once to upload the collected history)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    w = await req.json()
    storage.upsert_window(w)
    storage.save_final(w["window_id"], w)
    return {"ok": True, "window_id": w["window_id"]}
