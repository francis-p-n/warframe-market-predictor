"""
database.py — SQLite storage for price snapshots and watchlist management.

Schema:
  price_snapshots  — historical daily price data per item
  watchlist        — user-curated items to always track
  items_cache      — full item list from warframe.market (refreshed daily)
"""

import os
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional

import config

log = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    """Return a connection with row_factory set for dict-like access."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safer concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_url    TEXT    NOT NULL,
                item_name   TEXT    NOT NULL,
                snap_date   TEXT    NOT NULL,   -- YYYY-MM-DD
                median      REAL,
                avg_price   REAL,
                min_price   REAL,
                max_price   REAL,
                volume      INTEGER,
                fetched_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(item_url, snap_date)     -- one snapshot per item per day
            );

            CREATE INDEX IF NOT EXISTS idx_snap_item_date
                ON price_snapshots(item_url, snap_date);

            CREATE TABLE IF NOT EXISTS watchlist (
                item_url    TEXT PRIMARY KEY,
                item_name   TEXT NOT NULL,
                added_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS items_cache (
                item_url    TEXT PRIMARY KEY,
                item_name   TEXT NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );
        """)
    log.info("Database initialised at %s", config.DB_PATH)


# ─── Snapshots ─────────────────────────────────────────────────────────────────

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
    """Insert or replace a daily price snapshot."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO price_snapshots
                (item_url, item_name, snap_date, median, avg_price,
                 min_price, max_price, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_url, snap_date) DO UPDATE SET
                median    = excluded.median,
                avg_price = excluded.avg_price,
                min_price = excluded.min_price,
                max_price = excluded.max_price,
                volume    = excluded.volume,
                fetched_at = datetime('now')
            """,
            (item_url, item_name, snap_date, median, avg_price,
             min_price, max_price, volume),
        )


def get_snapshots(item_url: str, days: int = 90) -> list[dict]:
    """Return up to `days` daily snapshots for an item, oldest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT snap_date, median, avg_price, min_price, max_price, volume
            FROM price_snapshots
            WHERE item_url = ?
            ORDER BY snap_date ASC
            LIMIT ?
            """,
            (item_url, days),
        ).fetchall()
    return [dict(r) for r in rows]


def get_tracked_items() -> list[dict]:
    """Return all items we should be fetching data for.

    Union of watchlist + the top-volume items stored in items_cache
    (the caller is responsible for limiting to TOP_ITEMS_COUNT after sorting).
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT item_url, item_name FROM watchlist
            UNION
            SELECT item_url, item_name FROM items_cache
            """
        ).fetchall()
    return [dict(r) for r in rows]


def count_snapshots_today(item_url: str) -> int:
    """Return 1 if we already have a snapshot for today, else 0."""
    today = date.today().isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM price_snapshots WHERE item_url=? AND snap_date=?",
            (item_url, today),
        ).fetchone()
    return row[0]


# ─── Items Cache ───────────────────────────────────────────────────────────────

def upsert_items_cache(items: list[dict]) -> None:
    """Bulk-replace the full item list (url_name, item_name pairs)."""
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO items_cache (item_url, item_name)
            VALUES (:url_name, :item_name)
            ON CONFLICT(item_url) DO UPDATE SET
                item_name  = excluded.item_name,
                updated_at = datetime('now')
            """,
            items,
        )
    log.info("Items cache updated: %d items", len(items))


def get_all_cached_items() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT item_url, item_name FROM items_cache ORDER BY item_name"
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Watchlist ─────────────────────────────────────────────────────────────────

def add_to_watchlist(item_url: str, item_name: str) -> bool:
    """Add item to watchlist. Returns True if newly added, False if already there."""
    with _get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO watchlist (item_url, item_name) VALUES (?, ?)",
                (item_url, item_name),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_from_watchlist(item_url: str) -> bool:
    """Remove item from watchlist. Returns True if it was present."""
    with _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE item_url = ?", (item_url,)
        )
        return cur.rowcount > 0


def get_watchlist() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT item_url, item_name, added_at FROM watchlist ORDER BY item_name"
        ).fetchall()
    return [dict(r) for r in rows]


def prune_old_snapshots(keep_days: int = 120) -> int:
    """Delete snapshots older than `keep_days`. Returns rows deleted."""
    cutoff = datetime.now().strftime(f"%Y-%m-%d")
    with _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM price_snapshots WHERE snap_date < date('now', ?)",
            (f"-{keep_days} days",),
        )
        return cur.rowcount
