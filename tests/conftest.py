"""tests/conftest.py — Shared fixtures and test configuration."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Add project root to sys.path ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Environment mock (avoids needing a real .env) ────────────────────────────
@pytest.fixture(autouse=True)
def mock_env(tmp_path, monkeypatch):
    """Patch all required env vars and redirect data dir to a temp directory."""
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", "https://discord.com/api/webhooks/0/test")
    monkeypatch.setenv("REPORT_TIME", "09:00")
    monkeypatch.setenv("FETCH_INTERVAL_HOURS", "4")
    monkeypatch.setenv("TOP_ITEMS_COUNT", "10")
    monkeypatch.setenv("MIN_VOLUME_FILTER", "5")
    monkeypatch.setenv("MAX_ITEMS_PER_SECTION", "10")
    monkeypatch.setenv("MIN_SIGNAL_CONFIDENCE", "0.55")

    # Redirect DATA_DIR to a temporary directory so tests don't touch real data
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)

    # Reload config with patched env
    import importlib
    import config
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "data" / "test.db"))

    import database
    monkeypatch.setattr(database, "PRICES_DIR",       str(tmp_path / "data" / "prices"))
    monkeypatch.setattr(database, "WATCHLIST_FILE",   str(tmp_path / "data" / "watchlist.csv"))
    monkeypatch.setattr(database, "ITEMS_CACHE_FILE", str(tmp_path / "data" / "items_cache.csv"))

    database.init_db()
    return tmp_path
