"""
main.py — Entry point for the Warframe Market Predictor background service.

Usage:
  python main.py                          Run the background service
  python main.py --test-notify            Send a test Discord message and exit
  python main.py --run-report             Run analysis + send report now
  python main.py --fetch-now              Trigger one price fetch cycle
  python main.py --refresh-items          Re-download full item list
  python main.py --refresh-relics         Re-download relic drop tables
  python main.py --relics                 Show top relics to farm right now
  python main.py --watchlist              Show your current watchlist
  python main.py --watchlist-add NAME     Add an item to watchlist
  python main.py --watchlist-remove NAME  Remove an item from watchlist
  python main.py --search QUERY           Search available items
  python main.py --retrain                Force SVM model retrain
  python main.py --status                 Show storage stats and schedule
"""

import argparse
import logging
import os
import sys

# ─── Logging ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "data", "predictor.log"),
            encoding="utf-8",
            delay=True,
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
    g.add_argument("--test-notify",       action="store_true", help="Send a test Discord message")
    g.add_argument("--run-report",        action="store_true", help="Run analysis + send report now")
    g.add_argument("--fetch-now",         action="store_true", help="Trigger one price fetch cycle")
    g.add_argument("--refresh-items",     action="store_true", help="Re-download full item list")
    g.add_argument("--refresh-relics",    action="store_true", help="Re-download relic drop tables")
    g.add_argument("--relics",            action="store_true", help="Show top relics to farm")
    g.add_argument("--watchlist",         action="store_true", help="Show your watchlist")
    g.add_argument("--watchlist-add",     metavar="NAME",      help="Add item to watchlist")
    g.add_argument("--watchlist-remove",  metavar="NAME",      help="Remove item from watchlist")
    g.add_argument("--search",            metavar="QUERY",     help="Search items by name")
    g.add_argument("--retrain",           action="store_true", help="Force SVM model retrain")
    g.add_argument("--status",            action="store_true", help="Show storage stats")
    return p


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_test_notify():
    from notifier import send_test_message
    ok = send_test_message()
    print("✅ Test message sent to Discord!" if ok else "❌ Failed — check DISCORD_WEBHOOK_URLS in .env")
    sys.exit(0 if ok else 1)


def cmd_run_report():
    from analyzer import run_analysis
    from notifier import send_daily_report
    report = run_analysis()
    print(f"Analysis: {len(report.buys)} buys, {len(report.sells)} sells, "
          f"{len(report.holds)} holds from {report.total_scanned} items "
          f"[{report.model_used}]")
    ok = send_daily_report(report)
    sys.exit(0 if ok else 1)


def cmd_fetch_now():
    from fetcher import run_fetch_cycle
    count = run_fetch_cycle()
    print(f"✅ Fetched data for {count} items.")
    sys.exit(0)


def cmd_refresh_items():
    from fetcher import refresh_items_cache
    count = refresh_items_cache()
    print(f"✅ Items cache updated: {count} items.")
    sys.exit(0)


def cmd_refresh_relics():
    from relic_scraper import refresh_relic_cache
    count = refresh_relic_cache()
    print(f"✅ Relic drop tables updated: {count} relics.")
    sys.exit(0)


def cmd_relics():
    from relic_analyzer import get_top_relics
    from relic_scraper import cache_age_hours
    recs = get_top_relics(n=10)
    age  = cache_age_hours()
    age_str = f"{age:.0f}h ago" if age is not None else "never"
    print(f"\n⚙️  Top Relics to Farm  (cache: {age_str})\n{'─' * 80}")
    if not recs:
        print("  No relic data. Run: python main.py --refresh-relics")
        sys.exit(0)
    for i, rec in enumerate(recs, 1):
        farm = rec.farm_location
        print(f"\n  #{i}  {rec.full_name}")
        print(f"      EV: ~{rec.ev_intact:.1f}p/run (Intact)  ~{rec.ev_radiant:.1f}p/run (Radiant)")
        print(f"      Est: ~{rec.plat_per_hour_intact:.0f}p/hr  |  Farm: {farm['node']} ({farm['type']})")
        print(f"      {farm['note']}")
        for r in sorted(rec.rewards, key=lambda x: x.price, reverse=True)[:3]:
            if r.price > 0:
                star = "⭐" if r.rarity == "Rare" else "◈ " if r.rarity == "Uncommon" else "· "
                print(f"      {star} {r.item}  →  {r.price:.0f}p  ({r.chance_pct:.1f}% chance)")
        print(f"      → {rec.recommendation}")
    print()
    sys.exit(0)


