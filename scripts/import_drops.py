"""Push landing data for one tournament to the site: python scripts/import_drops.py landings.json
Needs the ADMIN_KEY environment variable. SITE overrides the address (default: the live site)."""
import json
import os
import sys

import requests

SITE = os.environ.get("SITE", "https://fn-game-analyzer.vercel.app").rstrip("/")
CHUNK = 5000


def main(path):
    key = os.environ.get("ADMIN_KEY")
    if not key:
        sys.exit("Set the ADMIN_KEY environment variable first.")
    body = json.load(open(path, encoding="utf-8"))
    rows = body.pop("drops")
    total = 0
    for i in range(0, len(rows), CHUNK):
        part = {**body, "drops": rows[i:i + CHUNK], "append": bool(body.get("append")) or i > 0}
        r = requests.post(f"{SITE}/api/admin/drops", json=part, headers={"x-admin-key": key}, timeout=120).json()
        if r.get("error"):
            sys.exit(f"Rejected: {r['error']}")
        total += r["stored"]
        print(f"batch {i // CHUNK + 1}: stored {r['stored']}, skipped {r['skipped']}")
    print(f"done: {total} landings for {body['window_id']}")


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) == 2 else sys.exit(__doc__)
