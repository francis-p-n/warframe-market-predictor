"""
database.py — CSV-based local storage.

Structure:
  data/prices/{item_url}.csv   — daily price data per item (auto-trimmed to 90 days)
  data/watchlist.csv           — user-curated items to always track
  data/items_cache.csv         — full item list from warframe.market API
"""

import csv
import logging
import os
from datetime import date, timedelta
from typing import Optional

import config

log = logging.getLogger(__name__)

# ─── Paths ─────────────────────────────────────────────────────────────────────
PRICES_DIR       = os.path.join(config.DATA_DIR, "prices")
WATCHLIST_FILE   = os.path.join(config.DATA_DIR, "watchlist.csv")
ITEMS_CACHE_FILE = os.path.join(config.DATA_DIR, "items_cache.csv")

PRICE_FIELDS     = ["date", "median", "avg_price", "min_price", "max_price", "volume"]
WATCHLIST_FIELDS = ["item_url", "item_name", "added_at"]
ITEMS_FIELDS     = ["item_url", "item_name", "updated_at"]

MAX_HISTORY_DAYS = 90


def _ensure_dirs() -> None:
    os.makedirs(PRICES_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)


def _price_file(item_url: str) -> str:
    return os.path.join(PRICES_DIR, f"{item_url}.csv")


def _cutoff(days: int = MAX_HISTORY_DAYS) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# ─── Init ──────────────────────────────────────────────────────────────────────

def init_db() -> None:
    _ensure_dirs()
    log.info("CSV storage ready at %s", config.DATA_DIR)


# ─── Price Snapshots ───────────────────────────────────────────────────────────

