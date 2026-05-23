"""
features.py — Technical feature extraction for the Warframe Market SVM classifier.

10 features designed to distinguish genuine troughs from items still in free-fall:

  1.  rsi_14            — Relative Strength Index (oversold < 30, overbought > 70)
  2.  slope_7d          — 7-day price trend direction and magnitude (% per day)
  3.  slope_decel       — Is the rate of decline SLOWING? (trough signal)
  4.  rsi_divergence    — Price at new low but RSI recovering? (bullish divergence)
  5.  price_to_ma30     — How far current price is from the 30-day average (%)
  6.  local_min_prox    — How close is price to the 30-day low? (0=at bottom, 1=at top)
  7.  vol_accumulation  — Volume on rising days vs falling days in last 14d
  8.  vol_trend         — 7-day avg volume vs 30-day avg volume
  9.  volatility_14     — Price noise over 14 days (high = unpredictable)
  10. day_of_week       — Encoded weekend premium (Warframe-specific player pattern)
"""

from __future__ import annotations

import numpy as np
from datetime import date
from typing import Optional

# Minimum days of history before features can be computed reliably
MIN_DAYS_REQUIRED = 32

FEATURE_NAMES = [
    "rsi_14",
    "slope_7d",
    "slope_decel",
    "rsi_divergence",
    "price_to_ma30",
    "local_min_prox",
    "vol_accumulation",
    "vol_trend",
    "volatility_14",
    "day_of_week",
]


# ─── RSI ───────────────────────────────────────────────────────────────────────

def compute_rsi(prices: np.ndarray, period: int = 14) -> float:
    """
    Relative Strength Index. Returns 50.0 (neutral) if insufficient data.
    Below 30 = oversold (potential buy zone). Above 70 = overbought (sell zone).
    """
    if len(prices) < period + 1:
        return 50.0
    deltas    = np.diff(prices[-(period + 1):])
    gains     = deltas[deltas > 0]
    losses    = -deltas[deltas < 0]
    avg_gain  = float(np.mean(gains))  if len(gains)  > 0 else 0.0
    avg_loss  = float(np.mean(losses)) if len(losses) > 0 else 0.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ─── Main Feature Extractor ────────────────────────────────────────────────────

