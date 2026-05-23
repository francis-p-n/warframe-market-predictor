"""
config.py — Load and validate environment configuration.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Read a required env var or raise a clear error."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            "Copy .env.example to .env and fill in your values."
        )
    return val


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


# ─── Twilio ────────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID: str = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: str = _require("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM: str = _optional(
    "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
)
# Comma-separated list of WhatsApp numbers to notify (broadcast to multiple people)
# e.g. whatsapp:+601XXXXXXXXX,whatsapp:+601YYYYYYYYY
WHATSAPP_TO: list[str] = [
    n.strip()
    for n in _require("WHATSAPP_TO").split(",")
    if n.strip()
]


# ─── Schedule ──────────────────────────────────────────────────────────────────
REPORT_TIME: str = _optional("REPORT_TIME", "09:00")          # HH:MM
FETCH_INTERVAL_HOURS: int = int(_optional("FETCH_INTERVAL_HOURS", "4"))

# ─── Item Tracking ─────────────────────────────────────────────────────────────
TOP_ITEMS_COUNT: int = int(_optional("TOP_ITEMS_COUNT", "50"))
MIN_VOLUME_FILTER: int = int(_optional("MIN_VOLUME_FILTER", "5"))

# ─── Report ────────────────────────────────────────────────────────────────────
MAX_ITEMS_PER_SECTION: int = int(_optional("MAX_ITEMS_PER_SECTION", "5"))
MIN_SIGNAL_CONFIDENCE: float = float(_optional("MIN_SIGNAL_CONFIDENCE", "0.55"))

# ─── API ───────────────────────────────────────────────────────────────────────
WF_API_BASE = "https://api.warframe.market/v1"
WF_API_PLATFORM = "pc"
WF_API_LANGUAGE = "en"
WF_API_RATE_LIMIT = 2.0     # requests per second (API allows 3, we stay safe)
WF_API_TIMEOUT = 20         # seconds

# ─── Storage ───────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "warframe_prices.db")
