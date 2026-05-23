"""
analyzer.py — Price trend analysis and signal generation.

For each item we compute five metrics from stored daily snapshots:

  1. short_slope   — 7-day linear regression slope (normalised to % per day)
  2. long_slope    — 30-day linear regression slope (normalised)
  3. momentum      — Current price vs 30-day MA (% deviation)
  4. volume_trend  — 7-day avg volume / 30-day avg volume
  5. volatility    — Coefficient of variation (std / mean) over 14 days

These combine into a confidence score and a BUY / SELL / HOLD / NEUTRAL signal.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config
import database as db

log = logging.getLogger(__name__)


# ─── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class ItemSignal:
    item_url: str
    item_name: str
    signal: str          # "BUY" | "SELL" | "HOLD" | "NEUTRAL"
    confidence: float    # 0.0 – 1.0
    current_price: float
    avg_30d: float
    short_slope_pct: float    # % per day over 7 days
    long_slope_pct: float     # % per day over 30 days
    volume_trend: float       # 7d/30d volume ratio
    momentum_pct: float       # % vs 30d MA
    explanation: str          # human-readable rationale


@dataclass
class AnalysisReport:
    buys: list[ItemSignal] = field(default_factory=list)
    sells: list[ItemSignal] = field(default_factory=list)
    holds: list[ItemSignal] = field(default_factory=list)
    total_scanned: int = 0
    total_signals: int = 0


# ─── Math Helpers ──────────────────────────────────────────────────────────────

def _linear_slope(values: list[float]) -> float:
    """Return the slope of a least-squares linear fit, normalised per-day."""
    if len(values) < 3:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    # Remove NaN entries
    mask = ~np.isnan(y)
    if mask.sum() < 3:
        return 0.0
    coeffs = np.polyfit(x[mask], y[mask], 1)
    return float(coeffs[0])  # units: price / day


def _normalise_slope(slope: float, mean_price: float) -> float:
    """Convert absolute slope to % per day relative to mean price."""
    if mean_price == 0:
        return 0.0
    return (slope / mean_price) * 100.0


def _moving_average(values: list[float]) -> float:
    arr = np.array(values, dtype=float)
    clean = arr[~np.isnan(arr)]
    if len(clean) == 0:
        return 0.0
    return float(np.mean(clean))


def _coeff_variation(values: list[float]) -> float:
    arr = np.array(values, dtype=float)
    clean = arr[~np.isnan(arr)]
    if len(clean) < 2:
        return 0.0
    mean = np.mean(clean)
    if mean == 0:
        return 0.0
    return float(np.std(clean) / mean)


# ─── Signal Logic ──────────────────────────────────────────────────────────────

def _compute_signal(
    item_url: str,
    item_name: str,
    snapshots: list[dict],
) -> Optional[ItemSignal]:
    """
    Compute a trading signal for a single item from its stored snapshots.
    Returns None if there is insufficient data.
    """
    if len(snapshots) < 10:
        return None   # not enough history

    # Extract time-ordered median prices and volumes
    prices = [s["median"] or s["avg_price"] for s in snapshots]
    volumes = [s["volume"] or 0 for s in snapshots]

    # Filter out None values
    prices = [p if p is not None else float("nan") for p in prices]

    if all(np.isnan(p) for p in prices):
        return None

    current_price = next((p for p in reversed(prices) if not np.isnan(p)), None)
    if current_price is None or current_price <= 0:
        return None

    # ── Slopes ──────────────────────────────────────────────────────────────────
    short_prices = prices[-7:]
    long_prices  = prices[-30:] if len(prices) >= 30 else prices

    mean_price = _moving_average(long_prices)
    if mean_price == 0:
        return None

    short_slope = _linear_slope(short_prices)
    long_slope  = _linear_slope(long_prices)
    short_slope_pct = _normalise_slope(short_slope, mean_price)
    long_slope_pct  = _normalise_slope(long_slope, mean_price)

    # ── Momentum ────────────────────────────────────────────────────────────────
    avg_30d = _moving_average(long_prices)
    momentum_pct = ((current_price - avg_30d) / avg_30d * 100) if avg_30d else 0.0

    # ── Volume trend ────────────────────────────────────────────────────────────
    vol_7d  = _moving_average(volumes[-7:])
    vol_30d = _moving_average(volumes[-30:] if len(volumes) >= 30 else volumes)
    volume_trend = (vol_7d / vol_30d) if vol_30d > 0 else 1.0

    # Skip illiquid items
    if vol_30d < config.MIN_VOLUME_FILTER:
        return None

    # ── Volatility ──────────────────────────────────────────────────────────────
    volatility = _coeff_variation(prices[-14:])

    # ─── Signal classification ──────────────────────────────────────────────────
    #
    # BUY  : Short trend rising (slope > +0.3%/day) AND price below 30d MA
    #         (momentum < -3%) — oversold, momentum shifting up
    #
    # SELL : Short trend falling (slope < -0.3%/day) AND price at/above 30d MA
    #         (momentum > +3%) AND volume still healthy (≥ 0.7x 30d avg)
    #         → overbought, momentum turning down
    #
    # HOLD : Price declining (slope < -0.2%/day) BUT volume is low (<0.6x)
    #         → illiquid slump, likely temporary — don't panic-sell
    #
    # NEUTRAL: No clear signal

    signal = "NEUTRAL"
    confidence = 0.0
    explanation = ""

    if short_slope_pct > 0.3 and momentum_pct < -3.0:
        signal = "BUY"
        # Confidence grows with slope magnitude and how oversold we are
        confidence = min(
            1.0,
            (short_slope_pct / 2.0) * 0.5 +
            (abs(momentum_pct) / 20.0) * 0.35 +
            (volume_trend * 0.15),
        )
        explanation = (
            f"Price dip ({momentum_pct:+.1f}% vs 30d avg) with rising "
            f"7d trend (+{short_slope_pct:.2f}%/day). Volume {volume_trend:.1f}x normal."
        )

    elif short_slope_pct < -0.3 and momentum_pct > 3.0 and volume_trend >= 0.7:
        signal = "SELL"
        confidence = min(
            1.0,
            (abs(short_slope_pct) / 2.0) * 0.5 +
            (momentum_pct / 20.0) * 0.35 +
            (volume_trend * 0.15),
        )
        explanation = (
            f"Price peaked ({momentum_pct:+.1f}% above 30d avg), now falling "
            f"({short_slope_pct:.2f}%/day). Volume {volume_trend:.1f}x normal."
        )

    elif short_slope_pct < -0.2 and volume_trend < 0.6:
        signal = "HOLD"
        confidence = min(
            1.0,
            (abs(short_slope_pct) / 2.0) * 0.4 +
            (1.0 - volume_trend) * 0.6,
        )
        explanation = (
            f"Price softening ({short_slope_pct:.2f}%/day) but volume is low "
            f"({volume_trend:.1f}x 30d avg) — likely a low-activity dip, not a crash."
        )

    if confidence < config.MIN_SIGNAL_CONFIDENCE:
        signal = "NEUTRAL"

    if signal == "NEUTRAL":
        return None

    return ItemSignal(
        item_url=item_url,
        item_name=item_name,
        signal=signal,
        confidence=confidence,
        current_price=current_price,
        avg_30d=avg_30d,
        short_slope_pct=short_slope_pct,
        long_slope_pct=long_slope_pct,
        volume_trend=volume_trend,
        momentum_pct=momentum_pct,
        explanation=explanation,
    )


# ─── Full Analysis Run ─────────────────────────────────────────────────────────

def run_analysis() -> AnalysisReport:
    """
    Analyse all tracked items and return a report with ranked signals.
    """
    report = AnalysisReport()
    tracked = db.get_tracked_items()
    report.total_scanned = len(tracked)

    log.info("Running analysis on %d items…", len(tracked))

    for item in tracked:
        snapshots = db.get_snapshots(item["item_url"], days=90)
        if not snapshots:
            continue

        signal = _compute_signal(
            item_url=item["item_url"],
            item_name=item["item_name"],
            snapshots=snapshots,
        )

        if signal is None:
            continue

        if signal.signal == "BUY":
            report.buys.append(signal)
        elif signal.signal == "SELL":
            report.sells.append(signal)
        elif signal.signal == "HOLD":
            report.holds.append(signal)

    # Sort each list by confidence descending
    report.buys.sort(key=lambda s: s.confidence, reverse=True)
    report.sells.sort(key=lambda s: s.confidence, reverse=True)
    report.holds.sort(key=lambda s: s.confidence, reverse=True)

    # Trim to max per section
    n = config.MAX_ITEMS_PER_SECTION
    report.buys  = report.buys[:n]
    report.sells = report.sells[:n]
    report.holds = report.holds[:n]

    report.total_signals = len(report.buys) + len(report.sells) + len(report.holds)

    log.info(
        "Analysis complete: %d buys, %d sells, %d holds (from %d scanned).",
        len(report.buys), len(report.sells), len(report.holds),
        report.total_scanned,
    )
    return report