def extract_features(
    prices:   list[Optional[float]],
    volumes:  list[Optional[int]],
    snap_date: Optional[str] = None,   # "YYYY-MM-DD" for day-of-week feature
) -> Optional[np.ndarray]:
    """
    Extract the 10-feature vector from price + volume history (oldest first).
    Returns None if there is insufficient or invalid data.
    """
    if len(prices) < MIN_DAYS_REQUIRED:
        return None

    # ── Clean and forward-fill ─────────────────────────────────────────────────
    p = np.array([float(x) if x is not None else np.nan for x in prices])
    v = np.array([float(x) if x is not None else np.nan for x in volumes])
    p = _ffill(p)
    v = _ffill(v)

    if np.isnan(p[-1]) or p[-1] <= 0:
        return None

    current = float(p[-1])

    # ── 1. RSI 14 ──────────────────────────────────────────────────────────────
    rsi_now = compute_rsi(p)

    # ── 2. 7-day slope (% per day, normalised) ─────────────────────────────────
    p7   = p[-7:]
    x7   = np.arange(7, dtype=float)
    if not np.isnan(p7).any() and np.mean(p7) > 0:
        raw_slope = float(np.polyfit(x7, p7, 1)[0])
        slope_7d  = (raw_slope / float(np.mean(p7))) * 100.0
    else:
        slope_7d = 0.0

    # ── 3. Slope deceleration — is the decline slowing down? ──────────────────
    # Compare the slope of the first half vs second half of the 14-day window.
    # Positive value = decline is flattening = potential trough forming.
    p14 = p[-14:]
    if not np.isnan(p14).any() and len(p14) == 14:
        first_half  = p14[:7]
        second_half = p14[7:]
        x_half = np.arange(7, dtype=float)
        mean14 = float(np.mean(p14))
        if mean14 > 0:
            s1 = float(np.polyfit(x_half, first_half,  1)[0]) / mean14 * 100
            s2 = float(np.polyfit(x_half, second_half, 1)[0]) / mean14 * 100
            slope_decel = s2 - s1   # positive = deceleration of decline
        else:
            slope_decel = 0.0
    else:
        slope_decel = 0.0

    # ── 4. RSI divergence — price at new low but RSI recovering ───────────────
    # Compare RSI 7 days ago vs now while price is at/below that past price.
    # Bullish divergence: price lower (or same) but RSI higher = potential reversal.
    rsi_7d_ago = compute_rsi(p[:-7]) if len(p) >= 7 + 15 else rsi_now
    price_7d_ago = float(p[-8]) if not np.isnan(p[-8]) else current
    if current <= price_7d_ago and rsi_now > rsi_7d_ago:
        # Price down or flat, but RSI improving = bullish divergence
        rsi_divergence = rsi_now - rsi_7d_ago   # positive = bullish
    else:
        rsi_divergence = 0.0

    # ── 5. Price relative to 30-day average (%) ────────────────────────────────
    ma30 = float(np.nanmean(p[-30:])) if len(p) >= 30 else float(np.nanmean(p))
    price_to_ma30 = ((current / ma30) - 1.0) * 100.0 if ma30 > 0 else 0.0

    # ── 6. Local minimum proximity (0 = at 30d low, 1 = at 30d high) ──────────
    p30      = p[-30:]
    lo30     = float(np.nanmin(p30))
    hi30     = float(np.nanmax(p30))
    price_range = hi30 - lo30
    if price_range > 0:
        local_min_prox = (current - lo30) / price_range   # 0 = at bottom
    else:
        local_min_prox = 0.5

    # ── 7. Volume accumulation — volume on UP days vs DOWN days (14d) ─────────
    # > 1.0 means more volume is flowing in on rising days = accumulation signal
    v14 = v[-14:]
    p14_diff = np.diff(p[-15:]) if len(p) >= 15 else np.array([0.0])
    up_vol   = float(np.nansum(v14[-len(p14_diff):][p14_diff > 0]))
    down_vol = float(np.nansum(v14[-len(p14_diff):][p14_diff < 0]))
    vol_accumulation = (up_vol / down_vol) if down_vol > 0 else 1.0
    vol_accumulation = min(vol_accumulation, 5.0)  # cap outliers

    # ── 8. Volume trend (7d avg vs 30d avg) ───────────────────────────────────
    v_clean  = v[~np.isnan(v)]
    vol_7d   = float(np.mean(v_clean[-7:]))  if len(v_clean) >= 7  else float(np.mean(v_clean))
    vol_30d  = float(np.mean(v_clean[-30:])) if len(v_clean) >= 30 else float(np.mean(v_clean))
    vol_trend = (vol_7d / vol_30d) if vol_30d > 0 else 1.0

    # ── 9. Price volatility (coefficient of variation, 14d) ───────────────────
    mean14   = float(np.nanmean(p[-14:]))
    volatility = float(np.nanstd(p[-14:])) / mean14 if mean14 > 0 else 0.0

    # ── 10. Day-of-week Warframe premium ──────────────────────────────────────
    # Warframe has more players Fri–Sun → higher trading activity + demand.
    # Encode as: 0 = Mon/Tue (quiet), 0.5 = Wed/Thu, 1.0 = Fri/Sat/Sun (peak)
    if snap_date:
        try:
            dow = date.fromisoformat(snap_date).weekday()   # 0=Mon … 6=Sun
            day_of_week = 1.0 if dow >= 4 else (0.5 if dow >= 2 else 0.0)
        except ValueError:
            day_of_week = 0.5
    else:
        day_of_week = date.today().weekday()
        day_of_week = 1.0 if day_of_week >= 4 else (0.5 if day_of_week >= 2 else 0.0)

    # ── Assemble ───────────────────────────────────────────────────────────────
    feat = np.array([
        rsi_now,
        slope_7d,
        slope_decel,
        rsi_divergence,
        price_to_ma30,
        local_min_prox,
        vol_accumulation,
        vol_trend,
        volatility,
        day_of_week,
    ], dtype=float)

    if np.isnan(feat).any() or np.isinf(feat).any():
        return None

    return feat


def _ffill(arr: np.ndarray) -> np.ndarray:
    """Forward-fill NaN values."""
    out = arr.copy()
    for i in range(1, len(out)):
        if np.isnan(out[i]):
            out[i] = out[i - 1]
    return out