def cmd_watchlist():
    import watchlist
    watchlist.print_watchlist()
    sys.exit(0)


def cmd_watchlist_add(name: str):
    import watchlist
    result = watchlist.add_item(name)
    print(f"✅ '{result}' added to watchlist." if result else
          f"❌ Could not find '{name}'. Try --search first.")
    sys.exit(0 if result else 1)


def cmd_watchlist_remove(name: str):
    import watchlist
    result = watchlist.remove_item(name)
    print(f"✅ '{result}' removed from watchlist." if result else
          f"❌ '{name}' not found in watchlist.")
    sys.exit(0 if result else 1)


def cmd_search(query: str):
    import watchlist
    watchlist.print_search_results(query)
    sys.exit(0)


def cmd_retrain():
    from analyzer import retrain
    ok = retrain()
    print("✅ Model retrained successfully." if ok else
          "⚠️  Not enough data to train yet — keep the service running to collect more.")
    sys.exit(0 if ok else 1)


def cmd_status():
    import config
    import database as db
    from relic_scraper import cache_age_hours

    stats   = db.get_storage_stats()
    relic_h = cache_age_hours()
    relic_age = f"{relic_h:.0f}h ago" if relic_h is not None else "never (run --refresh-relics)"

    print("\n📊 Warframe Market Predictor — Status")
    print("─" * 50)
    print(f"  Price snapshots  : {stats['total_rows']:,} rows")
    print(f"  Unique items     : {stats['unique_items']:,}")
    print(f"  Watchlist        : {stats['watchlist']} items")
    print(f"  Items cache      : {stats['cache_items']:,} items")
    print(f"  Data range       : {stats['oldest_date']} → {stats['newest_date']}")
    print(f"  Storage size     : {stats['size_kb']:.1f} KB")
    print(f"  SVM model        : {'trained ✅' if stats['model_trained'] else 'not yet trained (collecting data…)'}")
    print(f"  Relic cache      : {relic_age}")
    print(f"  Report time      : {config.REPORT_TIME} daily")
    print(f"  Fetch interval   : every {config.FETCH_INTERVAL_HOURS}h")
    print()
    sys.exit(0)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = _build_parser().parse_args()

    import database as db
    db.init_db()

    if args.test_notify:       cmd_test_notify()
    elif args.run_report:      cmd_run_report()
    elif args.fetch_now:       cmd_fetch_now()
    elif args.refresh_items:   cmd_refresh_items()
    elif args.refresh_relics:  cmd_refresh_relics()
    elif args.relics:          cmd_relics()
    elif args.watchlist:       cmd_watchlist()
    elif args.watchlist_add:   cmd_watchlist_add(args.watchlist_add)
    elif args.watchlist_remove: cmd_watchlist_remove(args.watchlist_remove)
    elif args.search:          cmd_search(args.search)
    elif args.retrain:         cmd_retrain()
    elif args.status:          cmd_status()
    else:
        # ── Background service ────────────────────────────────────────────────
        import config
        log.info("=" * 60)
        log.info("  Warframe Market Predictor starting")
        log.info("  Report time    : %s daily", config.REPORT_TIME)
        log.info("  Fetch interval : every %dh", config.FETCH_INTERVAL_HOURS)
        log.info("  Tracking       : top %d items + watchlist", config.TOP_ITEMS_COUNT)
        log.info("=" * 60)

        # Bootstrap item list on first run
        if not db.get_all_cached_items():
            log.info("First run — fetching item list…")
            from fetcher import refresh_items_cache
            refresh_items_cache()

        # Bootstrap relic data on first run
        from relic_scraper import cache_age_hours, refresh_relic_cache
        if cache_age_hours() is None:
            log.info("First run — fetching relic drop tables…")
            refresh_relic_cache()

        try:
            import scheduler
            scheduler.start(run_fetch_immediately=True)
        except (KeyboardInterrupt, SystemExit):
            log.info("Predictor stopped.")


if __name__ == "__main__":
    main()
