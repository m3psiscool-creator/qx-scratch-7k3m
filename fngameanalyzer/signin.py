"""Site sign-in: Google (ID token checked with Google) or the owner key. The site issues its own signed session token.

Setup: create a Google OAuth client (type "Web application"), add the site's address as an authorized JavaScript origin,
and set the Vercel env var GOOGLE_CLIENT_ID. Nothing else is needed (no client secret: the ID token is checked with Google)."""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from . import storage

SESSION_DAYS = 30


def google_client_id():
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _secret():
    s = os.environ.get("SESSION_SECRET") or (os.environ.get("ADMIN_KEY_OWNER", "") + "|" + os.environ.get("ADMIN_KEY", "") + "|" + os.environ.get("CRON_SECRET", ""))
    return hashlib.sha256(("fnlab-session|" + s).encode()).digest()


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(user):
    payload = {**user, "exp": int(time.time()) + SESSION_DAYS * 86400}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def verify(token):
    """token -> user dict, or None."""
    try:
        body, sig = str(token or "").split(".", 1)
        want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        p = json.loads(_unb64(body))
        return p if p.get("exp", 0) > time.time() else None
    except Exception:
        return None


def google_user(credential):
    """Check a Google ID token with Google; returns the user or raises ValueError."""
    cid = google_client_id()
    if not cid:
        raise ValueError("Google sign-in is not set up yet.")
    url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(str(credential or ""), safe="")
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            t = json.loads(r.read().decode())
    except Exception:
        raise ValueError("Google did not accept that sign-in. Try again.")
    if t.get("aud") != cid or str(t.get("email_verified")).lower() != "true" or int(t.get("exp", 0)) < time.time():
        raise ValueError("That Google sign-in is not valid for this site.")
    return {"sub": t["sub"], "email": t.get("email", ""), "name": t.get("name") or t.get("email", "").split("@")[0], "first": t.get("given_name") or "", "picture": t.get("picture", ""), "via": "google"}


def record(user):
    """Remember who signed in (shown to the owner on /admin)."""
    try:
        users = storage.kv_get("users") or {}
        u = users.get(user["sub"]) or {"first_seen": int(time.time())}
        u.update(email=user.get("email", ""), name=user.get("name", ""), last_seen=int(time.time()), via=user.get("via", ""))
        users[user["sub"]] = u
        storage.kv_set("users", users)
    except Exception:
        pass   # a sign-in must not fail because the database is busy
