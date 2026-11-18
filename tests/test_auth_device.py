"""Permanent (device auth) login, with Epic and the database stubbed: no network, never the production login."""
import time
import unittest
from unittest import mock

from fngameanalyzer import auth, storage


class Resp:
    def __init__(self, code=200, body=None):
        self.status_code, self._b, self.text = code, body or {}, str(body)

    def json(self):
        return self._b


class DeviceLogin(unittest.TestCase):
    def setUp(self):
        self.kv = {}
        self.posts = []
        self.p = [mock.patch.object(storage, "kv_get", lambda k: self.kv.get(k)),
                  mock.patch.object(storage, "kv_set", lambda k, v: self.kv.__setitem__(k, v)),
                  mock.patch.object(auth.config, "AUTH_FILE", mock.Mock(exists=lambda: False))]
        for p in self.p:
            p.start()
        auth.Session._mem.update(tok=None, exp=0, dev=False)

    def tearDown(self):
        for p in self.p:
            p.stop()

    def post(self, url, data=None, headers=None, **kw):
        self.posts.append((url, data, headers))
        if url.endswith("/oauth/token"):
            if data["grant_type"] == "device_auth":
                if self.kv.get("revoked"):
                    return Resp(400, {"errorCode": "invalid_account_credentials"})
                return Resp(200, {"access_token": "dev-%d" % len(self.posts), "expires_in": 7200, "account_id": "A"})
            return Resp(200, {"access_token": "ios-token", "expires_in": 7200, "account_id": "A"})
        if url.endswith("/deviceAuth"):
            return Resp(200, {"deviceId": "D", "secret": "S", "accountId": "A"})
        raise AssertionError(url)

    def get(self, url, **kw):
        return Resp(404 if "fnreplaysmetadata" in url else 200, {})

    def test_setup_stores_device_and_uses_ios_client(self):
        with mock.patch("requests.post", self.post), mock.patch("requests.get", self.get):
            self.assertEqual(auth.device_login("code"), "A")
        self.assertEqual(self.kv["device"]["device_id"], "D")
        self.assertIn(auth.config.IOS_CLIENT_ID, __import__("base64").b64decode(self.posts[0][2]["Authorization"][6:]).decode())

    def test_setup_refused_keeps_nothing(self):
        def post(url, **kw):
            return Resp(403, {"errorCode": "missing_permission"}) if url.endswith("/deviceAuth") else self.post(url, **kw)
        with mock.patch("requests.post", post), mock.patch("requests.get", self.get):
            with self.assertRaises(RuntimeError):
                auth.device_login("code")
        self.assertNotIn("device", self.kv)

    def test_token_unusable_for_events_is_not_kept(self):
        with mock.patch("requests.post", self.post), mock.patch("requests.get", lambda u, **k: Resp(403, {})):
            with self.assertRaises(RuntimeError):
                auth.device_login("code")
        self.assertNotIn("device", self.kv)

    def test_bearer_renews_by_itself_and_falls_back(self):
        self.kv["device"] = {"account_id": "A", "device_id": "D", "secret": "S", "created": time.time() - 100}
        with mock.patch("requests.post", self.post):
            s = auth.Session()
            self.assertEqual(s.account_id, "A")
            t1 = s.bearer()
            self.assertEqual(s.bearer(), t1)   # cached, no second login
            self.kv["dev_tok"]["expires_at"] = 0
            auth.Session._mem.update(tok=None, exp=0, dev=False)
            self.assertNotEqual(s.bearer(), t1)   # expired: new session from the device login, no code needed
            self.kv["revoked"] = True
            self.kv["dev_tok"]["expires_at"] = 0
            auth.Session._mem.update(tok=None, exp=0, dev=False)
            with self.assertRaises(auth.NotLoggedIn):   # revoked and no older login saved
                s.bearer()
        self.assertIn("device_bad", self.kv)


if __name__ == "__main__":
    unittest.main()
