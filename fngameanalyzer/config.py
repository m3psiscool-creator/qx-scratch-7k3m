import os
from pathlib import Path

HOME = Path(os.environ.get("FNGA_HOME", Path.home() / ".fngameanalyzer"))
HOME.mkdir(parents=True, exist_ok=True)
AUTH_FILE = HOME / "auth.json"
DB_FILE = HOME / "data.db"

ACCOUNT = "https://account-public-service-prod.ol.epicgames.com/account/api"
EVENTS = "https://events-public-service-live.ol.epicgames.com/api/v1"

# Public Fortnite PC client (well known, not a secret of the user).
CLIENT_ID = "3446cd72694c4a4485d81b77adbb2141"  # iOS client; allowed to create device auth
CLIENT_SECRET = "9209d4a5e25a457fb9b07489d313b41a"
LOGIN_URL = f"https://www.epicgames.com/id/api/redirect?clientId={CLIENT_ID}&responseType=code"

# family -> keywords searched (lowercase) in the event id
FAMILIES = {
    "FNCS": ["fncs"],
    "CASHCUP": ["cashcup", "cash_cup"],
}
REGIONS = ["NAC", "NAW", "EU", "BR", "ASIA", "OCE", "ME"]
REQUEST_DELAY = 0.4  # seconds between API calls
