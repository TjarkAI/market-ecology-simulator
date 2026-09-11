"""Several sectors trading at once.

The claim being tested is not "five order books exist" but that the couplings
between them are *emergent*: correlation comes out of a shared fair-value factor,
and contagion comes out of a shared balance sheet. Neither is configured, so both
have to be measurable — and the contagion test is written so that it fails if the
mechanism is removed.
"""

import numpy as np
import pytest

from mes import Config, Simulation
from mes.instruments import correlation_matrix


def small(**kwargs) -> Config:
    base = dict(n_adaptive=80, n_noise=60, n_passive=8, n_leveraged=10,
                n_makers=4, seed=5, steps_per_day=40)
    base.update(kwargs)
    return Config(**base)


@pytest.fixture(scope="module")
def sim() -> Simulation:
    s = Simulation(small())
    for _ in range(6000):
        s.step()
    return s


def test_every_sector_has_its_own_book_and_price(sim):
    assert len(sim.markets) == 5
    assert sim.symbols == ["TECH", "ENRG", "FINL", "HLTH", "CONS"]
    for market in sim.markets.values():
        assert market.price > 0
        assert market.book is not sim.market.book or market.symbol == sim.primary
        assert len(market.prices) == sim.t + 1


def test_prices_differ_between_sectors(sim):
    prices = [m.price for m in sim.markets.values()]
    assert len(set(round(p, 4) for p in prices)) > 1, "alle Sektoren identisch"


def test_a_single_symbol_gives_back_the_one_asset_market():
    """The calibrated model is the one-instrument case, so it has to still be
    reachable — and the agents' allocation rule has to reduce to it."""
    # The central bank is switched off: this test is about the agents' allocation
    # rule reducing correctly, and the rate channel repricing fair value would
    # only add noise to that question.
    sim = Simulation(small(symbols=("TECH",), cb_active=0))
    for _ in range(2000):
        sim.step()
    assert len(sim.markets) == 1
    assert sim.primary == "TECH"
    # Half the portfolio in stock at a neutral signal means the price should sit
    # in the neighbourhood of fair value, not at a multiple of it.
    assert 0.5 < sim.price / sim.fair < 2.0


def test_sector_correlation_is_positive_but_not_perfect(sim):
    """Correlation is not configured anywhere: it arrives through the common
    market factor in the fair values and through agents holding everything.

    The band used to be −0.5 to 0.98, which the *absence* of the mechanism also
    satisfies: with the shared factor removed the average sits near zero, well
    inside it. A claim that survives its own refutation is not a test. Positive is
    the claim, so positive is what is asserted — with room for the seed-to-seed
    spread, which on this small population runs 0.06 to 0.31."""
    result = correlation_matrix(sim.sector_returns())
    assert result["average"] is not None
    assert 0.0 < result["average"] < 0.98, result["average"]


def test_agents_hold_portfolios_not_single_positions(sim):
    holders = [a for a in sim.agents if a.kind in ("adaptive", "noise", "passive", "leveraged")]
    spread = [a for a in holders if sum(1 for q in a.positions.values() if q != 0) > 1]
    assert spread, "kein Agent hält mehr als ein Instrument"


def test_makers_and_issuers_stay_in_their_own_market(sim):
    for agent in sim.agents:
        if agent.kind not in ("maker", "company"):
            continue
        assert agent.symbol is not None
        held = {s for s, q in agent.positions.items() if q != 0}
        assert held <= {agent.symbol}, f"{agent.kind} #{agent.aid} handelt fremde Märkte"


def test_a_sector_shock_hits_that_sector_hardest(sim):
    """A headline naming one sector moves its fair value and not the others'."""
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    sim.inject_news("Regulierer eröffnet Verfahren", -0.25, symbol="FINL")
    after = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    assert after["FINL"] < before["FINL"] * 0.85
    assert all(after[s] == before[s] for s in after if s != "FINL")


def test_market_wide_news_scales_with_beta(sim):
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    sim.inject_news("Geopolitische Spannungen eskalieren", -0.10)
    drop = {s: 1 - m.instrument.fundamental / before[s] for s, m in sim.markets.items()}
    assert drop["TECH"] > drop["HLTH"]  # beta 1.4 against 0.7


def test_forced_selling_spreads_across_sectors():
    """The contagion mechanism, stated as a falsifiable claim.

    A leveraged fund in trouble is liquidated at portfolio level, so a fund hurt
    in one sector sells all of them. Set up a fund below its maintenance margin
    with positions everywhere, and every position has to shrink — not only the one
    that caused the problem. If the liquidation were per-instrument this test
    would fail.
    """
    sim = Simulation(small(max_leverage=5.0, maintenance_margin=0.5))
    for _ in range(1500):
        sim.step()

    fund = next(a for a in sim.agents if a.kind == "leveraged")
    fund.positions = {symbol: 500 for symbol in sim.symbols}
    fund.cash = -sum(500 * sim.markets[s].price for s in sim.symbols) * 0.85
    before = dict(fund.positions)

    for _ in range(40):
        sim.step()

    # Every position, not four of five. The docstring above, the README and
    # `_liquidate` all say all of them; the assertion said "at least four", which is
    # the one reading under which a per-instrument liquidation would also pass.
    shrunk = [s for s in sim.symbols if fund.position(s) < before[s]]
    assert len(shrunk) == len(sim.symbols), \
        f"nur {len(shrunk)} von {len(sim.symbols)} Sektoren verkauft: {fund.positions}"
    assert sim.margin_calls > 0


def test_correlation_rises_when_leverage_is_present():
    """Average correlation should be higher with leveraged funds than without,
    because their portfolio-level liquidation couples the sectors. This is a
    directional claim about a mechanism, so it is checked over several seeds
    rather than on one."""
    def average_correlation(n_leveraged: int, seed: int) -> float:
        sim = Simulation(small(n_leveraged=n_leveraged, seed=seed,
                               max_leverage=5.0, maintenance_margin=0.40))
        for _ in range(6000):
            sim.step()
        return correlation_matrix(sim.sector_returns())["average"]

    with_leverage = [average_correlation(40, seed) for seed in (5, 11)]
    without = [average_correlation(0, seed) for seed in (5, 11)]
    # Strictly greater. The old assertion allowed the mean *with* leverage to come
    # out 0.05 below the mean without and still pass, so the test survived the
    # mechanism working in reverse — the one outcome it exists to catch. Measured:
    # 0.38 with, 0.07 without, over these two seeds.
    assert np.mean(with_leverage) > np.mean(without), (
        f"mit Hebel {np.mean(with_leverage):.3f}, ohne {np.mean(without):.3f}"
    )
