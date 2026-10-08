"""Validation against the stylized facts of real financial markets.

This module is what separates the project from a pretty animation. Real
return series share a handful of statistical properties that hold across
assets, markets and centuries. None of them are built into the simulator. If
they show up in the output anyway, the agent interactions are producing
something market-like; if they do not, the model is wrong — regardless of how
convincing the price chart looks.

References: Cont (2001), "Empirical properties of asset returns".
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def autocorr(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag + 2:
        return 0.0
    a, b = x[:-lag], x[lag:]
    sa, sb = a.std(), b.std()
    if sa < 1e-12 or sb < 1e-12:
        return 0.0
    return float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))


def ljung_box(x: np.ndarray, lags: int = 20) -> tuple[float, float]:
    """Test statistic and p-value for 'no autocorrelation up to `lags`'."""
    n = len(x)
    if n <= lags + 2:
        return 0.0, 1.0
    q = 0.0
    for k in range(1, lags + 1):
        r = autocorr(x, k)
        q += r * r / (n - k)
    q *= n * (n + 2)
    return float(q), float(1 - stats.chi2.cdf(q, lags))


def hill_tail_index(x: np.ndarray, tail_frac: float = 0.05) -> float:
    """Hill estimator of the tail exponent of |returns|.

    Real markets sit roughly between 2 and 5. Below 2 the variance does not
    exist; above ~6 the tails are essentially Gaussian.
    """
    x = np.abs(x[np.abs(x) > 0])
    if len(x) < 100:
        return float("nan")
    k = max(10, int(len(x) * tail_frac))
    top = np.sort(x)[-k:]
    threshold = top[0]
    if threshold <= 0:
        return float("nan")
    return float(1.0 / np.mean(np.log(top / threshold) + 1e-12))


def variance_ratio(returns: np.ndarray, k: int) -> float:
    """Lo & MacKinlay variance ratio: Var(k-period return) / (k · Var(1-period)).

    A random walk gives 1 at every horizon. Above 1 means the moves persist
    (trending), below 1 means they are taken back (mean reversion).

    This is the single most informative number about a price series in this
    model, because it separates *permanent* from *transient* variance. A price
    that wanders on its own has permanent variance; a price pushed around by
    order flow and then pulled back has transient variance, and transient
    variance must by definition revert. When the return autocorrelation came out
    at −0.4, this profile was what showed why: strongly above 1 over tens of
    steps, far below 1 over days, meaning most of the price movement was noise
    around a slow anchor rather than genuine repricing.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < k * 4 or k < 1:
        return float("nan")
    single = r.var()
    if single < 1e-24:
        return float("nan")
    # Overlapping k-sums, which is the efficient form of the estimator.
    cumulative = np.concatenate(([0.0], np.cumsum(r)))
    k_sums = cumulative[k:] - cumulative[:-k]
    return float(k_sums.var() / (k * single))


def variance_ratio_profile(returns: np.ndarray, horizons=(1, 2, 5, 10, 20)) -> dict:
    return {str(k): variance_ratio(returns, k) for k in horizons}


def analyse(returns: np.ndarray, volumes: np.ndarray | None = None) -> dict:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 50:
        return {"n": int(len(r)), "insufficient": True}

    abs_r = np.abs(r)
    acf_r = [autocorr(r, k) for k in range(1, 11)]
    acf_abs = [autocorr(abs_r, k) for k in range(1, 21)]
    _, p_r = ljung_box(r, 10)
    _, p_abs = ljung_box(abs_r, 10)

    out = {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "std": float(r.std()),
        "annualised_vol": float(r.std() * np.sqrt(252)),
        "excess_kurtosis": float(stats.kurtosis(r, fisher=True)),
        "skew": float(stats.skew(r)),
        "jarque_bera_p": float(stats.jarque_bera(r).pvalue),
        "acf_returns": acf_r,
        "acf_abs_returns": acf_abs,
        "acf_abs_mean_1_10": float(np.mean(acf_abs[:10])),
        "ljung_box_p_returns": p_r,
        "ljung_box_p_abs": p_abs,
        "hill_tail_index": hill_tail_index(r),
        "max_drawdown": max_drawdown_from_returns(r),
        # Diagnostic rather than a criterion: it explains what the
        # autocorrelation check reports, in units that point at a cause.
        "variance_ratio": variance_ratio_profile(r),
    }

    if volumes is not None and len(volumes) == len(returns):
        v = np.asarray(volumes, dtype=float)[np.isfinite(np.asarray(returns, dtype=float))]
        if v.std() > 1e-9 and abs_r.std() > 1e-9:
            out["volume_volatility_corr"] = float(np.corrcoef(v, abs_r)[0, 1])

    out["stylized_facts"] = check_stylized_facts(out)
    return out


def max_drawdown_from_returns(r: np.ndarray) -> float:
    equity = np.exp(np.cumsum(r))
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def check_stylized_facts(m: dict) -> list[dict]:
    """The acceptance criteria, defined up front so results cannot be
    reinterpreted after the fact.

    A criterion whose statistic cannot be computed yet is reported as not
    measurable rather than as failed — the Hill estimator needs at least a
    hundred observations, and a short sample would otherwise show up as a red
    cross that looks like a property of the model instead of a property of the
    sample size.
    """
    checks = [
        {
            "name": "Fat Tails",
            "detail": "excess kurtosis > 1 (normal distribution = 0)",
            "value": m["excess_kurtosis"],
            "passed": m["excess_kurtosis"] > 1.0,
        },
        {
            "name": "No Return Autocorrelation",
            "detail": "|ACF(1)| of returns < 0.1: the market is not trivially predictable",
            "value": m["acf_returns"][0],
            "passed": abs(m["acf_returns"][0]) < 0.1,
        },
        {
            "name": "Volatility Clustering",
            "detail": "mean ACF of |returns| (lags 1–10) > 0.05",
            "value": m["acf_abs_mean_1_10"],
            "passed": m["acf_abs_mean_1_10"] > 0.05,
        },
        {
            "name": "Non-Normality",
            "detail": "Jarque-Bera p < 0.05: normal distribution rejected",
            "value": m["jarque_bera_p"],
            "passed": m["jarque_bera_p"] < 0.05,
        },
        {
            "name": "Tail Index in Market Range",
            "detail": "Hill estimator between 2 and 6",
            "value": m["hill_tail_index"],
            "passed": 2.0 < m["hill_tail_index"] < 6.0 if np.isfinite(m["hill_tail_index"]) else False,
        },
    ]
    if "volume_volatility_corr" in m:
        checks.append(
            {
                "name": "Volume-Volatility Coupling",
                "detail": "correlation of volume and |return| > 0.1",
                "value": m["volume_volatility_corr"],
                "passed": m["volume_volatility_corr"] > 0.1,
            }
        )

    # NaN is not valid JSON and arrives at the client as null, which then breaks
    # any consumer that formats the number. Anything non-finite becomes an
    # explicit "not measurable yet".
    for check in checks:
        value = check["value"]
        measurable = value is not None and np.isfinite(value)
        check["measurable"] = bool(measurable)
        check["value"] = float(value) if measurable else None
        check["passed"] = bool(check["passed"]) if measurable else False

    return checks
