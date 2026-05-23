"""tests/test_features.py — Unit tests for feature extraction."""

import numpy as np
import pytest

from features import MIN_DAYS_REQUIRED, compute_rsi, extract_features


# ─── RSI ──────────────────────────────────────────────────────────────────────

class TestComputeRsi:
    def test_neutral_on_insufficient_data(self):
        assert compute_rsi(np.array([100.0, 101.0])) == 50.0

    def test_100_on_all_gains(self):
        prices = np.array([float(i) for i in range(1, 20)])
        assert compute_rsi(prices) == 100.0

    def test_in_range(self):
        prices = np.array([100.0, 102.0, 101.0, 103.0, 99.0, 100.0,
                           98.0, 101.0, 103.0, 100.0, 102.0, 101.0,
                           99.0, 100.0, 101.0, 103.0])
        rsi = compute_rsi(prices)
        assert 0.0 <= rsi <= 100.0


# ─── Feature Extraction ───────────────────────────────────────────────────────

def _make_prices(n: int = 40, trend: float = 0.0) -> list[float]:
    """Generate a synthetic price series of length n."""
    import random
    random.seed(42)
    price = 100.0
    prices = []
    for _ in range(n):
        price += trend + random.gauss(0, 1.5)
        prices.append(max(price, 1.0))
    return prices


def _make_volumes(n: int = 40) -> list[int]:
    import random
    random.seed(99)
    return [random.randint(10, 100) for _ in range(n)]


class TestExtractFeatures:
    def test_returns_none_on_insufficient_data(self):
        prices  = [100.0] * 10
        volumes = [50] * 10
        assert extract_features(prices, volumes) is None

    def test_returns_array_on_sufficient_data(self):
        prices  = _make_prices(MIN_DAYS_REQUIRED + 5)
        volumes = _make_volumes(MIN_DAYS_REQUIRED + 5)
        feat = extract_features(prices, volumes)
        assert feat is not None
        assert feat.shape == (10,)

    def test_no_nans_or_infs(self):
        prices  = _make_prices(50)
        volumes = _make_volumes(50)
        feat = extract_features(prices, volumes)
        assert feat is not None
        assert not np.isnan(feat).any()
        assert not np.isinf(feat).any()

    def test_rsi_in_valid_range(self):
        prices  = _make_prices(50)
        volumes = _make_volumes(50)
        feat = extract_features(prices, volumes)
        assert feat is not None
        rsi = feat[0]
        assert 0.0 <= rsi <= 100.0

    def test_local_min_prox_in_0_1(self):
        prices  = _make_prices(50)
        volumes = _make_volumes(50)
        feat = extract_features(prices, volumes)
        assert feat is not None
        local_min_prox = feat[5]
        assert 0.0 <= local_min_prox <= 1.0

    def test_handles_none_values(self):
        prices: list = _make_prices(50)
        volumes: list = _make_volumes(50)
        # Introduce some None gaps
        prices[5] = None  # type: ignore[index]
        prices[20] = None  # type: ignore[index]
        volumes[10] = None  # type: ignore[index]
        feat = extract_features(prices, volumes)
        # Should still compute (forward-fills nones)
        assert feat is not None

    def test_rising_trend_has_positive_slope(self):
        prices  = _make_prices(50, trend=1.0)  # consistently rising
        volumes = _make_volumes(50)
        feat = extract_features(prices, volumes)
        assert feat is not None
        slope_7d = feat[1]
        assert slope_7d > 0.0  # rising trend → positive slope

    def test_falling_trend_has_negative_slope(self):
        prices  = _make_prices(50, trend=-1.0)  # consistently falling
        volumes = _make_volumes(50)
        feat = extract_features(prices, volumes)
        assert feat is not None
        slope_7d = feat[1]
        assert slope_7d < 0.0  # falling trend → negative slope

    def test_day_of_week_encodes_correctly(self):
        prices  = _make_prices(50)
        volumes = _make_volumes(50)
        # Friday = weekday 4
        feat_fri = extract_features(prices, volumes, snap_date="2024-05-10")  # Friday
        feat_mon = extract_features(prices, volumes, snap_date="2024-05-13")  # Monday
        assert feat_fri is not None and feat_mon is not None
        assert feat_fri[9] == 1.0   # weekend premium
        assert feat_mon[9] == 0.0   # quiet day
