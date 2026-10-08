"""Tests for the validation code itself.

A checklist that passes everything measures nothing. These tests feed the
analyser series whose properties are known in advance: plain Gaussian noise must
*fail* the fat-tail and clustering checks, and a series built to have those
properties must pass them. Without this, a bug in metrics.py would look like a
successful model.
"""

import numpy as np

from mes.metrics import analyse, autocorr, hill_tail_index, variance_ratio


def facts(report: dict) -> dict[str, bool]:
    return {c["name"]: c["passed"] for c in report["stylized_facts"]}


def gaussian(n: int = 4000, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n) * 0.01


def garch_like(n: int = 4000, seed: int = 0) -> np.ndarray:
    """Returns with persistent volatility — the textbook GARCH(1,1) shape."""
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    var = 1e-4
    for i in range(n):
        var = 2e-6 + 0.10 * out[i - 1] ** 2 + 0.88 * var if i else var
        out[i] = rng.standard_normal() * np.sqrt(var)
    return out


def test_gaussian_noise_fails_the_fat_tail_check():
    result = facts(analyse(gaussian()))
    assert result["Fat Tails"] is False
    assert result["Non-Normality"] is False


def test_gaussian_noise_fails_the_clustering_check():
    assert facts(analyse(gaussian()))["Volatility Clustering"] is False


def test_gaussian_noise_passes_the_no_autocorrelation_check():
    """It is a random walk increment, so this one *should* pass — otherwise the
    check is measuring something other than predictability."""
    assert facts(analyse(gaussian()))["No Return Autocorrelation"] is True


def test_garch_series_passes_clustering_and_fat_tails():
    result = facts(analyse(garch_like()))
    assert result["Volatility Clustering"] is True
    assert result["Fat Tails"] is True


def test_trending_series_fails_the_autocorrelation_check():
    """A series with obvious momentum must be flagged as predictable."""
    rng = np.random.default_rng(3)
    r = np.zeros(3000)
    for i in range(1, 3000):
        r[i] = 0.6 * r[i - 1] + rng.standard_normal() * 0.01
    assert facts(analyse(r))["No Return Autocorrelation"] is False


def test_autocorr_recovers_a_known_coefficient():
    rng = np.random.default_rng(1)
    r = np.zeros(20000)
    for i in range(1, 20000):
        r[i] = 0.5 * r[i - 1] + rng.standard_normal()
    assert abs(autocorr(r, 1) - 0.5) < 0.03


def test_hill_estimator_recovers_a_known_tail_index():
    """Pareto(alpha=3) samples should give a tail index near 3."""
    rng = np.random.default_rng(2)
    x = rng.pareto(3.0, 200_000) + 1.0
    assert 2.5 < hill_tail_index(x, tail_frac=0.02) < 3.6


def test_variance_ratio_is_one_for_a_random_walk():
    """The whole point of the statistic: a random walk scores 1 at every
    horizon, so any deviation means permanent and transient variance are out of
    balance."""
    r = np.random.default_rng(7).standard_normal(40_000) * 0.01
    for k in (2, 5, 10, 20):
        assert abs(variance_ratio(r, k) - 1.0) < 0.1, f"k={k}"


def test_variance_ratio_detects_mean_reversion():
    """Transient noise around a fixed level: the moves get taken back, so long
    horizons must score well below one."""
    rng = np.random.default_rng(8)
    level = np.cumsum(rng.standard_normal(20_000) * 0.0002)  # slow anchor
    noise = rng.standard_normal(20_000) * 0.01  # transient
    prices = level + noise
    r = np.diff(prices)
    assert variance_ratio(r, 20) < 0.5


def test_variance_ratio_detects_trending():
    rng = np.random.default_rng(9)
    r = np.zeros(20_000)
    for i in range(1, len(r)):
        r[i] = 0.4 * r[i - 1] + rng.standard_normal() * 0.01
    assert variance_ratio(r, 10) > 1.5


def test_variance_ratio_needs_enough_data():
    assert np.isnan(variance_ratio(np.zeros(10), 20))


def test_report_carries_the_variance_ratio_profile():
    report = analyse(gaussian(2000))
    assert report["variance_ratio"]["1"] == 1.0
    assert set(report["variance_ratio"]) == {"1", "2", "5", "10", "20"}


def test_short_series_is_reported_as_insufficient():
    report = analyse(np.zeros(10))
    assert report.get("insufficient") is True


def test_constant_series_does_not_crash():
    report = analyse(np.zeros(500))
    assert np.isfinite(report["std"])
