"""
analyzer.py — SVM-based price signal classifier with plain-English output.

Model: scikit-learn SVC (RBF kernel) + StandardScaler pipeline.

Training labels are trough/peak aware:
  BUY  — price is at/near a 30-day low AND recovers ≥3% within 7 days
  SELL — price is at/near a 30-day high AND drops ≥3% within 7 days
  HOLD — price declining but low volume; likely a quiet patch

Fallback: rule-based signals are used for the first 7+ days before
the SVM has enough labeled examples to train on.
"""

import logging
import os
import pickle
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
try:
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    class Pipeline: pass
    class StandardScaler: pass
    class SVC: pass

from predictor.core import config
from predictor.core import database as db
from predictor.market.features import MIN_DAYS_REQUIRED, extract_features

log = logging.getLogger(__name__)

MODEL_PATH           = os.path.join(config.DATA_DIR, "model.pkl")
MIN_TRAINING_SAMPLES = 80    # need this many labeled examples before trusting the SVM
LOOK_AHEAD_DAYS      = 7     # days forward used to verify label quality
TROUGH_TOLERANCE     = 0.06  # within 6% of local low/high counts as trough/peak
RECOVERY_THRESHOLD   = 0.03  # 3% move in 7 days to confirm the label

LABEL_MAP = {0: "SELL", 1: "HOLD", 2: "BUY"}
LABEL_INT = {"SELL": 0, "HOLD": 1, "BUY": 2}


# ─── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class ItemSignal:
    item_url:      str
    item_name:     str
    signal:        str         # "BUY" | "SELL" | "HOLD"
    confidence:    float       # 0.0 – 1.0
    current_price: float
    avg_30d:       float
    low_30d:       float
    high_30d:      float
    momentum_pct:  float       # % vs 30d average
    vol_ratio:     float       # 7d/30d volume
    rsi:           float
    headline:      str         # plain-English one-liner
    detail:        str         # plain-English detail sentence
    method:        str         # "svm" | "rule-based"


@dataclass
class AnalysisReport:
    buys:          list[ItemSignal] = field(default_factory=list)
    sells:         list[ItemSignal] = field(default_factory=list)
    holds:         list[ItemSignal] = field(default_factory=list)
    total_scanned: int = 0
    total_signals: int = 0
    model_used:    str = "rule-based"


# ─── Plain-English Copy ────────────────────────────────────────────────────────

def _buy_text(feat: np.ndarray, sig: "ItemSignal") -> tuple[str, str]:
    """Return (headline, detail) for a BUY signal in plain English."""
    rsi, slope7, slope_decel, rsi_div, to_ma30, local_min, vol_acc, vol_trend, vol_14, dow, macd_hist, bb_pos, ema_ratio = feat

    pct_below = abs(to_ma30)
    near_bottom = local_min < 0.2   # within bottom 20% of 30d range
    diverging   = rsi_div > 3
    decelerating = slope_decel > 0.1
    accumulating = vol_acc > 1.3
    weekend_boost = dow >= 1.0
    macd_cross = macd_hist > 0

    if near_bottom and (diverging or macd_cross):
        headline = "Price at the bottom — buyers are quietly moving in"
        detail   = (
            f"**{sig.item_name}** is sitting near its lowest price in a month ({sig.current_price:.0f}p vs "
            f"{sig.avg_30d:.0f}p average). Momentum indicators like MACD and RSI are turning positive, "
            f"a classic sign the drop is almost over. Good entry point."
        )
    elif bb_pos < 0.1 and decelerating:
        headline = "Price hit the lower Bollinger Band and is stabilizing"
        detail   = (
            f"**{sig.item_name}** dropped to {sig.current_price:.0f}p, hitting extreme oversold levels on the "
            f"Bollinger Bands. The decline is now flattening out, which often means the bottom is in. Buy before it bounces."
        )
    elif accumulating and ema_ratio > 0:
        headline = "Short-term moving averages crossing up + rising trade volume"
        detail   = (
            f"**{sig.item_name}** is priced at {sig.current_price:.0f}p with noticeably more "
            f"buy activity than sell activity lately. Players are accumulating at this price. "
            f"Worth picking up while it's still cheap."
        )
    elif weekend_boost and to_ma30 < -5:
        headline = "Weekend trading boost + below-average price — good timing"
        detail   = (
            f"**{sig.item_name}** at {sig.current_price:.0f}p is {pct_below:.0f}% below its normal "
            f"price, and weekend player counts typically push prices higher. "
            f"Good window to buy now and sell over the weekend."
        )
    else:
        headline = "Below average price with improving momentum"
        detail   = (
            f"**{sig.item_name}** is at {sig.current_price:.0f}p — about {pct_below:.0f}% below its "
            f"30-day average of {sig.avg_30d:.0f}p. Short-term trend is starting to turn positive. "
            f"Confidence: {sig.confidence*100:.0f}%."
        )
    return headline, detail


