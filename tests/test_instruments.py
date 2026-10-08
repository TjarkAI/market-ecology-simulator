"""The factor model behind the sector fair values.

What matters here is that correlation between sectors *comes from* the shared
market factor rather than from a matrix someone typed in. So the tests check the
mechanism: remove the common factor and the sectors decouple; remove the
idiosyncratic parts and they move as one.
"""

import numpy as np
import pytest

from mes.instruments import SECTOR_SPEC, FactorWorld, build, correlation_matrix


def world(**kwargs) -> FactorWorld:
    base = dict(
        instruments=build(100.0),
        rng=np.random.default_rng(4),
        drift=0.0,
        vol=0.002,
    )
    base.update(kwargs)
    return FactorWorld(**base)


def returns_of(factor_world: FactorWorld, steps: int = 3000) -> dict:
    """Step the factor world and record the fair values as it goes.

    `FactorWorld` used to keep this series itself, in a dict nothing in `mes/` ever
    read — a byte-identical second copy of `Market.fundamentals`, growing by one
    float per instrument per step for the whole life of a run. The observation
    belongs to whoever wants to observe, which here is the test.
    """
    history: dict[str, list[float]] = {i.symbol: [] for i in factor_world.instruments}
    for _ in range(steps):
        factor_world.step()
        for instrument in factor_world.instruments:
            history[instrument.symbol].append(instrument.fundamental)
    return {
        symbol: np.diff(np.log(np.array(series)))
        for symbol, series in history.items()
    }


def test_five_sectors_by_default():
    instruments = build(100.0)
    assert len(instruments) == len(SECTOR_SPEC) == 5
    assert {i.symbol for i in instruments} == {"TECH", "ENRG", "FINL", "HLTH", "CONS"}
    assert all(i.sector == i.symbol for i in instruments)


def test_a_single_symbol_gives_the_calibrated_one_asset_market():
    instruments = build(100.0, symbols=["TECH"])
    assert len(instruments) == 1 and instruments[0].symbol == "TECH"


def test_unknown_symbols_are_an_error():
    with pytest.raises(ValueError):
        build(100.0, symbols=["GOLD"])


def test_the_common_factor_creates_positive_correlation():
    result = correlation_matrix(returns_of(world()))
    assert result["average"] > 0.15, f"coupled too weakly: {result['average']}"
    assert result["average"] < 0.95, "the sectors are practically identical"


def test_without_idiosyncratic_noise_the_sectors_move_as_one():
    """Betas alone differ, so the returns are proportional — correlation ≈ 1.
    This is the check that the factor structure, not the labelling, does the
    work."""
    factor_world = world(sector_vol=0.0)
    for instrument in factor_world.instruments:
        instrument.idio_vol = 0.0
    assert correlation_matrix(returns_of(factor_world))["average"] > 0.99


def test_high_beta_sector_is_more_volatile():
    result = returns_of(world())
    tech = result["TECH"].std()  # beta 1.4
    health = result["HLTH"].std()  # beta 0.7
    assert tech > health


def test_a_sector_shock_hits_only_that_sector():
    factor_world = world()
    before = {i.symbol: i.fundamental for i in factor_world.instruments}
    factor_world.apply_shock("FINL", -0.30)
    after = {i.symbol: i.fundamental for i in factor_world.instruments}
    assert after["FINL"] < before["FINL"] * 0.8
    assert all(after[s] == before[s] for s in after if s != "FINL")


def test_a_market_wide_shock_scales_with_beta():
    factor_world = world()
    before = {i.symbol: i.fundamental for i in factor_world.instruments}
    factor_world.apply_shock(None, -0.10)
    drop = {s: 1 - i.fundamental / before[s]
            for s, i in ((i.symbol, i) for i in factor_world.instruments)}
    assert drop["TECH"] > drop["HLTH"]  # beta 1.4 vs 0.7


def test_correlation_matrix_is_well_formed():
    result = correlation_matrix(returns_of(world()))
    matrix = result["matrix"]
    assert len(matrix) == 5 and all(len(row) == 5 for row in matrix)
    for i in range(5):
        assert matrix[i][i] == pytest.approx(1.0)
        for j in range(5):
            assert matrix[i][j] == pytest.approx(matrix[j][i])


def test_correlation_needs_enough_data():
    result = correlation_matrix({"A": np.zeros(5), "B": np.zeros(5)})
    assert result["matrix"] is None
