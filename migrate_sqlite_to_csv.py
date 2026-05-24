import os
import sqlite3
import csv
from pathlib import Path

# Setup paths
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "warframe_prices.db"
PRICES_DIR = DATA_DIR / "prices"
ITEMS_CACHE = DATA_DIR / "items_cache.csv"
WATCHLIST_FILE = DATA_DIR / "watchlist.csv"

def migrate():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH}")
        return
        
    print("Migrating SQLite back to CSVs...")
    PRICES_DIR.mkdir(exist_ok=True, parents=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. Export Items Cache
    print("Exporting items cache...")
    cur.execute("SELECT item_url, item_name FROM items_cache")
    items = cur.fetchall()
    with open(ITEMS_CACHE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url_name", "item_name"])
        for item in items:
            writer.writerow([item["item_url"], item["item_name"]])
            
    # 2. Export Watchlist
    print("Exporting watchlist...")
    cur.execute("SELECT item_url, item_name FROM watchlist")
    watchlist = cur.fetchall()
    with open(WATCHLIST_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item_url", "item_name"])
        for w in watchlist:
            writer.writerow([w["item_url"], w["item_name"]])
            
    # 3. Export Prices
    print("Exporting prices...")
    cur.execute("SELECT DISTINCT item_url FROM price_snapshots")
    url_names = [row["item_url"] for row in cur.fetchall()]
    
    for url in url_names:
        cur.execute(
            "SELECT snap_date, volume, min_price, max_price, avg_price, median "
            "FROM price_snapshots WHERE item_url = ? ORDER BY snap_date ASC", (url,)
        )
        snaps = cur.fetchall()
        
        csv_path = PRICES_DIR / f"{url}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "volume", "min_price", "max_price", "avg_price", "median"])
            for s in snaps:
                writer.writerow([s["snap_date"], s["volume"], s["min_price"], s["max_price"], s["avg_price"], s["median"]])
                
    conn.close()
    print("Migration complete. Renaming database to prevent accidental reuse.")
    os.rename(DB_PATH, DB_PATH.with_suffix(".db.backup"))
    
if __name__ == "__main__":
    migrate()