def _sell_text(feat: np.ndarray, sig: "ItemSignal") -> tuple[str, str]:
    rsi, slope7, slope_decel, rsi_div, to_ma30, local_min, vol_acc, vol_trend, vol_14, dow, macd_hist, bb_pos, ema_ratio = feat
    pct_above = to_ma30
    near_top = local_min > 0.8   # within top 20% of 30d range

    if near_top and bb_pos > 0.9 and rsi > 65:
        headline = "Price spiked hard — cash out before it drops"
        detail   = (
            f"**{sig.item_name}** is at {sig.current_price:.0f}p, breaking the upper Bollinger Band. "
            f"RSI at {rsi:.0f} confirms it's heavily overbought. Sellers who list now will get the best price."
        )
    elif macd_hist < 0 and near_top:
        headline = "MACD crossed bearish — upward trend is exhausted"
        detail   = (
            f"**{sig.item_name}** hit a high recently ({sig.current_price:.0f}p) but the MACD momentum "
            f"is turning down. It's still above average by {pct_above:.0f}% — you can still get a "
            f"good price if you list it now before the drop accelerates."
        )
    elif vol_trend < 0.7 and near_top:
        headline = "High price but trading is drying up — sell while you can"
        detail   = (
            f"**{sig.item_name}** is priced well ({sig.current_price:.0f}p vs {sig.avg_30d:.0f}p average) "
            f"but buyer activity is dropping off. When volume falls at a price peak, a correction "
            f"usually follows. Good time to exit."
        )
    else:
        headline = "Above normal price — good time to sell"
        detail   = (
            f"**{sig.item_name}** at {sig.current_price:.0f}p is {pct_above:.0f}% above its "
            f"30-day average. Trend is pointing down. List it while buyers are still paying this much."
        )
    return headline, detail


def _hold_text(feat: np.ndarray, sig: "ItemSignal") -> tuple[str, str]:
    rsi, slope7, slope_decel, rsi_div, to_ma30, local_min, vol_acc, vol_trend, vol_14, dow, macd_hist, bb_pos, ema_ratio = feat
    headline = "Price is down but the market is quiet — not a real crash"
    detail   = (
        f"**{sig.item_name}** has slipped to {sig.current_price:.0f}p but trading volume is very low "
        f"({vol_trend:.1f}x normal). This usually just means fewer players are online — "
        f"not that the item lost its value. Don't panic-sell. Wait for activity to pick back up."
    )
    return headline, detail


# ─── Model I/O ─────────────────────────────────────────────────────────────────

def _load_model() -> Optional[Pipeline]:
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        if not SKLEARN_AVAILABLE and "sklearn" in str(exc):
            log.info("Skipping ML model load because scikit-learn is not installed.")
        else:
            log.warning("Could not load model from %s: %s", MODEL_PATH, exc)
        return None


def _save_model(pipeline: Pipeline) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipeline, f)
    log.info("SVM model saved to %s", MODEL_PATH)


