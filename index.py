"""Vercel entrypoint (FastAPI)."""
import hmac
import os
import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from fngameanalyzer import auth, collector, config, insights, service, storage

app = FastAPI()


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


@app.get("/style.css")
def style_css():
    return _file("style.css", "text/css; charset=utf-8")


def _api(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        return _err(e)


@app.get("/api/home")
def api_home():
    return _api(insights.home)


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
        return service.window_info(w)
    return _api(f)


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
def tick(authorization: str = Header(default=""), x_admin_key: str = Header(default="")):
    secret = os.environ.get("CRON_SECRET", "")
    if not (secret and hmac.compare_digest(authorization, f"Bearer {secret}")) and not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return collector.run_tick(duration=int(os.environ.get("TICK_SECONDS", "25")))


@app.post("/api/admin/window")
async def seed_window(req: Request, x_admin_key: str = Header(default="")):
    """Load one finished window (used once to upload the collected history)."""
    if not _is_admin(x_admin_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    w = await req.json()
    storage.upsert_window(w)
    storage.save_final(w["window_id"], w)
    return {"ok": True, "window_id": w["window_id"]}
