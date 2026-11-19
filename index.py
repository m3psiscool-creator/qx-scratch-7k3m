"""Vercel entrypoint (FastAPI)."""
import hashlib
import hmac
import os
import re
import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from fngameanalyzer import art, auth, signin, collector, config, drops, insights, me, service, storage, strategy, tracks

app = FastAPI()


# How long Vercel's cache may reuse an answer (seconds). Identical requests inside this window cost
# the database nothing, whoever asks and however often a page refreshes.
CACHE_TTL = {"/api/predict": 120, "/api/bubble": 120, "/api/home": 20, "/api/live": 15, "/api/windows": 60,
             "/api/window": 60, "/api/board": 30, "/api/series": 30, "/api/thresholds": 30,
             "/api/archive": 300, "/api/classes": 300, "/api/class": 300, "/api/fncs": 120,
             "/api/players": 300, "/api/player": 300,
             "/api/scoring": 600, "/api/profile": 600, "/api/pace": 300, "/api/safety": 120, "/api/ladder": 120, "/api/tempo": 600, "/api/me": 30, "/api/account": 600, "/api/sessions": 120, "/api/drops/events": 120, "/api/drops/info": 300, "/api/drops/grid": 120, "/api/drops/area": 120, "/api/drops/hotspots": 120, "/api/drops/loot": 300, "/api/maps": 300, "/api/tracks/player": 60, "/api/tracks/recent": 120, "/api/tracks/windows": 120, "/api/tracks/window": 120, "/api/tracks/playerwindow": 120, "/api/tracks/game": 600, "/api/drops/areas": 120, "/api/calendar.ics": 300, "/api/health": 30, "/api/art": 21600, "/api/public/demo": 3600}


# API paths anyone may call (sign-in itself, the tournament pictures, the calendar feed, aggregate numbers for the signed-out home page)
OPEN_API = ("/api/auth/", "/api/public/", "/api/art", "/api/calendar.ics")
# these check their own key (owner/worker/cron endpoints)
SELF_AUTH = ("/api/admin/", "/api/tick", "/api/login")
MAIN_HOST = "fncslab.com"
ALT_HOSTS = {"www.fncslab.com", "fncslab.org", "www.fncslab.org", "fncslab.info", "www.fncslab.info", "fncslab.store", "www.fncslab.store"}


@app.middleware("http")
async def meter(request, call_next):
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
    if host in ALT_HOSTS:   # one address for the site: the other domains send visitors to fncslab.com
        q = ("?" + request.url.query) if request.url.query else ""
        return RedirectResponse("https://" + MAIN_HOST + request.url.path + q, status_code=308)
    path = request.url.path
    gated = path.startswith("/api/") and not path.startswith(OPEN_API)
    if gated and request.method != "OPTIONS" and not path.startswith(SELF_AUTH):
        tok = request.headers.get("authorization", "")
        if not (_is_admin(request.headers.get("x-admin-key")) or signin.verify(tok[7:] if tok.lower().startswith("bearer ") else tok)):
            return JSONResponse({"error": "Sign in required."}, status_code=401, headers={"Cache-Control": "no-store"})
    resp = await call_next(request)
    ttl = CACHE_TTL.get(request.url.path)
    if request.url.path.startswith("/api/status"):
        resp.headers["Cache-Control"] = "no-store"
    if ttl and request.method == "GET" and resp.status_code == 200 and "x-admin-key" not in request.headers:
        if gated:   # answers only for signed-in visitors: never stored in a shared cache
            resp.headers["Cache-Control"] = f"private, max-age={min(ttl, 60)}"
        else:
            resp.headers["Cache-Control"] = f"public, s-maxage={ttl}, stale-while-revalidate={ttl * 3}"
    elif gated:
        resp.headers["Cache-Control"] = "private, no-store"
    try:
        storage.egress_flush()   # keeps a running total of data read from the database
    except Exception:
        pass
    return resp


def _is_admin(key):
    # ADMIN_KEY (cron-job.org, GitHub Actions) and ADMIN_KEY_OWNER (the owner's own key, both are sensitive Vercel env vars)
    for name in ("ADMIN_KEY", "ADMIN_KEY_OWNER"):
        want = os.environ.get(name, "")
        if want and hmac.compare_digest(str(key or ""), want):
            return True
    return False


def _err(e, code=200):
    return JSONResponse({"error": str(e)}, status_code=code)


WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _file(name, ctype):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return Response(f.read(), media_type=ctype, headers={"Cache-Control": "public, max-age=60"})


@app.get("/", response_class=HTMLResponse)
def home_page():
    return _file("index.html", "text/html; charset=utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return Response(open(os.path.join(WEB, "admin.html"), encoding="utf-8").read(), media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/api/auth/config")
def auth_config():
    return {"google_client_id": signin.google_client_id()}


