import os
from pathlib import Path

HOME = Path(os.environ.get("FNGA_HOME", Path.home() / ".fngameanalyzer"))
HOME.mkdir(parents=True, exist_ok=True)
AUTH_FILE = HOME / "auth.json"
DB_FILE = HOME / "data.db"

ACCOUNT = "https://account-public-service-prod.ol.epicgames.com/account/api"
EVENTS = "https://events-public-service-live.ol.epicgames.com/api/v1"

# Public Fortnite PC client (well known, not a secret of the user).
CLIENT_ID = "ec684b8c687f479fadea3cb2ad83f5c6"
CLIENT_SECRET = "e1f31c211f28413186262d37a13fc84d"
LOGIN_URL = f"https://www.epicgames.com/id/api/redirect?clientId={CLIENT_ID}&responseType=code"

# family -> keywords searched (lowercase) in the event id
FAMILIES = {
    "FNCS": ["fncs"],
    "CASHCUP": ["cashcup", "cash_cup"],
}
REGIONS = ["NAC", "NAE", "NAW", "EU", "BR", "ASIA", "OCE", "ME"]
REQUEST_DELAY = 0.4  # seconds between API calls
