"""
relic_scraper.py — Fetch Warframe relic drop tables.

Data source: drops.warframestat.us (community-maintained, sourced from
the official Warframe drop table exports. Updated by the community after
every hotfix and major patch.)

Scrape schedule:
  - Weekly refresh (CACHE_TTL_HOURS = 168) catches hotfixes and balance changes.
  - Prime Access rotates ~every 84 days, which dramatically changes which
    relic drops are valuable. The weekly refresh means we're always current
    within a week of any rotation.
  - Scheduler calls refresh_relic_cache() every Monday at midnight so the
    Tuesday morning report reflects any weekend hotfixes.

Relic tier drop probabilities (source: warframe.fandom.com/wiki/Void_Relic):
  Each relic has 3 Common slots, 2 Uncommon slots, 1 Rare slot.

  Refinement  | Common (each) | Uncommon (each) | Rare
  ------------|---------------|-----------------|------
  Intact      |  25.33%       |  11.00%         |  2.00%
  Exceptional |  23.33%       |  13.00%         |  4.00%
  Flawless    |  20.00%       |  17.00%         |  6.00%
  Radiant     |  16.67%       |  17.00%         | 10.00%
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx

from predictor.core import config

log = logging.getLogger(__name__)

RELICS_CACHE_PATH = os.path.join(config.DATA_DIR, "relics_cache.json")
DROPS_API_URL     = "https://drops.warframestat.us/data/relics.json"
CACHE_TTL_HOURS   = 168   # 1 week

# Canonical drop chances per refinement state
RELIC_PROBS: dict[str, dict[str, float]] = {
    "Intact":      {"Common": 25.33, "Uncommon": 11.00, "Rare":  2.00},
    "Exceptional": {"Common": 23.33, "Uncommon": 13.00, "Rare":  4.00},
    "Flawless":    {"Common": 20.00, "Uncommon": 17.00, "Rare":  6.00},
    "Radiant":     {"Common": 16.67, "Uncommon": 17.00, "Rare": 10.00},
}

# Best farming locations per relic tier (runner community consensus)
FARM_LOCATIONS: dict[str, list[dict]] = {
    "Lith": [
        {"node": "Hepit, Void",        "type": "Capture",       "runs_per_hour": 30, "note": "Fastest Lith farm — 2 min/run, 100% Lith drop"},
        {"node": "Olympus, Mars",      "type": "Disruption",    "runs_per_hour": 20, "note": "Good density, can AFK conduits"},
    ],
    "Meso": [
        {"node": "Io, Jupiter",        "type": "Defense",       "runs_per_hour":  7, "note": "Leave at wave 10 (rotation B). Fast and consistent."},
        {"node": "Belenus, Lua",       "type": "Defense",       "runs_per_hour":  6, "note": "Rotation B. Also good XP."},
    ],
    "Neo": [
        {"node": "Xini, Eris",         "type": "Interception",  "runs_per_hour":  4, "note": "Rotation A (4 min) and C (12 min) both drop Neo"},
        {"node": "Hydron, Sedna",      "type": "Defense",       "runs_per_hour":  5, "note": "Best XP in the game AND Neo relics. Win-win."},
    ],
    "Axi": [
        {"node": "Xini, Eris",         "type": "Interception",  "runs_per_hour":  2, "note": "Rotation C (every 3rd). Stay for 3 rotations."},
        {"node": "Mithra, Void",       "type": "Interception",  "runs_per_hour":  3, "note": "More Axi-dense than Xini if you only want Axi"},
        {"node": "Hieracon, Pluto",    "type": "Excavation",    "runs_per_hour":  4, "note": "AFK-friendly with Nekros. Every 100 cryotic = Axi"},
    ],
}


# ─── Cache Management ─────────────────────────────────────────────────────────

def _cache_is_fresh() -> bool:
    if not os.path.exists(RELICS_CACHE_PATH):
        return False
    try:
        with open(RELICS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        return (datetime.now() - fetched_at) < timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return False


def _load_cache() -> Optional[list[dict]]:
    try:
        with open(RELICS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("relics", [])
    except Exception as exc:
        log.warning("Could not read relic cache: %s", exc)
        return None


def _save_cache(relics: list[dict]) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "relic_count": len(relics),
        "relics": relics,
    }
    with open(RELICS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("Relic cache saved: %d unique relics.", len(relics))


# ─── API Fetch ────────────────────────────────────────────────────────────────

def _fetch_from_api() -> list[dict]:
    """
    Download relic data from drops.warframestat.us.
    Returns a list of consolidated relic dicts (one per tier+name, all rewards).
    """
    log.info("Fetching relic drop tables from drops.warframestat.us…")
    try:
        resp = httpx.get(DROPS_API_URL, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        raw = resp.json()
    except httpx.HTTPStatusError as exc:
        log.error("HTTP error fetching relics: %s", exc)
        return []
    except Exception as exc:
        log.error("Failed to fetch relic data: %s", exc)
        return []

    raw_list = raw.get("relics", [])
    if not raw_list:
        log.error("API returned empty relic list.")
        return []

    log.info("Received %d raw relic entries, consolidating…", len(raw_list))

    # Consolidate: the API returns one entry per (tier, name, state).
    # We keep one entry per (tier, name) using the Intact rewards as the canonical
    # drop table (rewards are the same across refinements — only chances differ).
    seen: dict[str, dict] = {}
    for entry in raw_list:
        tier  = entry.get("tier", "")
        name  = entry.get("relicName", "")
        state = entry.get("state", "Intact")
        key   = f"{tier} {name}"

        if key not in seen:
            seen[key] = {
                "tier":    tier,
                "name":    name,
                "key":     key,
                "rewards": [],
            }

        # Only pull rewards from the Intact entry (they're the same for all states)
        if state == "Intact":
            rewards = entry.get("rewards", [])
            seen[key]["rewards"] = [
                {
                    "item":   r.get("itemName", ""),
                    "rarity": r.get("rarity", "Common"),
                    "chance": r.get("chance", 0.0),
                }
                for r in rewards
            ]

    consolidated = [v for v in seen.values() if v["rewards"]]
    log.info("Consolidated to %d unique relics.", len(consolidated))
    return consolidated


# ─── Public API ───────────────────────────────────────────────────────────────

def get_relics(force: bool = False) -> list[dict]:
    """
    Return all relics with their drop tables.
    Uses cache if fresh; fetches from API otherwise.
    Each relic dict: {tier, name, key, rewards: [{item, rarity, chance}]}
    """
    if not force and _cache_is_fresh():
        cached = _load_cache()
        if cached:
            log.info("Using cached relic data (%d relics).", len(cached))
            return cached

    relics = _fetch_from_api()
    if relics:
        _save_cache(relics)
    elif (stale := _load_cache()):
        log.warning("API fetch failed — using stale cache.")
        return stale

    return relics


def refresh_relic_cache() -> int:
    """Force a fresh fetch. Returns number of relics loaded. Called by scheduler."""
    relics = _fetch_from_api()
    if relics:
        _save_cache(relics)
    return len(relics)


def cache_age_hours() -> Optional[float]:
    """Return how old the cache is in hours, or None if no cache exists."""
    if not os.path.exists(RELICS_CACHE_PATH):
        return None
    try:
        with open(RELICS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        return (datetime.now() - fetched_at).total_seconds() / 3600
    except Exception:
        return None
