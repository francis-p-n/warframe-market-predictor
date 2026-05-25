"""
database.py — Manages CSV-based persistent storage for the Warframe Market Predictor.
Implements a 90-day rolling data limit.
"""

import csv
import logging
import os
from datetime import date, timedelta
from typing import Generator, Optional
from dateutil.parser import parse

from predictor.core import config

log = logging.getLogger(__name__)


def init_db() -> None:
    os.makedirs(config.PRICES_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config.ITEMS_CACHE_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(config.WATCHLIST_FILE), exist_ok=True)


def _load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return []


def _save_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    init_db()
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as exc:
        log.error("Failed to write %s: %s", path, exc)


# ─── Items Cache ───────────────────────────────────────────────────────────────

def get_all_cached_items() -> list[dict]:
    """Returns a list of dicts with url_name and item_name."""
    return _load_csv(config.ITEMS_CACHE_FILE)


def update_items_cache(items: list[dict]) -> None:
    _save_csv(config.ITEMS_CACHE_FILE, ["url_name", "item_name"], items)


# ─── Watchlist ─────────────────────────────────────────────────────────────────

def get_tracked_items() -> list[dict]:
    """Returns all cached items so the predictor tracks the entire market."""
    items = get_all_cached_items()
    if items:
        # Standardize key names since items cache uses 'url_name'
        return [{"item_url": i["url_name"], "item_name": i["item_name"]} for i in items]
    return _load_csv(config.WATCHLIST_FILE)

def get_watchlist() -> list[dict]:
    return _load_csv(config.WATCHLIST_FILE)

def set_tracked_items(items: list[dict]) -> None:
    _save_csv(config.WATCHLIST_FILE, ["item_url", "item_name"], items)

def add_to_watchlist(item_url: str, item_name: str) -> bool:
    items = get_watchlist()
    for i in items:
        if i["item_url"] == item_url:
            return False
    items.append({"item_url": item_url, "item_name": item_name})
    set_tracked_items(items)
    return True

def remove_from_watchlist(item_url: str) -> bool:
    items = get_watchlist()
    filtered = [i for i in items if i["item_url"] != item_url]
    if len(filtered) == len(items):
        return False
    set_tracked_items(filtered)
    return True


# ─── Prices (90-day rolling) ───────────────────────────────────────────────────

def get_snapshots(item_url: str, days: int = 90) -> list[dict]:
    """
    Get up to `days` of historical snapshots for `item_url`.
    """
    path = os.path.join(config.PRICES_DIR, f"{item_url}.csv")
    rows = _load_csv(path)
    
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    
    valid_rows = []
    for r in rows:
        try:
            # handle both ISO strings and warframe.market datetime strings
            dt_str = r["datetime"].split("T")[0] 
            if dt_str >= cutoff:
                valid_rows.append({
                    "snap_date": r["datetime"],
                    "volume":    int(float(r["volume"])),
                    "min_price": float(r["min_price"]),
                    "max_price": float(r["max_price"]),
                    "avg_price": float(r["avg_price"]),
                    "median":    float(r["median"]) if r.get("median") else None,
                })
        except Exception:
            continue
            
    # Sort chronologically just in case
    return sorted(valid_rows, key=lambda x: x["snap_date"])


def save_snapshots(item_url: str, snapshots: list[dict]) -> None:
    """
    Save snapshots for `item_url`. Automatically drops data older than 90 days.
    Input snapshots are expected to have:
      datetime, volume, min_price, max_price, avg_price, median
    """
    # 1. Load existing data
    path = os.path.join(config.PRICES_DIR, f"{item_url}.csv")
    existing_rows = _load_csv(path)
    
    # 2. Merge existing and new data (keyed by date string prefix)
    merged = {}
    for r in existing_rows:
        dt_key = r["datetime"][:10]
        merged[dt_key] = r
        
    for r in snapshots:
        dt_key = str(r["datetime"])[:10]
        merged[dt_key] = {
            "datetime": r["datetime"],
            "volume": r["volume"],
            "min_price": r["min_price"],
            "max_price": r["max_price"],
            "avg_price": r["avg_price"],
            "median": r.get("median", ""),
        }
        
    # 3. Filter to last 90 days
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    final_rows = []
    for dt_key in sorted(merged.keys()):
        if dt_key >= cutoff:
            final_rows.append(merged[dt_key])
            
    # 4. Save
    fieldnames = ["datetime", "volume", "min_price", "max_price", "avg_price", "median"]
    _save_csv(path, fieldnames, final_rows)


# ─── Statistics ────────────────────────────────────────────────────────────────

def get_storage_stats() -> dict:
    prices_count = 0
    date_min = "9999-99-99"
    date_max = "0000-00-00"
    
    if os.path.exists(config.PRICES_DIR):
        for f in os.listdir(config.PRICES_DIR):
            if not f.endswith(".csv"): continue
            rows = _load_csv(os.path.join(config.PRICES_DIR, f))
            prices_count += len(rows)
            for r in rows:
                dt_str = r["datetime"][:10]
                if dt_str < date_min: date_min = dt_str
                if dt_str > date_max: date_max = dt_str
                
    if date_min == "9999-99-99":
        date_min = "—"
        date_max = "—"
        
    watchlist = get_tracked_items()
    items = get_all_cached_items()
    
    def get_size(path):
        if not os.path.exists(path): return 0
        if os.path.isfile(path): return os.path.getsize(path)
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total += os.path.getsize(fp)
        return total
        
    total_size = get_size(config.DATA_DIR)
    
    model_path = os.path.join(config.DATA_DIR, "model.pkl")
    
    return {
        "total_rows": prices_count,
        "unique_items": len(watchlist),
        "watchlist": len(watchlist),
        "cache_items": len(items),
        "oldest_date": date_min,
        "newest_date": date_max,
        "size_kb": total_size / 1024,
        "model_trained": os.path.exists(model_path)
    }

_ensure_dirs = init_db
