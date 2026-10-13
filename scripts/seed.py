"""Upload locally collected finished windows to the hosted site (run once).

Usage: python scripts/seed.py https://your-site.vercel.app ADMIN_KEY [REGION ...]
"""
import sys

import requests

from fngameanalyzer import storage

site, key = sys.argv[1].rstrip("/"), sys.argv[2]
regions = sys.argv[3:] or ["NAC", "BR"]
ws = [w for w in storage.windows(final=True) if w["region"] in regions and w["points"]]
print(len(ws), "windows to upload")
for w in ws:
    body = {k: w[k] for k in ("window_id", "event_id", "family", "region", "begin", "end", "meta",
                              "entrants", "points", "games", "sessions", "players")}
    for attempt in range(3):
        r = requests.post(f"{site}/api/admin/window", json=body, headers={"x-admin-key": key}, timeout=120)
        if r.status_code == 200:
            break
    print(r.status_code, w["window_id"])