def upsert_snapshot(
    item_url: str,
    item_name: str,
    snap_date: str,
    median: Optional[float],
    avg_price: Optional[float],
    min_price: Optional[float],
    max_price: Optional[float],
    volume: Optional[int],
) -> None:
    """Insert or update a daily snapshot and trim to 90 days."""
    _ensure_dirs()
    fpath = _price_file(item_url)

    rows: dict[str, dict] = {}
    if os.path.exists(fpath):
        with open(fpath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[row["date"]] = row

    rows[snap_date] = {
        "date":      snap_date,
        "median":    "" if median    is None else str(median),
        "avg_price": "" if avg_price is None else str(avg_price),
        "min_price": "" if min_price is None else str(min_price),
        "max_price": "" if max_price is None else str(max_price),
        "volume":    "" if volume    is None else str(volume),
    }

    # Always enforce 90-day cap on write
    cutoff = _cutoff()
    rows = {d: r for d, r in rows.items() if d >= cutoff}

    with open(fpath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PRICE_FIELDS)
        writer.writeheader()
        for d in sorted(rows):
            writer.writerow(rows[d])


def get_snapshots(item_url: str, days: int = 90) -> list[dict]:
    """Return up to `days` snapshots oldest-first with typed numeric values."""
    fpath = _price_file(item_url)
    if not os.path.exists(fpath):
        return []

    cutoff = _cutoff(days)
    rows = []
    with open(fpath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["date"] < cutoff:
                continue
            rows.append({
                "snap_date": row["date"],
                "median":    float(row["median"])    if row["median"]    else None,
                "avg_price": float(row["avg_price"]) if row["avg_price"] else None,
                "min_price": float(row["min_price"]) if row["min_price"] else None,
                "max_price": float(row["max_price"]) if row["max_price"] else None,
                "volume":    int(row["volume"])       if row["volume"]   else None,
            })
    return sorted(rows, key=lambda r: r["snap_date"])


def count_snapshots_today(item_url: str) -> int:
    fpath = _price_file(item_url)
    if not os.path.exists(fpath):
        return 0
    today = date.today().isoformat()
    with open(fpath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["date"] == today:
                return 1
    return 0


def prune_old_snapshots(keep_days: int = 90) -> int:
    """Explicitly trim all price CSVs. Auto-trim also happens on every write."""
    _ensure_dirs()
    cutoff = _cutoff(keep_days)
    removed = 0
    if not os.path.exists(PRICES_DIR):
        return 0
    for fname in os.listdir(PRICES_DIR):
        if not fname.endswith(".csv"):
            continue
        fpath = os.path.join(PRICES_DIR, fname)
        kept, dropped = [], 0
        with open(fpath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                (kept if row["date"] >= cutoff else [None]).append(row) if row["date"] >= cutoff else None
                dropped += 0 if row["date"] >= cutoff else 1
                if row["date"] >= cutoff:
                    kept.append(row)
        if dropped:
            with open(fpath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=PRICE_FIELDS)
                writer.writeheader()
                writer.writerows(kept)
            removed += dropped
    log.info("Pruned %d old rows across price CSVs.", removed)
    return removed


# ─── Items Cache ───────────────────────────────────────────────────────────────

def upsert_items_cache(items: list[dict]) -> None:
    """Bulk-replace items cache. Items must have keys: url_name, item_name."""
    _ensure_dirs()
    today = date.today().isoformat()
    rows = [
        {"item_url": i["url_name"], "item_name": i["item_name"], "updated_at": today}
        for i in items
        if "url_name" in i and "item_name" in i
    ]
    with open(ITEMS_CACHE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ITEMS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    log.info("Items cache updated: %d items", len(rows))


def get_all_cached_items() -> list[dict]:
    if not os.path.exists(ITEMS_CACHE_FILE):
        return []
    with open(ITEMS_CACHE_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_tracked_items() -> list[dict]:
    """Union of watchlist (always included) + top-N items from cache."""
    seen: set[str] = set()
    result: list[dict] = []

    # Watchlist items always included
    for item in get_watchlist():
        key = item["item_url"]
        if key not in seen:
            seen.add(key)
            result.append({"item_url": item["item_url"], "item_name": item["item_name"]})

    # Fill remaining slots from cache — prefer items we already have data for
    price_counts = _get_price_row_counts()
    cached = get_all_cached_items()
    cached_sorted = sorted(cached, key=lambda i: price_counts.get(i["item_url"], 0), reverse=True)

    for item in cached_sorted:
        if len(result) >= config.TOP_ITEMS_COUNT:
            break
        key = item["item_url"]
        if key not in seen:
            seen.add(key)
            result.append({"item_url": item["item_url"], "item_name": item["item_name"]})

    return result


def _get_price_row_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    if not os.path.exists(PRICES_DIR):
        return counts
    for fname in os.listdir(PRICES_DIR):
        if fname.endswith(".csv"):
            fpath = os.path.join(PRICES_DIR, fname)
            try:
                with open(fpath, newline="", encoding="utf-8") as f:
                    counts[fname[:-4]] = sum(1 for _ in csv.DictReader(f))
            except Exception:
                pass
    return counts


# ─── Watchlist ─────────────────────────────────────────────────────────────────

def get_watchlist() -> list[dict]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_watchlist(rows: list[dict]) -> None:
    _ensure_dirs()
    with open(WATCHLIST_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def add_to_watchlist(item_url: str, item_name: str) -> bool:
    rows = get_watchlist()
    if any(r["item_url"] == item_url for r in rows):
        return False
    rows.append({"item_url": item_url, "item_name": item_name, "added_at": date.today().isoformat()})
    _write_watchlist(rows)
    return True


def remove_from_watchlist(item_url: str) -> bool:
    rows = get_watchlist()
    new_rows = [r for r in rows if r["item_url"] != item_url]
    if len(new_rows) == len(rows):
        return False
    _write_watchlist(new_rows)
    return True


# ─── Storage Stats ─────────────────────────────────────────────────────────────

def get_storage_stats() -> dict:
    """Return storage stats for the --status command."""
    _ensure_dirs()
    total_rows, unique_items, size_bytes = 0, 0, 0
    oldest_date = newest_date = None

    if os.path.exists(PRICES_DIR):
        for fname in os.listdir(PRICES_DIR):
            if not fname.endswith(".csv"):
                continue
            fpath = os.path.join(PRICES_DIR, fname)
            size_bytes += os.path.getsize(fpath)
            unique_items += 1
            try:
                with open(fpath, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        total_rows += 1
                        d = row.get("date", "")
                        if d:
                            if not oldest_date or d < oldest_date:
                                oldest_date = d
                            if not newest_date or d > newest_date:
                                newest_date = d
            except Exception:
                pass

    for extra in [ITEMS_CACHE_FILE, WATCHLIST_FILE]:
        if os.path.exists(extra):
            size_bytes += os.path.getsize(extra)

    model_path = os.path.join(config.DATA_DIR, "model.pkl")
    model_exists = os.path.exists(model_path)

    return {
        "total_rows":    total_rows,
        "unique_items":  unique_items,
        "watchlist":     len(get_watchlist()),
        "cache_items":   len(get_all_cached_items()),
        "oldest_date":   oldest_date or "—",
        "newest_date":   newest_date or "—",
        "size_kb":       size_bytes / 1024,
        "model_trained": model_exists,
    }
