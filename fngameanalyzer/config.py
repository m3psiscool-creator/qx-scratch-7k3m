import os
from pathlib import Path

HOME = Path(os.environ.get("FNGA_HOME", Path.home() / ".fngameanalyzer"))
try:
    HOME.mkdir(parents=True, exist_ok=True)
except OSError:  # read-only filesystem (hosted)
    pass
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
# Epic's own tournamentType -> our family. Anything else (Ranked, Victory, Workshop...) is ignored.
TOURNAMENT_TYPES = {"CashCup": "CASHCUP", "FNCS": "FNCS", "ShopCup": "SKINCUP", "VictoryCup": "VICTORYCUP", "WorkshopCup": "WORKSHOP"}   # WorkshopCup = Epic's Performance Evaluation cups
REGIONS =["NAC", "NAE", "NAW", "EU", "BR", "ASIA", "OCE", "ME"]
# Teams per lobby by (game type, mode). None = unknown (Reload solo is 24 or 40): the model then
# uses the highest placement seen in past games of the same playlist.
LOBBY = {
    ("br", "solo"): 100, ("br", "duos"): 50, ("br", "trios"): 33, ("br", "squads"): 25,
    ("reload", "solo"): None, ("reload", "duos"): 20, ("reload", "squads"): 10,
}
RELOAD_WORDS = ["reload", "_re_", "blastberry", "dashberry", "punchberry", "piperboot",
                "sourspawn", "jumpbear"]
# Games must START before a window ends but can finish up to ~22 min later and still count.
POST_END_GRACE = 22 * 60       # shown as "games finishing"
FINALIZE_AFTER = 25 * 60       # keep polling this long after the end, then store the final board
REQUEST_DELAY =float(os.environ.get("FNGA_DELAY", "0.4"))  # seconds between API calls
# Regions the hosted collector tracks (comma separated Epic region codes in event ids).
ALL_REGIONS = ["NAC", "NAW", "EU", "BR", "ASIA", "ME", "OCE"]
TRACKED_REGIONS = [r for r in os.environ.get("FNGA_REGIONS", ",".join(ALL_REGIONS)).split(",") if r]
# region parameter of Epic's event download call (NAE returns both NAC and NAW events)
DOWNLOAD_REGIONS = ["NAC", "NAW", "NAE", "EU", "BR", "ASIA", "ME", "OCE"]

# Points are stored at these ranks for every event (Epic lists at most 10,000 places).
DEEP_RANKS = [1000] + list(range(1500, 10001, 500))
SERIES_RANKS = [1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100, 150, 200, 250, 300, 400,
                500, 750] + DEEP_RANKS
