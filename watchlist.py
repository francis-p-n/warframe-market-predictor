"""
watchlist.py — CLI helpers for managing your custom item watchlist.

Called from main.py when the user passes --watchlist-add or --watchlist-remove.
Also provides a search helper to find valid item URLs from partial names.
"""

import logging
from typing import Optional

import database as db

log = logging.getLogger(__name__)


def search_items(query: str) -> list[dict]:
    """
    Search the local items cache for items matching `query` (case-insensitive).
    Returns a list of {item_url, item_name} dicts.
    """
    query_lower = query.lower()
    all_items = db.get_all_cached_items()
    return [
        i for i in all_items
        if query_lower in i["item_name"].lower()
           or query_lower in i["item_url"].lower()
    ]


def add_item(query: str) -> Optional[str]:
    """
    Find the best match for `query` in the items cache and add it to watchlist.
    Returns the item name on success, None on failure.

    If multiple matches exist, adds the best (shortest/most-exact) match.
    """
    matches = search_items(query)
    if not matches:
        log.error("No items found matching '%s'. Try --refresh-items first.", query)
        return None

    # Prefer exact name match, then shortest name (most specific)
    exact = [m for m in matches if m["item_name"].lower() == query.lower()]
    chosen = exact[0] if exact else sorted(matches, key=lambda m: len(m["item_name"]))[0]

    added = db.add_to_watchlist(chosen["item_url"], chosen["item_name"])
    if added:
        log.info("Added '%s' to watchlist.", chosen["item_name"])
    else:
        log.info("'%s' is already on your watchlist.", chosen["item_name"])

    return chosen["item_name"]


def remove_item(query: str) -> Optional[str]:
    """
    Remove an item matching `query` from the watchlist.
    Returns the item name if removed, None if not found.
    """
    watchlist = db.get_watchlist()
    query_lower = query.lower()

    matches = [
        w for w in watchlist
        if query_lower in w["item_name"].lower()
           or query_lower in w["item_url"].lower()
    ]

    if not matches:
        log.error("'%s' not found in watchlist.", query)
        return None

    chosen = matches[0]
    removed = db.remove_from_watchlist(chosen["item_url"])
    if removed:
        log.info("Removed '%s' from watchlist.", chosen["item_name"])
    return chosen["item_name"] if removed else None


def print_watchlist() -> None:
    """Print the current watchlist to stdout."""
    items = db.get_watchlist()
    if not items:
        print("Your watchlist is empty.")
        print("Use:  python main.py --watchlist-add \"item name\"")
        return

    print(f"\n{'Item Name':<40} {'Added':<20}")
    print("─" * 62)
    for item in items:
        print(f"{item['item_name']:<40} {item['added_at'][:10]:<20}")
    print(f"\nTotal: {len(items)} item(s)")


def print_search_results(query: str) -> None:
    """Print search results for a query."""
    results = search_items(query)
    if not results:
        print(f"No items found matching '{query}'.")
        return

    print(f"\nFound {len(results)} result(s) for '{query}':\n")
    print(f"{'Item Name':<45} {'URL Name'}")
    print("─" * 80)
    for item in results[:30]:
        print(f"{item['item_name']:<45} {item['item_url']}")
    if len(results) > 30:
        print(f"  … and {len(results) - 30} more. Try a more specific query.")
