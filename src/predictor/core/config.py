"""
config.py — Load and validate environment configuration.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            "Copy .env.example to .env and fill in your values."
        )
    return val


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


# ─── Discord ───────────────────────────────────────────────────────────────────
# Comma-separated webhook URLs (one per channel/server you want to post to)
DISCORD_WEBHOOK_URLS: list[str] = [
    u.strip()
    for u in _require("DISCORD_WEBHOOK_URLS").split(",")
    if u.strip()
]

# ─── Schedule ──────────────────────────────────────────────────────────────────
REPORT_TIME: str          = _optional("REPORT_TIME", "09:00")
FETCH_INTERVAL_HOURS: int = int(_optional("FETCH_INTERVAL_HOURS", "4"))

# ─── Item Tracking ─────────────────────────────────────────────────────────────
TOP_ITEMS_COUNT: int  = int(_optional("TOP_ITEMS_COUNT", "50"))
MIN_VOLUME_FILTER: int = int(_optional("MIN_VOLUME_FILTER", "5"))

# ─── Report ────────────────────────────────────────────────────────────────────
MAX_ITEMS_PER_SECTION: int   = int(_optional("MAX_ITEMS_PER_SECTION", "10"))
MIN_SIGNAL_CONFIDENCE: float = float(_optional("MIN_SIGNAL_CONFIDENCE", "0.55"))

# ─── Warframe Market API ───────────────────────────────────────────────────────
WF_API_BASE     = "https://api.warframe.market/v1"   # statistics endpoint still v1
WF_API_BASE_V2  = "https://api.warframe.market/v2"   # items list moved to v2
WF_API_PLATFORM = "pc"
WF_API_LANGUAGE = "en"
WF_API_RATE_LIMIT = 2.0    # req/s (API allows 3, we stay safe)
WF_API_TIMEOUT    = 20     # seconds

# ─── Storage ───────────────────────────────────────────────────────────────────
from pathlib import Path
DATA_DIR = str(Path(__file__).parent.parent.parent.parent / "data")
DB_PATH  = os.path.join(DATA_DIR, "warframe_prices.db")