def _build_pipeline() -> Pipeline:
    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn is not installed")
    return Pipeline([
        ("scaler", StandardScaler()),
        ("svm", SVC(
            kernel="rbf",
            class_weight="balanced",   # handle class imbalance gracefully
            C=1.5,
            gamma="scale",
            probability=True,          # needed for confidence scores
        )),
    ])


# ─── Training Data Generation ──────────────────────────────────────────────────

def _label_point(
    prices: list,
    idx: int,
) -> Optional[int]:
    """
    Generate a trough/peak-aware label for the data point at `idx`.

    BUY:  price is at/near a 30-day low AND recovers ≥3% within 7 days
    SELL: price is at/near a 30-day high AND drops ≥3% within 7 days
    HOLD: everything else with enough data
    Returns None if there is insufficient look-ahead data.
    """
    n = len(prices)
    if idx + LOOK_AHEAD_DAYS >= n:
        return None   # no look-ahead available

    current = prices[idx]
    future  = prices[idx + LOOK_AHEAD_DAYS]
    if current is None or future is None or current <= 0:
        return None

    # 30-day local low and high around this point
    window     = prices[max(0, idx - 30): idx + 1]
    valid      = [p for p in window if p is not None and p > 0]
    if not valid:
        return None
    lo30 = min(valid)
    hi30 = max(valid)

    near_low  = (current - lo30) <= TROUGH_TOLERANCE * lo30 if lo30 > 0 else False
    near_high = (hi30 - current) <= TROUGH_TOLERANCE * hi30 if hi30 > 0 else False

    ratio = future / current

    # BUY: near trough AND confirmed by subsequent recovery
    if near_low and ratio >= (1.0 + RECOVERY_THRESHOLD):
        return LABEL_INT["BUY"]

    # SELL: near peak AND confirmed by subsequent drop
    if near_high and ratio <= (1.0 - RECOVERY_THRESHOLD):
        return LABEL_INT["SELL"]

    # HOLD: not near extremes — label as HOLD so the model learns these too
    return LABEL_INT["HOLD"]


def _generate_labeled_data(snaps: list[dict]) -> tuple[list, list]:
    """Extract feature vectors + trough-aware labels from one item's history."""
    prices  = [s["median"] or s["avg_price"] for s in snaps]
    volumes = [s["volume"] for s in snaps]
    dates   = [s["snap_date"] for s in snaps]
    n       = len(prices)

    X, y = [], []
    for i in range(MIN_DAYS_REQUIRED, n - LOOK_AHEAD_DAYS):
        feat  = extract_features(prices[:i + 1], volumes[:i + 1], snap_date=dates[i])
        label = _label_point(prices, i)
        if feat is not None and label is not None:
            X.append(feat)
            y.append(label)
    return X, y


def train_model() -> Optional[Pipeline]:
    """
    Gather labeled examples from all tracked items and train the SVM.
    Returns the trained pipeline or None if not enough data yet.
    """
    if not SKLEARN_AVAILABLE:
        log.info("scikit-learn is not available. Using rule-based fallback only.")
        return None

    tracked = db.get_tracked_items()
    X_all, y_all = [], []

    for item in tracked:
        snaps = db.get_snapshots(item["item_url"], days=90)
        if len(snaps) < MIN_DAYS_REQUIRED + LOOK_AHEAD_DAYS:
            continue
        X, y = _generate_labeled_data(snaps)
        X_all.extend(X)
        y_all.extend(y)

    if len(X_all) < MIN_TRAINING_SAMPLES:
        log.info(
            "Insufficient training data: %d examples (need %d). "
            "Rule-based fallback will be used until more data is collected.",
            len(X_all), MIN_TRAINING_SAMPLES,
        )
        return None

    if len(set(y_all)) < 2:
        log.warning("Only one class in training data — skipping SVM training.")
        return None

    dist = Counter(LABEL_MAP[y] for y in y_all)
    log.info(
        "Training SVM on %d examples from %d items. Labels: %s",
        len(X_all), len(tracked), dict(dist),
    )

    pipeline = _build_pipeline()
    pipeline.fit(np.array(X_all), np.array(y_all))
    _save_model(pipeline)
    return pipeline


