"""
database.py — SQLite-based local storage.

Structure:
  data/warframe_prices.db  — single SQLite file (WAL mode)

Tables:
  price_snapshots  — daily OHLCV-style data per item (rolling 90-day window)
  items_cache      — full item list from warframe.market API
  watchlist        — user-curated items to always track

Public API is identical to the old CSV version so all callers are unaffected.
"""

import csv
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Generator, Optional

from predictor.core import config

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_HISTORY_DAYS = 90





# ─── Connection ───────────────────────────────────────────────────────────────

def _cutoff(days: int = MAX_HISTORY_DAYS) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """Yield a WAL-mode SQLite connection; auto-commit/rollback via context."""
    con = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


# ─── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS price_snapshots (
    item_url  TEXT NOT NULL,
    snap_date TEXT NOT NULL,
    median    REAL,
    avg_price REAL,
    min_price REAL,
    max_price REAL,
    volume    INTEGER,
    PRIMARY KEY (item_url, snap_date)
);

CREATE TABLE IF NOT EXISTS items_cache (
    item_url   TEXT PRIMARY KEY,
    item_name  TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    item_url  TEXT PRIMARY KEY,
    item_name TEXT NOT NULL,
    added_at  TEXT NOT NULL
);
"""


# ─── Init & Migration ─────────────────────────────────────────────────────────

def init_db() -> None:
    """Create schema (if needed) and migrate CSV data on first run."""
    os.makedirs(config.DATA_DIR, exist_ok=True)

    is_new = not os.path.exists(config.DB_PATH)

    with _conn() as con:
        con.executescript(_DDL)
        con.commit()

    if is_new:
        log.info("SQLite database created at %s", config.DB_PATH)
        migrate_from_csv()
    else:
        log.info("SQLite storage ready at %s", config.DB_PATH)


def migrate_from_csv() -> None:
    """
    One-time import of legacy CSV data into SQLite.

    After import the prices/ directory is renamed to prices_backup/ so it is
    preserved but no longer read by any code path.
    """
    migrated_snapshots = 0
    migrated_items = 0
    migrated_watchlist = 0

    # Legacy CSV paths — computed at call time to respect monkeypatched config in tests
    prices_dir_csv  = os.path.join(config.DATA_DIR, "prices")
    watchlist_csv   = os.path.join(config.DATA_DIR, "watchlist.csv")
    items_cache_csv = os.path.join(config.DATA_DIR, "items_cache.csv")

    if os.path.isdir(prices_dir_csv):
        log.info("Migrating legacy CSV price data from %s …", prices_dir_csv)
        cutoff = _cutoff()
        with _conn() as con:
            for fname in os.listdir(prices_dir_csv):
                if not fname.endswith(".csv"):
                    continue
                item_url = fname[:-4]
                fpath = os.path.join(prices_dir_csv, fname)
                try:
                    with open(fpath, newline="", encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            snap_date = row.get("date", "")
                            if not snap_date or snap_date < cutoff:
                                continue
                            con.execute(
                                """
                                INSERT OR REPLACE INTO price_snapshots
                                    (item_url, snap_date, median, avg_price,
                                     min_price, max_price, volume)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    item_url,
                                    snap_date,
                                    float(row["median"])    if row.get("median")    else None,
                                    float(row["avg_price"]) if row.get("avg_price") else None,
                                    float(row["min_price"]) if row.get("min_price") else None,
                                    float(row["max_price"]) if row.get("max_price") else None,
                                    int(row["volume"])       if row.get("volume")   else None,
                                ),
                            )
                            migrated_snapshots += 1
                except Exception as exc:
                    log.warning("Could not migrate %s: %s", fpath, exc)
            con.commit()

        # Rename prices/ → prices_backup/ to avoid future confusion
        backup_dir = prices_dir_csv + "_backup"
        try:
            os.rename(prices_dir_csv, backup_dir)
            log.info("Renamed prices/ → prices_backup/ (CSV data preserved).")
        except OSError as exc:
            log.warning("Could not rename prices/ directory: %s", exc)

    # ── Items cache CSV ───────────────────────────────────────────────────────
    if os.path.isfile(items_cache_csv):
        log.info("Migrating legacy items_cache.csv …")
        with _conn() as con, open(items_cache_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("item_url") and row.get("item_name"):
                    con.execute(
                        "INSERT OR IGNORE INTO items_cache (item_url, item_name, updated_at) VALUES (?, ?, ?)",
                        (row["item_url"], row["item_name"], row.get("updated_at", date.today().isoformat())),
                    )
                    migrated_items += 1
            con.commit()

    # ── Watchlist CSV ─────────────────────────────────────────────────────────
    if os.path.isfile(watchlist_csv):
        log.info("Migrating legacy watchlist.csv …")
        with _conn() as con, open(watchlist_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("item_url") and row.get("item_name"):
                    con.execute(
                        "INSERT OR IGNORE INTO watchlist (item_url, item_name, added_at) VALUES (?, ?, ?)",
                        (row["item_url"], row["item_name"], row.get("added_at", date.today().isoformat())),
                    )
                    migrated_watchlist += 1
            con.commit()

    if migrated_snapshots or migrated_items or migrated_watchlist:
        log.info(
            "Migration complete: %d snapshots, %d items, %d watchlist entries.",
            migrated_snapshots, migrated_items, migrated_watchlist,
        )
    else:
        log.info("No legacy CSV data found — starting fresh.")


# ─── Price Snapshots ──────────────────────────────────────────────────────────

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
    """Insert or replace a daily snapshot, then enforce the 90-day window."""
    with _conn() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO price_snapshots
                (item_url, snap_date, median, avg_price, min_price, max_price, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_url, snap_date, median, avg_price, min_price, max_price, volume),
        )
        # Enforce rolling 90-day window on every write
        con.execute(
            "DELETE FROM price_snapshots WHERE item_url = ? AND snap_date < ?",
            (item_url, _cutoff()),
        )
        con.commit()


def get_snapshots(item_url: str, days: int = 90) -> list[dict]:
    """Return up to `days` snapshots for an item, oldest-first."""
    cutoff = _cutoff(days)
    with _conn() as con:
        rows = con.execute(
            """
            SELECT snap_date, median, avg_price, min_price, max_price, volume
            FROM price_snapshots
            WHERE item_url = ? AND snap_date >= ?
            ORDER BY snap_date ASC
            """,
            (item_url, cutoff),
        ).fetchall()
    return [
        {
            "snap_date": r["snap_date"],
            "median":    r["median"],
            "avg_price": r["avg_price"],
            "min_price": r["min_price"],
            "max_price": r["max_price"],
            "volume":    r["volume"],
        }
        for r in rows
    ]


def count_snapshots_today(item_url: str) -> int:
    """Return 1 if a snapshot already exists for today, else 0."""
    today = date.today().isoformat()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM price_snapshots WHERE item_url = ? AND snap_date = ?",
            (item_url, today),
        ).fetchone()
    return row[0] if row else 0


