"""
main.py — Entry point for the Warframe Market Predictor background service.

Usage:
  python main.py                        Run the full background service
  python main.py --test-notify          Send a test WhatsApp message and exit
  python main.py --run-report           Run analysis + send report now, then exit
  python main.py --fetch-now            Trigger one fetch cycle now, then exit
  python main.py --refresh-items        Re-download full item list, then exit
  python main.py --watchlist            Show your current watchlist
  python main.py --watchlist-add NAME   Add an item to your watchlist
  python main.py --watchlist-remove N   Remove an item from your watchlist
  python main.py --search QUERY         Search available items by name
  python main.py --status               Show DB stats and next scheduled runs
"""

import argparse
import logging
import sys
import os
from datetime import datetime

# ─── Logging setup (before any imports that log at module level) ───────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "data", "predictor.log"),
            encoding="utf-8",
            delay=True,   # don't open the file until the first log line
        ),
    ],
)

log = logging.getLogger("main")


# ─── Argument Parser ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Warframe Market Predictor — background price-analysis service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--test-notify",      action="store_true",
                   help="Send a test WhatsApp message and exit")
    g.add_argument("--run-report",       action="store_true",
                   help="Run analysis + send report now, then exit")
    g.add_argument("--fetch-now",        action="store_true",
                   help="Trigger one fetch cycle now, then exit")
    g.add_argument("--refresh-items",    action="store_true",
                   help="Re-download full item list from warframe.market, then exit")
    g.add_argument("--watchlist",        action="store_true",
                   help="Display your current watchlist")
    g.add_argument("--watchlist-add",    metavar="NAME",
                   help="Add an item to your watchlist (fuzzy search)")
    g.add_argument("--watchlist-remove", metavar="NAME",
                   help="Remove an item from your watchlist")
    g.add_argument("--search",           metavar="QUERY",
                   help="Search available items by name")
    g.add_argument("--status",           action="store_true",
                   help="Show database statistics")
    return p


# ─── One-shot Commands ────────────────────────────────────────────────────────

def cmd_test_notify():
    from notifier import send_test_message
    log.info("Sending test WhatsApp message…")
    ok = send_test_message()
    if ok:
        print("✅ Test message sent! Check your WhatsApp.")
    else:
        print("❌ Failed to send. Check your Twilio credentials in .env")
    sys.exit(0 if ok else 1)


def cmd_run_report():
    from analyzer import run_analysis
    from notifier import send_daily_report
    log.info("Running manual report…")
    report = run_analysis()
    print(f"Analysis: {len(report.buys)} buys, {len(report.sells)} sells, "
          f"{len(report.holds)} holds from {report.total_scanned} items.")
    ok = send_daily_report(report)
    sys.exit(0 if ok else 1)


def cmd_fetch_now():
    from fetcher import run_fetch_cycle
    log.info("Running manual fetch cycle…")
    count = run_fetch_cycle()
    print(f"✅ Fetched data for {count} items.")
    sys.exit(0)


def cmd_refresh_items():
    from fetcher import refresh_items_cache
    log.info("Refreshing items cache…")
    count = refresh_items_cache()
    print(f"✅ Items cache updated: {count} items.")
    sys.exit(0)


def cmd_watchlist():
    import watchlist
    watchlist.print_watchlist()
    sys.exit(0)


def cmd_watchlist_add(name: str):
    import watchlist
    result = watchlist.add_item(name)
    if result:
        print(f"✅ '{result}' added to watchlist.")
    else:
        print(f"❌ Could not find '{name}'. Try --search to find the correct name.")
    sys.exit(0 if result else 1)


def cmd_watchlist_remove(name: str):
    import watchlist
    result = watchlist.remove_item(name)
    if result:
        print(f"✅ '{result}' removed from watchlist.")
    else:
        print(f"❌ '{name}' not found in watchlist.")
    sys.exit(0 if result else 1)


def cmd_search(query: str):
    import watchlist
    watchlist.print_search_results(query)
    sys.exit(0)


def cmd_status():
    import sqlite3
    import config

    if not os.path.exists(config.DB_PATH):
        print("No database found. Run the service first to start collecting data.")
        sys.exit(0)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    total_snaps = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    total_items = conn.execute("SELECT COUNT(DISTINCT item_url) FROM price_snapshots").fetchone()[0]
    wl_count    = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    cache_count = conn.execute("SELECT COUNT(*) FROM items_cache").fetchone()[0]
    oldest      = conn.execute("SELECT MIN(snap_date) FROM price_snapshots").fetchone()[0]
    newest      = conn.execute("SELECT MAX(snap_date) FROM price_snapshots").fetchone()[0]
    conn.close()

    print("\n📊 Warframe Market Predictor — Status")
    print("─" * 45)
    print(f"  Snapshots stored : {total_snaps:,}")
    print(f"  Unique items     : {total_items:,}")
    print(f"  Watchlist items  : {wl_count}")
    print(f"  Items cache      : {cache_count:,}")
    print(f"  Data range       : {oldest} → {newest}")
    print(f"  DB size          : {os.path.getsize(config.DB_PATH) / 1024:.1f} KB")
    print(f"  Report time      : {config.REPORT_TIME} daily")
    print(f"  Fetch interval   : every {config.FETCH_INTERVAL_HOURS}h")
    print()
    sys.exit(0)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = _build_parser().parse_args()

    # Ensure data directory and DB exist before anything else
    import database as db
    db.init_db()

    # Route one-shot commands
    if args.test_notify:
        cmd_test_notify()
    elif args.run_report:
        cmd_run_report()
    elif args.fetch_now:
        cmd_fetch_now()
    elif args.refresh_items:
        cmd_refresh_items()
    elif args.watchlist:
        cmd_watchlist()
    elif args.watchlist_add:
        cmd_watchlist_add(args.watchlist_add)
    elif args.watchlist_remove:
        cmd_watchlist_remove(args.watchlist_remove)
    elif args.search:
        cmd_search(args.search)
    elif args.status:
        cmd_status()
    else:
        # ── Normal mode: start background service ─────────────────────────────
        log.info("=" * 60)
        log.info("  Warframe Market Predictor starting up")
        log.info("  Report time  : %s daily", config.REPORT_TIME)
        log.info("  Fetch every  : %dh", config.FETCH_INTERVAL_HOURS)
        log.info("  Top items    : %d (auto) + watchlist", config.TOP_ITEMS_COUNT)
        log.info("  Notify to    : %s", config.WHATSAPP_TO)
        log.info("=" * 60)

        # Seed item list on first run
        import config as cfg
        if not os.path.exists(cfg.DB_PATH) or _db_is_empty():
            log.info("First run detected — fetching item list before starting…")
            from fetcher import refresh_items_cache
            refresh_items_cache()

        # Start the blocking scheduler (never returns until Ctrl+C)
        try:
            import scheduler
            scheduler.start(run_fetch_immediately=True)
        except (KeyboardInterrupt, SystemExit):
            log.info("Predictor stopped.")


def _db_is_empty() -> bool:
    """Return True if items_cache table has no rows."""
    import sqlite3
    import config
    if not os.path.exists(config.DB_PATH):
        return True
    try:
        conn = sqlite3.connect(config.DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM items_cache").fetchone()[0]
        conn.close()
        return count == 0
    except Exception:
        return True


if __name__ == "__main__":
    main()