# ─── SVM Prediction ────────────────────────────────────────────────────────────

def _predict_svm(
    pipeline: Pipeline,
    item: dict,
    snaps: list[dict],
) -> Optional[ItemSignal]:
    prices  = [s["median"] or s["avg_price"] for s in snaps]
    volumes = [s["volume"] for s in snaps]
    dates   = [s["snap_date"] for s in snaps]

    feat = extract_features(prices, volumes, snap_date=dates[-1] if dates else None)
    if feat is None:
        return None

    current = next((p for p in reversed(prices) if p is not None), None)
    if not current or current <= 0:
        return None

    proba      = pipeline.predict_proba([feat])[0]   # [P(SELL), P(HOLD), P(BUY)]
    pred       = int(np.argmax(proba))
    confidence = float(proba[pred])

    if confidence < config.MIN_SIGNAL_CONFIDENCE:
        return None

    signal = LABEL_MAP[pred]
    if signal == "HOLD" and confidence < 0.72:
        return None   # only report very confident holds

    local_min_prox = feat[5]
    if signal == "BUY" and local_min_prox > 0.05:
        return None   # Strict enforcement: must be at a trough (bottom 5% of 30d range)
    if signal == "SELL" and local_min_prox < 0.95:
        return None   # Strict enforcement: must be at a peak (top 5% of 30d range)

    p30      = [p for p in prices[-30:] if p is not None]
    avg_30d  = float(np.mean(p30)) if p30 else current
    low_30d  = float(np.min(p30))  if p30 else current
    high_30d = float(np.max(p30))  if p30 else current

    sig = ItemSignal(
        item_url=item["item_url"],
        item_name=item["item_name"],
        signal=signal,
        confidence=confidence,
        current_price=current,
        avg_30d=avg_30d,
        low_30d=low_30d,
        high_30d=high_30d,
        momentum_pct=feat[4],      # price_to_ma30
        vol_ratio=feat[7],         # vol_trend
        rsi=feat[0],               # rsi_14
        headline="",
        detail="",
        method="svm",
    )

    if signal == "BUY":
        sig.headline, sig.detail = _buy_text(feat, sig)
    elif signal == "SELL":
        sig.headline, sig.detail = _sell_text(feat, sig)
    else:
        sig.headline, sig.detail = _hold_text(feat, sig)

    return sig


# ─── Rule-Based Fallback ────────────────────────────────────────────────────────

