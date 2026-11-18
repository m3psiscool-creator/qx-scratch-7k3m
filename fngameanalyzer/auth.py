import base64
import json
import time

import requests

from . import config, storage


class NotLoggedIn(RuntimeError):
    pass


def _basic(client=None):
    cid, sec = client or (config.CLIENT_ID, config.CLIENT_SECRET)
    return {"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()}


def _token(data, client=None):
    r = requests.post(f"{config.ACCOUNT}/oauth/token", data=data, headers=_basic(client), timeout=30)
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


# ---- permanent login: device auth (a fresh session on every use; only a password reset or revoking it ends it)
def _device():
    d = storage.kv_get("device")
    if not d:
        return None
    bad = storage.kv_get("device_bad") or 0
    if bad > d["created"] and time.time() - bad < 600:   # Epic just refused it: use the old login meanwhile, try again in 10 min
        return None
    return d


def _device_grant(dev):
    return _token({"grant_type": "device_auth", "account_id": dev["account_id"], "device_id": dev["device_id"],
                   "secret": dev["secret"], "token_type": "eg1"}, client=tuple(dev["client"][1:]))


def device_start():
    """Step 1 of the permanent login: ask Epic for an activation link. The owner opens it (logged in to Epic) and approves."""
    errs = []
    for name, cid, sec in config.DEVICE_CLIENTS:
        try:
            tok = _token({"grant_type": "client_credentials", "token_type": "eg1"}, client=(cid, sec))
            r = requests.post(f"{config.ACCOUNT}/oauth/deviceAuthorization", headers={"Authorization": "Bearer " + tok["access_token"],
                              "Content-Type": "application/x-www-form-urlencoded"}, data="prompt=login", timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"deviceAuthorization {r.status_code}: {r.text[:200]}")
            j = r.json()
        except RuntimeError as e:
            errs.append(f"{name}: {str(e)[:160]}")
            continue
        storage.kv_set("device_pending", {"client": [name, cid, sec], "device_code": j["device_code"],
                                           "interval": j.get("interval", 10), "expires_at": time.time() + int(j.get("expires_in", 600))})
        note("device start", name)
        return {"url": j.get("verification_uri_complete") or j.get("verification_uri"), "user_code": j.get("user_code"),
                "expires_in": j.get("expires_in"), "client": name}
    raise RuntimeError("No Epic client accepted the request. " + " | ".join(errs))


def device_finish():
    """Step 2, after the owner approved the link: turn it into a device auth, test it and keep it for good."""
    p = storage.kv_get("device_pending")
    if not p or time.time() > p["expires_at"]:
        raise RuntimeError("No pending activation (or it expired): start again")
    name, cid, sec = p["client"]
    try:
        tok = _token({"grant_type": "device_code", "device_code": p["device_code"], "token_type": "eg1"}, client=(cid, sec))
    except RuntimeError as e:
        if "authorization_pending" in str(e):
            return {"pending": True}
        raise
    acct = tok["account_id"]
    r = requests.post(f"{config.ACCOUNT}/public/account/{acct}/deviceAuth",
                      headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Epic refused to create a device login with {name} ({r.status_code}): {r.text[:300]}")
    j = r.json()
    dev = {"account_id": acct, "device_id": j["deviceId"], "secret": j["secret"], "created": time.time(), "client": [name, cid, sec]}
    t = _device_grant(dev)   # prove it works before keeping it
    _verify(t["access_token"], acct)   # and that it can read what the site needs
    storage.kv_set("device", dev)
    storage.kv_set("dev_tok", {"access_token": t["access_token"], "expires_at": time.time() + int(t.get("expires_in", 7200))})
    storage.kv_set("device_pending", None)
    Session._mem.update(tok=None, exp=0, dev=False)
    note("device login", f"permanent login saved ({name})")
    return {"account_id": acct, "client": name}


def _verify(access, acct):
    h = {"Authorization": "Bearer " + access}
    r = requests.get(f"{config.EVENTS}/events/Fortnite/download/{acct}", headers=h, timeout=30,
                     params={"region": "EU", "platform": "Windows", "teamAccountIds": acct})
    if r.status_code != 200:
        raise RuntimeError(f"The permanent login cannot read the event list ({r.status_code}): {r.text[:200]}")
    r = requests.get("https://datastorage-public-service-live.ol.epicgames.com/api/v1/data/fnreplaysmetadata/public/" + "0" * 32 + ".json",
                     headers=h, timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError(f"The permanent login cannot reach the replay service ({r.status_code}): {r.text[:200]}")


def _device_bearer():
    """Access token from the device login, or None when there is none (or Epic refuses it right now)."""
    m = Session._mem
    d = _device()
    if not d:
        return None
    if m["tok"] and m.get("dev") and time.time() < m["exp"] - 300:
        return m["tok"]
    t = storage.kv_get("dev_tok")
    if t and time.time() < t["expires_at"] - 300:
        m.update(tok=t["access_token"], exp=t["expires_at"], dev=True)
        return t["access_token"]
    with storage.locked("auth"):
        t = storage.kv_get("dev_tok")
        if t and time.time() < t["expires_at"] - 300:
            m.update(tok=t["access_token"], exp=t["expires_at"], dev=True)
            return t["access_token"]
        try:
            tok = _device_grant(d)
        except RuntimeError as e:
            note("device login FAILED", e)
            storage.kv_set("device_bad", time.time())
            return None
        t = {"access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 7200))}
        storage.kv_set("dev_tok", t)
        m.update(tok=t["access_token"], exp=t["expires_at"], dev=True)
        note("device token ok")
        return t["access_token"]


def load():
    d = storage.kv_get("auth")
    if not d and config.AUTH_FILE.exists():  # login made by the old local command
        old = json.loads(config.AUTH_FILE.read_text())
        if "refresh_token" in old:
            d = {"account_id": old["account_id"], "refresh_token": old["refresh_token"],
                 "access_token": None, "expires_at": 0, "refresh_expires_at": 0}
    return d


def status():
    dev = _device()
    d = load()
    if dev:
        return {"logged_in": True, "account_id": dev["account_id"], "permanent": True, "refresh_valid_for_s": 10 ** 9}
    if not d:
        return {"logged_in": False}
    bad = storage.kv_get("auth_bad")
    if bad and bad > d.get("saved_at", 0):
        return {"logged_in": False, "reason": "Epic rejected the saved login; log in again"}
    return {"logged_in": True, "account_id": d["account_id"],
            "refresh_valid_for_s": max(0, int(d.get("refresh_expires_at", 0) - time.time()))}


class Session:
    def __init__(self):
        dev = _device()
        d = load()
        if not d and not dev:
            raise NotLoggedIn("Not logged in: open the site's Login page")
        self.account_id = (dev or d)["account_id"]

    _mem = {"tok": None, "exp": 0}   # per-process cache: avoids a database read per request

    def bearer(self):
        m = Session._mem
        tok = _device_bearer()
        if tok:
            return tok
        if m["tok"] and not m.get("dev") and time.time() < m["exp"] - 300:
            return m["tok"]
        d = load()
        if not d:
            raise NotLoggedIn("Epic refused the permanent login and no older login is saved: log in again on the Status page")
        if d.get("access_token") and time.time() < d["expires_at"] - 300:
            m.update(tok=d["access_token"], exp=d["expires_at"])
            return d["access_token"]
        bad = storage.kv_get("auth_bad")
        if bad and bad > d.get("saved_at", 0) and time.time() - bad < 600:   # Epic just refused this login: do not hammer it every minute
            raise NotLoggedIn("Epic login expired, log in again on the Status page")
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
                Session._mem.update(tok=None, exp=0, dev=False)
                t = storage.kv_get("dev_tok")
                if t and t["access_token"] == used:   # the permanent login's token was revoked early: the next call makes a new one
                    storage.kv_set("dev_tok", {**t, "expires_at": 0})
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
