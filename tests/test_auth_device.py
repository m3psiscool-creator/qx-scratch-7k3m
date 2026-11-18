"""Permanent (device auth) login, with Epic and the database stubbed: no network, never the production login."""
import base64
import time
import unittest
from unittest import mock

from fngameanalyzer import auth, config, storage


class Resp:
    def __init__(self, code=200, body=None):
        self.status_code, self._b, self.text = code, body or {}, str(body)

    def json(self):
        return self._b


def client_of(headers):
    return base64.b64decode(headers["Authorization"][6:]).decode().split(":")[0]


class DeviceLogin(unittest.TestCase):
    def setUp(self):
        self.kv, self.posts = {}, []
        self.disabled = set()          # client ids Epic answers client_disabled for
        self.approved = False
        self.p = [mock.patch.object(storage, "kv_get", lambda k: self.kv.get(k)),
                  mock.patch.object(storage, "kv_set", lambda k, v: self.kv.__setitem__(k, v)),
                  mock.patch.object(auth.config, "AUTH_FILE", mock.Mock(exists=lambda: False)),
                  mock.patch("requests.post", self.post), mock.patch("requests.get", self.get)]
        for p in self.p:
            p.start()
        auth.Session._mem.update(tok=None, exp=0, dev=False)

    def tearDown(self):
        for p in self.p:
            p.stop()

    def post(self, url, data=None, headers=None, **kw):
        self.posts.append((url, data, headers))
        if url.endswith("/oauth/token"):
            if client_of(headers) in self.disabled:
                return Resp(400, {"errorCode": "errors.com.epicgames.account.client_disabled"})
            g = data["grant_type"]
            if g == "client_credentials":
                return Resp(200, {"access_token": "cc", "expires_in": 14400})
            if g == "device_code":
                return Resp(200, {"access_token": "user-token", "account_id": "A", "expires_in": 7200}) if self.approved \
                    else Resp(400, {"errorCode": "errors.com.epicgames.account.oauth.authorization_pending"})
            if g == "device_auth":
                if self.kv.get("revoked"):
                    return Resp(400, {"errorCode": "invalid_account_credentials"})
                return Resp(200, {"access_token": "dev-%d" % len(self.posts), "expires_in": 7200, "account_id": "A"})
        if url.endswith("/oauth/deviceAuthorization"):
            return Resp(200, {"user_code": "ABCD1234", "device_code": "DC", "verification_uri_complete": "https://x/activate?userCode=ABCD1234",
                              "expires_in": 600, "interval": 10})
        if url.endswith("/deviceAuth"):
            return Resp(200, {"deviceId": "D", "secret": "S", "accountId": "A"})
        raise AssertionError(url)

    def get(self, url, **kw):
        return Resp(404 if "fnreplaysmetadata" in url else 200, {})

    def test_full_setup_skips_disabled_client(self):
        self.disabled.add(config.DEVICE_CLIENTS[0][1])   # the first client is disabled by Epic: the next one is used
        r = auth.device_start()
        self.assertEqual(r["client"], config.DEVICE_CLIENTS[1][0])
        self.assertIn("ABCD1234", r["user_code"])
        self.assertEqual(auth.device_finish(), {"pending": True})   # not approved yet
        self.approved = True
        r = auth.device_finish()
        self.assertEqual(r["account_id"], "A")
        self.assertEqual(self.kv["device"]["client"][1], config.DEVICE_CLIENTS[1][1])
        self.assertTrue(auth.status()["permanent"])
        # later logins use the same client that made the device auth
        auth.Session._mem.update(tok=None, exp=0, dev=False)
        self.kv["dev_tok"]["expires_at"] = 0
        auth.Session().bearer()
        self.assertEqual(client_of(self.posts[-1][2]), config.DEVICE_CLIENTS[1][1])

    def test_all_clients_disabled_reports_every_error(self):
        self.disabled.update(c[1] for c in config.DEVICE_CLIENTS)
        with self.assertRaises(RuntimeError) as cm:
            auth.device_start()
        self.assertIn("client_disabled", str(cm.exception))
        self.assertIn(config.DEVICE_CLIENTS[-1][0], str(cm.exception))

    def test_token_unusable_for_events_is_not_kept(self):
        auth.device_start()
        self.approved = True
        with mock.patch("requests.get", lambda u, **k: Resp(403, {})):
            with self.assertRaises(RuntimeError):
                auth.device_finish()
        self.assertNotIn("device", self.kv)

    def test_bearer_renews_by_itself_and_falls_back(self):
        self.kv["device"] = {"account_id": "A", "device_id": "D", "secret": "S", "created": time.time() - 100,
                             "client": list(config.DEVICE_CLIENTS[0])}
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
