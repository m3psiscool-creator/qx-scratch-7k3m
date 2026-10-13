"""Vercel entrypoint (FastAPI)."""
import hmac
import os
import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from fngameanalyzer import auth, collector, config, service, storage
from fngameanalyzer.ui import PAGE

app = FastAPI()


def _is_admin(key):
    want = os.environ.get("ADMIN_KEY", "")
    return bool(want) and hmac.compare_digest(str(key or ""), want)


def _err(e, code=200):
    return JSONResponse({"error": str(e)}, status_code=code)


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


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
