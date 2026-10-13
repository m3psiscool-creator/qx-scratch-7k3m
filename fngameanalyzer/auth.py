import base64
import json
import time

import requests

from . import config


def _basic():
    raw = f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _token(data):
    r = requests.post(f"{config.ACCOUNT}/oauth/token", data=data, headers=_basic(), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Epic token error {r.status_code}: {r.text[:300]}")
    return r.json()


def login(code):
    """Exchange a one-time authorizationCode for a saved device auth."""
    tok = _token({"grant_type": "authorization_code", "code": code, "token_type": "eg1"})
    acc = tok["account_id"]
    r = requests.post(
        f"{config.ACCOUNT}/public/account/{acc}/deviceAuth",
        headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=30)
    if r.status_code == 200:
        d = r.json()
        _save({"account_id": acc, "device_id": d["deviceId"], "secret": d["secret"]})
    else:  # this client may not create device auth: keep a rolling refresh token instead
        print("Device auth not allowed; using refresh token (re-login if idle > ~8h).")
        _save({"account_id": acc, "refresh_token": tok["refresh_token"]})
    return acc


def _save(d):
    config.AUTH_FILE.write_text(json.dumps(d))


class Session:
    def __init__(self):
        if not config.AUTH_FILE.exists():
            raise SystemExit("Not logged in. Run: python -m fngameanalyzer login")
        self.auth = json.loads(config.AUTH_FILE.read_text())
        self.account_id = self.auth["account_id"]
        self._tok = None
        self._exp = 0

    def bearer(self):
        if time.time() > self._exp - 60:
            if "refresh_token" in self.auth:
                t = _token({"grant_type": "refresh_token",
                            "refresh_token": self.auth["refresh_token"], "token_type": "eg1"})
                self.auth["refresh_token"] = t["refresh_token"]
                _save(self.auth)
            else:
                t = _token({"grant_type": "device_auth", "account_id": self.account_id,
                            "device_id": self.auth["device_id"], "secret": self.auth["secret"],
                            "token_type": "eg1"})
            self._tok = t["access_token"]
            self._exp = time.time() + int(t.get("expires_in", 7200))
        return self._tok

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
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:300]}")
            return r.json()
