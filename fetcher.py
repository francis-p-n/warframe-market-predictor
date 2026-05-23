"""
fetcher.py — Warframe.market API client.

Rate-limited to 2 req/s (API allows 3; we leave a buffer).
All network I/O is synchronous but staggered by a per-call sleep so the
long fetch cycles run quietly without hammering the server.
"""

import time
import logging
import random
from datetime import date
from typing import Optional

import httpx

import config
import database as db

log = logging.getLogger(__name__)

# ─── HTTP Client ───────────────────────────────────────────────────────────────

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": config.WF_API_LANGUAGE,
    "Platform": config.WF_API_PLATFORM,
}

_MIN_INTERVAL = 1.0 / config.WF_API_RATE_LIMIT   # seconds between requests
_last_request_at: float = 0.0


def _throttle() -> None:
    """Block until the minimum inter-request interval has elapsed."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    wait = _MIN_INTERVAL - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _get(path: str, retries: int = 3) -> Optional[dict]:
    """
    GET a warframe.market API path, respecting rate limits.
    Returns parsed JSON or None on persistent failure.
    """
    url = f"{config.WF_API_BASE}{path}"
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            with httpx.Client(timeout=config.WF_API_TIMEOUT, headers=_HEADERS) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                backoff = 10 * attempt
                log.warning("Rate limited by API. Backing off %ds.", backoff)
                time.sleep(backoff)
                continue
            log.warning("API %s returned HTTP %d", url, resp.status_code)
            return None
        except httpx.RequestError as exc:
            log.warning("Request error (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(2 ** attempt)   # exponential backoff
    log.error("All retries failed for %s", url)
    return None


# ─── Item List ─────────────────────────────────────────────────────────────────

def fetch_all_items() -> list[dict]:
    """
    Fetch the full tradable item list from /v1/items.
    Returns a list of {url_name, item_name} dicts.
    """
    log.info("Fetching full item list from warframe.market…")
    data = _get("/items")
    if not data:
        return []
    items = data.get("payload", {}).get("items", [])
    log.info("Received %d items from API.", len(items))
    return [
        {"url_name": i["url_name"], "item_name": i["item_name"]}
        for i in items
        if "url_name" in i and "item_name" in i
    ]


def refresh_items_cache() -> int:
    """Fetch items list and persist to DB. Returns item count."""
    items = fetch_all_items()
    if items:
        db.upsert_items_cache(items)
    return len(items)


# ─── Statistics ────────────────────────────────────────────────────────────────

def fetch_item_statistics(item_url: str) -> list[dict]:
    """
    Fetch 90-day statistics for a single item.
    Returns a list of daily stat dicts, each containing:
      datetime, volume, min_price, max_price, open_price, closed_price, avg_price, median
    """
    data = _get(f"/items/{item_url}/statistics")
    if not data:
        return []
    stats_90 = (
        data.get("payload", {})
            .get("statistics_closed", {})
            .get("90days", [])
    )
    return stats_90


def _parse_daily_stats(raw_stats: list[dict]) -> list[dict]:
    """
    Aggregate raw closed-order statistics into one record per calendar day.
    The API sometimes returns multiple intra-day records; we keep the last one.
    """
    by_day: dict[str, dict] = {}
    for entry in raw_stats:
        dt_str = entry.get("datetime", "")
        day = dt_str[:10]  # YYYY-MM-DD
        if not day:
            continue
        by_day[day] = entry   # latest entry for the day wins
    return [by_day[d] for d in sorted(by_day)]


# ─── Full Fetch Cycle ──────────────────────────────────────────────────────────

def run_fetch_cycle() -> int:
    """
    Fetch price statistics for all tracked items (watchlist + top-volume).
    Skips items that already have a snapshot for today.
    Returns the number of items successfully updated.
    """
    tracked = db.get_tracked_items()
    if not tracked:
        log.warning(
            "No items to track. Run 'python main.py --refresh-items' first."
        )
        return 0

    log.info("Starting fetch cycle for %d tracked items…", len(tracked))
    updated = 0

    for item in tracked:
        url = item["item_url"]
        name = item["item_name"]

        if db.count_snapshots_today(url):
            log.debug("Skipping %s — already have today's snapshot.", url)
            continue

        raw = fetch_item_statistics(url)
        if not raw:
            log.warning("No data for %s", url)
            continue

        daily = _parse_daily_stats(raw)
        if not daily:
            continue

        for entry in daily:
            day = entry.get("datetime", "")[:10]
            if not day:
                continue
            db.upsert_snapshot(
                item_url=url,
                item_name=name,
                snap_date=day,
                median=entry.get("median"),
                avg_price=entry.get("avg_price"),
                min_price=entry.get("min_price"),
                max_price=entry.get("max_price"),
                volume=entry.get("volume"),
            )

        updated += 1
        # Small random jitter so bursts are spread out
        time.sleep(random.uniform(0.1, 0.4))

    log.info("Fetch cycle complete. Updated %d / %d items.", updated, len(tracked))
    return updated


# ─── Top-Volume Seeding ────────────────────────────────────────────────────────

def seed_top_volume_items() -> None:
    """
    Identify the top N highest-volume items to auto-track.

    With CSV storage, get_tracked_items() already ranks items by how much
    price data exists in data/prices/ — items with more history (i.e. the
    ones we've been tracking longest and trading most) naturally sort to the
    top. This function just validates the cache is populated.
    """
    all_items = db.get_all_cached_items()
    if not all_items:
        log.warning("Items cache is empty — run --refresh-items first.")
        return

    tracked = db.get_tracked_items()
    log.info(
        "Auto-tracking %d items (top %d by data history + %d watchlist).",
        len(tracked),
        config.TOP_ITEMS_COUNT,
        len(db.get_watchlist()),
    )