def _predict_rules(item: dict, snaps: list[dict]) -> Optional[ItemSignal]:
    """
    Rule-based signal used before the SVM has enough training data.
    Trough-aware: requires slope deceleration or RSI divergence alongside a low price.
    """
    prices  = [s["median"] or s["avg_price"] for s in snaps]
    volumes = [s["volume"] for s in snaps]
    dates   = [s["snap_date"] for s in snaps]

    feat = extract_features(prices, volumes, snap_date=dates[-1] if dates else None)
    if feat is None:
        return None

    rsi, slope7, slope_decel, rsi_div, to_ma30, local_min, vol_acc, vol_trend, volatility, dow, macd_hist, bb_pos, ema_ratio = feat

    current = next((p for p in reversed(prices) if p is not None), None)
    if not current or current <= 0:
        return None

    p30      = [p for p in prices[-30:] if p is not None]
    avg_30d  = float(np.mean(p30)) if p30 else current
    low_30d  = float(np.min(p30))  if p30 else current
    high_30d = float(np.max(p30))  if p30 else current

    signal     = "NEUTRAL"
    confidence = 0.0

    # ── BUY: must be near bottom AND show reversal signs ──────────────────────
    near_bottom  = local_min <= 0.05                   # STRICT trough: bottom 5% of 30d range
    reversal_ok  = (slope_decel > 0.1) or (rsi_div > 3) or (vol_acc > 1.3) or (macd_hist > 0)
    if near_bottom and reversal_ok and to_ma30 < -3.0:
        signal     = "BUY"
        confidence = min(1.0,
            0.30 * min(1.0, (1.0 - local_min) * 2) +
            0.20 * min(1.0, abs(to_ma30) / 15.0) +
            0.15 * min(1.0, slope_decel if slope_decel > 0 else 0) +
            0.15 * min(1.0, rsi_div / 10.0 if rsi_div > 0 else vol_acc / 3.0) +
            0.20 * (1.0 if macd_hist > 0 else 0.0) # Bonus for MACD crossover
        )

    # ── SELL: near peak, trend turning, still liquid ───────────────────────────
    elif local_min >= 0.95 and to_ma30 > 5.0 and vol_trend >= 0.7:
        signal     = "SELL"
        confidence = min(1.0,
            0.30 * min(1.0, local_min) +
            0.30 * min(1.0, to_ma30 / 20.0) +
            0.20 * min(1.0, vol_trend) +
            0.20 * (1.0 if macd_hist < 0 else 0.0) # Bonus for bearish MACD
        )

    # ── HOLD: falling but thin market — likely temporary ──────────────────────
    elif slope7 < -0.2 and vol_trend < 0.55 and local_min > 0.3:
        signal     = "HOLD"
        confidence = min(1.0, 0.5 + (0.55 - vol_trend) * 0.8)

    if confidence < config.MIN_SIGNAL_CONFIDENCE or signal == "NEUTRAL":
        return None

    sig = ItemSignal(
        item_url=item["item_url"],
        item_name=item["item_name"],
        signal=signal,
        confidence=confidence,
        current_price=current,
        avg_30d=avg_30d,
        low_30d=low_30d,
        high_30d=high_30d,
        momentum_pct=to_ma30,
        vol_ratio=vol_trend,
        rsi=rsi,
        headline="",
        detail="",
        method="rule-based",
    )

    if signal == "BUY":
        sig.headline, sig.detail = _buy_text(feat, sig)
    elif signal == "SELL":
        sig.headline, sig.detail = _sell_text(feat, sig)
    else:
        sig.headline, sig.detail = _hold_text(feat, sig)

    return sig


# ─── Full Analysis Run ──────────────────────────────────────────────────────────

def run_analysis() -> AnalysisReport:
    """
    Analyse all tracked items. Trains or loads SVM; falls back to rules if not ready.
    Returns up to MAX_ITEMS_PER_SECTION signals per category, sorted by confidence.
    """
    report  = AnalysisReport()
    tracked = db.get_tracked_items()
    report.total_scanned = len(tracked)

    # Try to load saved model; retrain if missing
    pipeline = _load_model()
    if pipeline is None:
        pipeline = train_model()

    method         = "svm" if pipeline is not None else "rule-based"
    report.model_used = method
    log.info("Analysing %d items via %s…", len(tracked), method)

    for item in tracked:
        snaps = db.get_snapshots(item["item_url"], days=90)
        if not snaps:
            continue

        sig = _predict_svm(pipeline, item, snaps) if pipeline else _predict_rules(item, snaps)
        if sig is None:
            continue

        if sig.signal == "BUY":
            report.buys.append(sig)
        elif sig.signal == "SELL":
            report.sells.append(sig)
        elif sig.signal == "HOLD":
            report.holds.append(sig)

    n = config.MAX_ITEMS_PER_SECTION
    report.buys  = sorted(report.buys,  key=lambda s: s.confidence, reverse=True)[:n]
    report.sells = sorted(report.sells, key=lambda s: s.confidence, reverse=True)[:n]
    report.holds = sorted(report.holds, key=lambda s: s.confidence, reverse=True)[:n]
    report.total_signals = len(report.buys) + len(report.sells) + len(report.holds)

    log.info(
        "Analysis done: %d buys, %d sells, %d holds | method=%s",
        len(report.buys), len(report.sells), len(report.holds), method,
    )
    return report


def retrain() -> bool:
    """Force a model retrain. Returns True on success."""
    pipeline = train_model()
    return pipeline is not None
