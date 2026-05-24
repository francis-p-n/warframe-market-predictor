"""
relic_analyzer.py — Rank Warframe relics by expected platinum value per run.

Cross-references relic drop tables (from relic_scraper.py) with live market
prices (from our CSV database) to answer the question:
  "Which relic should I farm right now to make the most platinum?"

Expected Value formula (per run, single player):
  EV = sum over 6 reward slots: price(item) × chance(rarity, refinement) / 100

We compute EV for both Intact and Radiant refinements. Radiant is better when
the rare drop is worth farming specifically. Intact is better when the common
drops are all valuable (maximises average value per run, no Void Traces spent).
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from predictor.core import database as db
from predictor.relics.relic_scraper import FARM_LOCATIONS, RELIC_PROBS, get_relics

log = logging.getLogger(__name__)

# Items below this plat value are treated as worth 0 (forma, etc.)
MIN_ITEM_VALUE = 3.0

# Only include relics with at least this EV to filter out worthless ones
MIN_EV_INTACT  = 2.0   # plat per run
MIN_EV_RADIANT = 3.0

# How many days of price history to average for EV calc
PRICE_LOOKBACK_DAYS = 14


@dataclass
class RelicReward:
    item:       str
    rarity:     str      # "Common" | "Uncommon" | "Rare"
    chance_pct: float    # at Intact refinement
    price:      float    # median price in plat (0 if unknown)
    ev_contrib: float    # price × chance/100


@dataclass
class RelicRec:
    tier:          str            # "Lith" | "Meso" | "Neo" | "Axi"
    name:          str            # e.g. "A1"
    full_name:     str            # e.g. "Lith A1"
    rewards:       list[RelicReward]
    ev_intact:     float          # expected plat per Intact run
    ev_radiant:    float          # expected plat per Radiant run
    best_drop:     Optional[RelicReward]   # the most valuable single reward
    farm_location: dict           # best node dict from FARM_LOCATIONS
    plat_per_hour_intact:  float
    plat_per_hour_radiant: float
    recommendation: str           # plain-English advice


# ─── Price Lookup ─────────────────────────────────────────────────────────────

def _build_price_map() -> dict[str, float]:
    """
    Build a {item_name_lower: median_price} lookup from stored CSV snapshots.
    Uses the last PRICE_LOOKBACK_DAYS days of data and averages the medians.
    """
    price_map: dict[str, float] = {}
    cached = db.get_all_cached_items()

    for item in cached:
        snaps = db.get_snapshots(item["item_url"], days=PRICE_LOOKBACK_DAYS)
        if not snaps:
            continue
        medians = [s["median"] for s in snaps if s["median"] and s["median"] > 0]
        if not medians:
            avg_prices = [s["avg_price"] for s in snaps if s["avg_price"] and s["avg_price"] > 0]
            if not avg_prices:
                continue
            medians = avg_prices

        price_map[item["item_name"].lower()] = sum(medians) / len(medians)

    log.info("Price map built: %d items with price data.", len(price_map))
    return price_map


def _normalise(name: str) -> str:
    """Normalise an item name for fuzzy matching."""
    return re.sub(r"\s+", " ", name.lower().strip())


def _lookup_price(drop_name: str, price_map: dict[str, float]) -> float:
    """
    Try to find a market price for a relic drop item name.
    Handles variations like 'Blueprint' suffix, Prime name formatting.
    Returns 0.0 if no price found.
    """
    key = _normalise(drop_name)

    # Direct match
    if key in price_map:
        return max(0.0, price_map[key])

    # Try without " blueprint" suffix (some items listed without it)
    stripped = key.removesuffix(" blueprint")
    if stripped in price_map:
        return max(0.0, price_map[stripped])

    # Try with " blueprint" suffix
    with_bp = key + " blueprint"
    if with_bp in price_map:
        return max(0.0, price_map[with_bp])

    # Partial match — find the most specific item containing all words
    words = key.split()
    candidates = [
        (k, v) for k, v in price_map.items()
        if all(w in k for w in words)
    ]
    if candidates:
        # shortest key = most specific match
        best = min(candidates, key=lambda x: len(x[0]))
        return max(0.0, best[1])

    return 0.0


# ─── EV Computation ───────────────────────────────────────────────────────────

def _compute_ev(rewards: list[RelicReward], state: str) -> float:
    """
    Compute expected plat value for one relic run at the given refinement state.
    Uses the canonical per-slot probabilities from RELIC_PROBS.
    """
    probs = RELIC_PROBS.get(state, RELIC_PROBS["Intact"])
    total = 0.0
    for r in rewards:
        chance = probs.get(r.rarity, 0.0) / 100.0
        price  = r.price if r.price >= MIN_ITEM_VALUE else 0.0
        total += price * chance
    return round(total, 2)


def _build_rewards(raw_rewards: list[dict], price_map: dict[str, float]) -> list[RelicReward]:
    """Map raw API reward dicts to RelicReward objects with prices filled in."""
    rewards = []
    for r in raw_rewards:
        item   = r.get("item", "")
        rarity = r.get("rarity", "Common")
        chance = RELIC_PROBS["Intact"].get(rarity, 0.0)
        price  = _lookup_price(item, price_map)
        ev_contrib = (price if price >= MIN_ITEM_VALUE else 0.0) * chance / 100
        rewards.append(RelicReward(
            item=item, rarity=rarity, chance_pct=chance,
            price=price, ev_contrib=ev_contrib,
        ))
    return rewards


def _pick_farm_location(tier: str) -> dict:
    locations = FARM_LOCATIONS.get(tier, [])
    return locations[0] if locations else {"node": "Unknown", "type": "?", "runs_per_hour": 1, "note": ""}


def _build_recommendation(rec: "RelicRec") -> str:
    """Plain English: should they run this Intact or Radiant, and why?"""
    if rec.best_drop and rec.best_drop.rarity == "Rare" and rec.best_drop.price >= 20:
        radiant_edge = rec.ev_radiant - rec.ev_intact
        if radiant_edge >= 2.0:
            return (
                f"Run **Radiant** — the rare drop ({rec.best_drop.item}, "
                f"{rec.best_drop.price:.0f}p) is worth spending Void Traces for "
                f"the 10% chance. Extra ~{radiant_edge:.1f}p EV per run."
            )
    if rec.ev_intact >= 5.0:
        return (
            f"Run **Intact** — all drops are decent so don't waste Void Traces. "
            f"~{rec.ev_intact:.1f}p average per run without any refinement cost."
        )
    return (
        f"Decent value at ~{rec.ev_intact:.1f}p per Intact run. "
        f"Radiant gives ~{rec.ev_radiant:.1f}p if you have spare Void Traces."
    )


# ─── Main Analysis ────────────────────────────────────────────────────────────

def get_top_relics(n: int = 10) -> list[RelicRec]:
    """
    Return the top-n most profitable relics to farm right now,
    ranked by plat-per-hour (Intact runs, most accessible for casual players).
    """
    relics     = get_relics()
    price_map  = _build_price_map()

    if not relics:
        log.warning("No relic data available. Run --refresh-relics first.")
        return []

    if not price_map:
        log.warning("No price data in database yet. Run --fetch-now first.")
        return []

    results: list[RelicRec] = []

    for relic in relics:
        tier    = relic.get("tier", "")
        name    = relic.get("name", "")
        raw_rwd = relic.get("rewards", [])

        if not tier or not name or not raw_rwd:
            continue

        rewards    = _build_rewards(raw_rwd, price_map)
        ev_intact  = _compute_ev(rewards, "Intact")
        ev_radiant = _compute_ev(rewards, "Radiant")

        if ev_intact < MIN_EV_INTACT and ev_radiant < MIN_EV_RADIANT:
            continue

        farm      = _pick_farm_location(tier)
        rph       = farm.get("runs_per_hour", 1)
        best_drop = max(rewards, key=lambda r: r.price) if rewards else None

        rec = RelicRec(
            tier=tier,
            name=name,
            full_name=f"{tier} {name}",
            rewards=rewards,
            ev_intact=ev_intact,
            ev_radiant=ev_radiant,
            best_drop=best_drop,
            farm_location=farm,
            plat_per_hour_intact=round(ev_intact * rph, 1),
            plat_per_hour_radiant=round(ev_radiant * rph, 1),
            recommendation="",
        )
        rec.recommendation = _build_recommendation(rec)
        results.append(rec)

    # Sort by Intact plat/hour (accessible for everyone, no Void Trace cost)
    results.sort(key=lambda r: r.plat_per_hour_intact, reverse=True)

    top = results[:n]
    log.info("Relic analysis: %d relics ranked, returning top %d.", len(results), len(top))
    return top