def prune_old_snapshots(keep_days: int = MAX_HISTORY_DAYS) -> int:
    """Delete all snapshots older than `keep_days`. Returns rows removed."""
    cutoff = _cutoff(keep_days)
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM price_snapshots WHERE snap_date < ?",
            (cutoff,),
        )
        con.commit()
    removed = cur.rowcount
    log.info("Pruned %d old snapshot rows (cutoff: %s).", removed, cutoff)
    return removed


# ─── Items Cache ──────────────────────────────────────────────────────────────

def upsert_items_cache(items: list[dict]) -> None:
    """Bulk-replace items cache. Items must have keys: url_name, item_name."""
    today = date.today().isoformat()
    rows = [
        (i["url_name"], i["item_name"], today)
        for i in items
        if "url_name" in i and "item_name" in i
    ]
    with _conn() as con:
        con.execute("DELETE FROM items_cache")
        con.executemany(
            "INSERT INTO items_cache (item_url, item_name, updated_at) VALUES (?, ?, ?)",
            rows,
        )
        con.commit()
    log.info("Items cache updated: %d items", len(rows))


def get_all_cached_items() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT item_url, item_name, updated_at FROM items_cache ORDER BY item_name"
        ).fetchall()
    return [dict(r) for r in rows]


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

    # Fill remaining slots — prefer items with more accumulated history
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
    """Return a mapping of item_url → number of stored snapshots."""
    with _conn() as con:
        rows = con.execute(
            "SELECT item_url, COUNT(*) AS cnt FROM price_snapshots GROUP BY item_url"
        ).fetchall()
    return {r["item_url"]: r["cnt"] for r in rows}


# ─── Watchlist ────────────────────────────────────────────────────────────────

def get_watchlist() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT item_url, item_name, added_at FROM watchlist ORDER BY added_at"
        ).fetchall()
    return [dict(r) for r in rows]


def add_to_watchlist(item_url: str, item_name: str) -> bool:
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO watchlist (item_url, item_name, added_at) VALUES (?, ?, ?)",
                (item_url, item_name, date.today().isoformat()),
            )
            con.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # already exists (PRIMARY KEY conflict)


def remove_from_watchlist(item_url: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM watchlist WHERE item_url = ?", (item_url,))
        con.commit()
    return cur.rowcount > 0


# ─── Storage Stats ────────────────────────────────────────────────────────────

def get_storage_stats() -> dict:
    """Return storage stats for the --status command."""
    with _conn() as con:
        snap_row = con.execute(
            "SELECT COUNT(*) AS total, COUNT(DISTINCT item_url) AS items, "
            "MIN(snap_date) AS oldest, MAX(snap_date) AS newest "
            "FROM price_snapshots"
        ).fetchone()

        cache_count = con.execute("SELECT COUNT(*) FROM items_cache").fetchone()[0]
        watchlist_count = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]

    total_rows   = snap_row["total"]   if snap_row else 0
    unique_items = snap_row["items"]   if snap_row else 0
    oldest_date  = snap_row["oldest"]  if snap_row and snap_row["oldest"] else "—"
    newest_date  = snap_row["newest"]  if snap_row and snap_row["newest"] else "—"

    size_bytes = os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0
    model_path = os.path.join(config.DATA_DIR, "model.pkl")

    return {
        "total_rows":    total_rows,
        "unique_items":  unique_items,
        "watchlist":     watchlist_count,
        "cache_items":   cache_count,
        "oldest_date":   oldest_date,
        "newest_date":   newest_date,
        "size_kb":       size_bytes / 1024,
        "model_trained": os.path.exists(model_path),
    }
