import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-before-production")
    DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
    ROOMS_FILE = DATA_DIR / "rooms.json"
    TOURNAMENT_FILE = DATA_DIR / "tournament.json"
    LAST_SYNC_FILE = DATA_DIR / "last_sync.json"
    PROVIDER = os.environ.get("RESULTS_PROVIDER", "none").lower()
    FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    FOOTBALL_DATA_BASE_URL = os.environ.get(
        "FOOTBALL_DATA_BASE_URL", "https://api.football-data.org/v4"
    )
    FOOTBALL_DATA_COMPETITION = os.environ.get("FOOTBALL_DATA_COMPETITION", "WC")
    ADMIN_SYNC_KEY = os.environ.get("ADMIN_SYNC_KEY", "")
    SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "1800"))
