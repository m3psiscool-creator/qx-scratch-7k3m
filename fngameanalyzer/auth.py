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
    if r.status_code != 200:
        raise RuntimeError(f"Device auth error {r.status_code}: {r.text[:300]}")
    d = r.json()
    config.AUTH_FILE.write_text(json.dumps(
        {"account_id": acc, "device_id": d["deviceId"], "secret": d["secret"]}))
    return acc


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
            t = _token({"grant_type": "device_auth", "account_id": self.account_id,
                        "device_id": self.auth["device_id"], "secret": self.auth["secret"],
                        "token_type": "eg1"})
            self._tok = t["access_token"]
            self._exp = time.time() + int(t.get("expires_in", 7200))
        return self._tok

    def get(self, url, **params):
        time.sleep(config.REQUEST_DELAY)
        r = requests.get(url, params=params, timeout=30,
                         headers={"Authorization": "Bearer " + self.bearer()})
        if r.status_code != 200:
            raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:300]}")
        return r.json()