@app.post("/api/auth/google")
async def auth_google(req: Request):
    body = await req.json()
    try:
        user = signin.google_user(body.get("credential"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    signin.record(user)
    return {"token": signin.issue(user), "user": {k: user[k] for k in ("name", "first", "picture", "email")}}


@app.get("/api/auth/me")
def auth_me(authorization: str = Header(default="")):
    u = signin.verify(authorization.replace("Bearer ", "", 1))
    if not u:
        return JSONResponse({"error": "not signed in"}, status_code=401)
    return {"user": {k: u.get(k, "") for k in ("name", "first", "picture", "email")}}


@app.get("/api/public/demo")
def public_demo():
    return _api(drops.demo)


@app.get("/api/art")
def tournament_art():
    """Epic's tournament pictures and colours (public list, no database); cached for hours at the CDN."""
    return art.compact()


@app.get("/api/admin/overview")
def admin_overview(x_admin_key: str = Header(default=""), test: int = 0):
    """Owner only: everything the /admin page shows. ?test=1 also makes one real call with the stored Epic login."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    out = {"now": time.time(), "regions": config.TRACKED_REGIONS, "login_url": config.LOGIN_URL, "db_ok": True}
    try:
        tick = storage.kv_get("last_tick") or {}
        out["login"] = auth.status()
        out["last_tick_age_s"] = round(time.time() - tick["at"]) if tick.get("at") else None
        out["idle_until"] = tick.get("idle_until")
        out["last_log"] = tick.get("log", [])[-6:]
        out["auth_log"] = (storage.kv_get("auth_log") or [])[-8:]
        out["egress_mb_month"] = round(storage.egress_month() / 1e6, 1)
    except Exception as e:
        out["db_ok"] = False
        out["db_error"] = str(e)[:300]
        return out
    if test:
        try:
            auth.Session().bearer()
            out["login_test"] = {"ok": True}
        except Exception as e:
            out["login_test"] = {"ok": False, "error": str(e)[:300]}
    return out


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


@app.get("/map.js")
def map_js():
    return _file("map.js", "application/javascript; charset=utf-8")


@app.get("/landing.js")
def landing_js():
    return _file("landing.js", "application/javascript; charset=utf-8")


@app.get("/pages.js")
def pages_js():
    return _file("pages.js", "application/javascript; charset=utf-8")


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
def api_accuracy(x_admin_key: str = Header(default="")):
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return _api(insights.accuracy)


@app.get("/api/status_full")
def api_status_full(x_admin_key: str = Header(default="")):
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
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


@app.get("/api/drops/hotspots")
def api_drops_hotspots(window: str, top: int = 100, game: int = 0):
    return _api(drops.hotspots, window, max(1, top), game)


@app.get("/api/maps")
def api_maps():
    return _api(drops.maps)


@app.get("/api/drops/loot")
def api_drops_loot(window: str, frac: float = 0, nms: int = 1, smooth: int = 0, cls: str = ""):
    kinds = drops.CTN_KINDS if cls == "all" else tuple(c for c in cls.split(",") if c) or None
    return _api(drops.loot, window, frac if 0.002 <= frac <= 0.5 else None, min(max(nms, 1), 3), min(max(smooth, 0), 2), kinds)


@app.get("/api/drops/areas")
def api_drops_areas(window: str, top: int = 100, game: int = 0, min_chests: int = 4):
    return _api(drops.areas, window, max(1, top), game, 0.055, max(1, min_chests))


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


@app.post("/api/admin/containers")
async def admin_containers(req: Request, x_admin_key: str = Header(default="")):
    """Owner only: container positions read from replays (see worker/landings/Containers.cs)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await req.json()
        return drops.add_containers(body.get("window_id"), body.get("matches"))
    except Exception as e:
        return _err(e)


@app.post("/api/admin/containers_remove")
async def admin_containers_remove(req: Request, x_admin_key: str = Header(default="")):
    """Owner only: take matches out of a map's container atlas (they were filed under the wrong map)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await req.json()
        return drops.remove_containers(body.get("map_key"), body.get("matches"))
    except Exception as e:
        return _err(e)


@app.post("/api/admin/drops_complete")
async def admin_drops_complete(req: Request, x_admin_key: str = Header(default="")):
    """Owner only: the worker read every match of this window ({window_id, failed}); it is not listed again for a while."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    b = await req.json()
    done = storage.kv_get("drops_complete") or {}
    done[str(b["window_id"])] = {"at": int(time.time()), "failed": int(b.get("failed") or 0)}
    storage.kv_set("drops_complete", done)
    return {"ok": True}


@app.get("/api/admin/budget")
def admin_budget(x_admin_key: str = Header(default="")):
    """Owner only: database data read this month (MB). The free Neon plan allows 5,000 MB; the worker stops well before."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"egress_mb_month": round(storage.egress_month() / 1e6, 1)}


@app.post("/api/admin/tracks")
async def admin_tracks(req: Request, x_admin_key: str = Header(default="")):
    """Owner only: one match's movement tracks (see worker/run.mjs --tracks)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return tracks.ingest(await req.json())
    except Exception as e:
        return _err(e)


@app.get("/api/tracks/player")
def api_tracks_player(account: str):
    return _api(tracks.player_games, account)


@app.get("/api/tracks/windows")
def api_tracks_windows():
    return _api(tracks.windows)


@app.get("/api/tracks/window")
def api_tracks_window(window: str):
    return _api(tracks.window_players, window)


@app.get("/api/tracks/playerwindow")
def api_tracks_playerwindow(window: str, account: str):
    return _api(tracks.player_window, window, account)


@app.get("/api/tracks/recent")
def api_tracks_recent():
    return _api(tracks.recent)


@app.get("/api/tracks/game")
def api_tracks_game(session: str):
    return _api(tracks.game, session)


@app.get("/rotations.js")
def rotations_js():
    return _file("rotations.js", "application/javascript; charset=utf-8")


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


@app.get("/api/admin/event_scan")
def admin_event_scan(q: str = "", x_admin_key: str = Header(default="")):
    """Owner only: every event Epic lists that matches q, tracked by the site or not."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import probe
    return _api(probe.scan, q)


@app.get("/api/admin/prestart")
def admin_prestart(window: str, x_admin_key: str = Header(default="")):
    """Owner only: the as-of-the-start prediction of one finished window (what the accuracy page scores), or the error."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import collector
    w = storage.get_window(window)
    if not w:
        return _err("Unknown window")
    try:
        return {"window": window, "ranks": collector._ranks_of(w), "got": service.prestart(window, collector._ranks_of(w)), "kv": storage.kv_get("prest2:" + window)}
    except Exception as ex:
        import traceback
        return {"error": str(ex), "trace": traceback.format_exc()[-1500:]}


@app.get("/api/admin/score")
def admin_score(seconds: int = 200, x_admin_key: str = Header(default="")):
    """Owner only: score finished tournaments as of their start for up to `seconds` (the collector also does a few per pass)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return _api(lambda: {"scored": collector.backfill_prestart(min(max(seconds, 5), 250)),
                         "left": sum(1 for w in storage.windows(final=True, light=True) if not storage.kv_get("prest2:" + w["window_id"]))})


@app.get("/api/admin/ctn")
def admin_ctn(map: str = "BR", ver: str = "ctn:", x_admin_key: str = Header(default="")):
    """Owner only: what the container counts of a map hold, by container class and how often each was searched."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import re as _re
    a = storage.kv_get(ver + map) or {}
    by = {}
    for name, it in (a.get("items") or {}).items():
        fam = _re.sub(r"_C_UAID.*|_UAID.*", "", name)
        d = by.setdefault(fam, {"names": 0, "n1": 0, "n_med": []})
        d["names"] += 1
        d["n1"] += it["n"] <= 1
        d["n_med"].append(it["n"])
    for d in by.values():
        d["n_med"] = sorted(d["n_med"])[len(d["n_med"]) // 2]
    return {"M": a.get("M"), "items": len(a.get("items") or {}), "classes": dict(sorted(by.items(), key=lambda kv: -kv[1]["names"]))}


@app.get("/api/admin/sync_test")
def admin_sync_test(region: str = "NAC", x_admin_key: str = Header(default="")):
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from fngameanalyzer import probe
    return _api(probe.sync_test, region)


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
    napping = bool(tick) and time.time() < (tick.get("idle_until") or 0) + 600   # quiet on purpose between tournaments
    return {"ok": bool(s.get("logged_in")) and (idle is not None and (idle < 900 or napping)), "logged_in": bool(s.get("logged_in")), "idle_s": idle}


@app.get("/api/status")
def status(x_admin_key: str = Header(default="")):
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
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


@app.post("/api/login_device")
async def login_device(req: Request):
    """Turn the current (still valid) login into a permanent device login."""
    body = await req.json()
    if not _is_admin(body.get("key")):
        return {"ok": False, "error": "wrong admin key"}
    try:
        return {"ok": True, **auth.make_permanent(auth.Session().bearer())}
    except Exception as e:
        return {"ok": False, "error": str(e)[:900]}


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
    # cron-job.org calls this every minute; only every TICK_EVERY_MIN-th minute does work, the others return before touching the
    # database (so it can scale to zero in between and use less compute). ?sync=1 always runs.
    every = int(os.environ.get("TICK_EVERY_MIN", "5"))
    if not sync and ((every > 1 and (int(time.time()) // 60) % every != 0) or not collector.should_run()):
        return {"skipped": True, "reason": f"runs every {every} minutes while a tournament is on, about every 30 minutes otherwise"}
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


@app.get("/{page}", response_class=HTMLResponse, include_in_schema=False)
def public_page(page: str):
    """Addresses for the public pages (shared links, Google's consent screen): the app opens them as #/page."""
    if page in ("about", "how", "faq", "privacy", "terms", "contact"):
        return RedirectResponse("/#/" + page, status_code=302)
    return JSONResponse({"error": "Not found"}, status_code=404)
