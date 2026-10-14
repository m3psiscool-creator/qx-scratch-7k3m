import base64
import json
import time

import requests

from . import config, storage


class NotLoggedIn(RuntimeError):
    pass


def _basic():
    raw = f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _token(data):
    r = requests.post(f"{config.ACCOUNT}/oauth/token", data=data, headers=_basic(), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Epic token error {r.status_code}: {r.text[:300]}")
    return r.json()


def note(kind, detail=""):
    """Keep the last few login events so a broken login can be diagnosed from the Status page."""
    try:
        log = storage.kv_get("auth_log") or []
        storage.kv_set("auth_log", ([{"at": time.time(), "kind": kind, "detail": str(detail)[:140]}] + log)[:15])
    except Exception:
        pass


def _store(tok):
    """Persist a token response (the refresh token rotates on every use)."""
    d = {"account_id": tok["account_id"], "refresh_token": tok["refresh_token"],
         "access_token": tok["access_token"],
         "expires_at": time.time() + int(tok.get("expires_in", 7200)),
         "refresh_expires_at": time.time() + int(tok.get("refresh_expires", 28800)),
         "saved_at": time.time()}
    storage.kv_set("auth", d)
    return d


def login(code):
    """Exchange a one-time authorizationCode and keep the rolling refresh token."""
    tok = _token({"grant_type": "authorization_code", "code": code, "token_type": "eg1"})
    _store(tok)
    note("login", "new login saved")
    return tok["account_id"]


def load():
    d = storage.kv_get("auth")
    if not d and config.AUTH_FILE.exists():  # login made by the old local command
        old = json.loads(config.AUTH_FILE.read_text())
        if "refresh_token" in old:
            d = {"account_id": old["account_id"], "refresh_token": old["refresh_token"],
                 "access_token": None, "expires_at": 0, "refresh_expires_at": 0}
    return d


def status():
    d = load()
    if not d:
        return {"logged_in": False}
    bad = storage.kv_get("auth_bad")
    if bad and bad > d.get("saved_at", 0):
        return {"logged_in": False, "reason": "Epic rejected the saved login; log in again"}
    return {"logged_in": True, "account_id": d["account_id"],
            "refresh_valid_for_s": max(0, int(d.get("refresh_expires_at", 0) - time.time()))}


class Session:
    def __init__(self):
        d = load()
        if not d:
            raise NotLoggedIn("Not logged in: open the site's Login page")
        self.account_id = d["account_id"]

    _mem = {"tok": None, "exp": 0}   # per-process cache: avoids a database read per request

    def bearer(self):
        m = Session._mem
        if m["tok"] and time.time() < m["exp"] - 300:
            return m["tok"]
        d = load()
        if d.get("access_token") and time.time() < d["expires_at"] - 300:
            m.update(tok=d["access_token"], exp=d["expires_at"])
            return d["access_token"]
        with storage.locked("auth"):  # another run may have refreshed while we waited
            d = load()
            if d.get("access_token") and time.time() < d["expires_at"] - 300:
                m.update(tok=d["access_token"], exp=d["expires_at"])
                return d["access_token"]
            try:
                d = _store(_token({"grant_type": "refresh_token",
                                   "refresh_token": d["refresh_token"],
                                   "token_type": "eg1"}))
                m.update(tok=d["access_token"], exp=d["expires_at"])
                note("refresh ok")
                return d["access_token"]
            except RuntimeError as e:
                note("refresh FAILED", e)
                storage.kv_set("auth_bad", time.time())   # the Status page then asks for a new login
                raise NotLoggedIn(f"Epic login expired, log in again ({e})")

    def get(self, url, **params):
        for attempt in range(5):
            time.sleep(config.REQUEST_DELAY * (attempt + 1))
            try:
                r = requests.get(url, params=params, timeout=30,
                                 headers={"Authorization": "Bearer " + self.bearer()})
            except requests.ConnectionError:
                if attempt == 4:
                    raise
                continue
            if r.status_code == 401 and attempt < 4:
                # Epic revoked this access token early: drop it and fetch a fresh one with the refresh token
                used = r.request.headers.get("Authorization", "")[7:]
                Session._mem.update(tok=None, exp=0)
                with storage.locked("auth"):      # never write back a stale copy of the login
                    d = load()
                    if d and d.get("access_token") == used:   # only if nobody refreshed it meanwhile
                        d["expires_at"] = 0
                        storage.kv_set("auth", d)
                        note("401", "access token rejected by Epic; refreshing")
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:300]}")
            return r.json()
