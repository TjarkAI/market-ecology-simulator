# Integration note: simulation core → view

Status: calibration of the core. This file describes what has changed in `mes/` and
what the view needs from it. It does not replace talking to each other; it only
records the contract.

## Two new views and two new read points

`Simulation.indices` (from [`mes/indices.py`](mes/indices.py)) is rebuilt on every
reset and updated on every step. It draws **no random numbers** and changes no
state: the same seed gives a bit-identical run with and without it, and
`tests/test_indices.py` checks that through the RNG state.

`mes/traders.py` is to `/traders` what `mes/city.py` is to the town: the only point
at which simulation state becomes display figures. Sorting, filtering and paging
live there, not in the browser.

Important for the view:

- **`Agent.start_equity`** is new: the equity at spawn.
  `Agent.last_wealth` is the baseline of the strategy review and moves with every
  review, so it is no use as a comparison for "how has this trader done".
- **`Market.step_orders`** counts orders per book. `Simulation.step_orders` counts
  them across all markets; the town line mixed the two.
- **`Simulation.script_source`** holds the scenario timeline unconsumed, so that a
  recording can write it down and a replay can put it back.
- **`Simulation.cfg_start`** is the configuration the run *started* with.
  `Config.update_live` changes the object in place, but the recording format needs
  the initial state.

## Two new agent groups

`Simulation.group_of()` now returns seven groups instead of five:

| Group | Class | Role | Why it exists |
|---|---|---|---|
| `momentum` | `AdaptiveTrader` | trend following | as before |
| `value` | `AdaptiveTrader` | valuation | as before |
| `noise` | `NoiseTrader` | noise | as before |
| `passive` | `PassiveInvestor` | ETF / savings plan | as before |
| `leveraged` | `LeveragedFund` | leverage, margin calls | as before |
| **`maker`** | `MarketMaker` | **new**: two-sided quotes | without it the book had ~600 shares of depth against orders of several thousand; every order cleared the book, and volatility was 129% a year |
| **`company`** | `Company` | **new**: Issuer | without it there was no supply of shares: value investors sold their holdings down to nothing, market makers ran into their inventory limit, and then the price rose unchecked to twice the fundamental value |

Both trade on **every** step (`Simulation.always_active`), not according to
`activation_rate`. Otherwise their effect disappears between turns.

Points to note for the display:

- **Market makers** may hold negative positions (down to `mm_inventory_limit`).
  A negative position is a short position.
- **The Issuer** holds systematically negative positions. That is not a bug:
  `-shares` **is** the free float it has issued. Its capital sits in its cash.
- `Simulation.strategy_performance()` now derives the groups from the population
  instead of from a fixed list, so new types no longer silently drop out of the
  comparison.

**Done:** `city.py` now knows the two districts `mkr` and `cmp`, in `_ROADS`,
`capital` and `rooms`. The sum check in the test clips each agent at 0, as
`_equity_by_group` does, because leveraged funds can have negative equity.

## Price, quotes and bars

- `sim.price` is the **mid of the order book**, not the last trade price.
  Marking to the last trade produced an autocorrelation of −0.29 in the returns
  that was pure microstructure.
- `sim.last_trade` is the last actual execution price, the right value for the
  tape and the order book display.
- **New: `sim.bars`**: daily OHLC (`t, step, o, h, l, c, v`). A day is
  `cfg.steps_per_day` steps (default 240). The close is averaged over the last
  5% of the day, like a closing auction.
- **New: `sim.daily_returns`**: the series the validation computes on.
  The stylized facts are properties of *daily* returns; at step level every
  measure comes out wrong.
- **New: `sim.fitness`**: `{"momentum": float, "value": float}`, how well each
  rule would have done lately. Drives strategy switching and is interesting to
  display: it shows which camp is right at the moment.

## Calibrated defaults

The defaults in `config.py` are now calibrated and **cannot** be changed freely
without re-checking the validation. In particular:

```
steps_per_day        240        a day must hold a full adjustment cycle
fundamental_drift    7%/year    divided by 252*steps_per_day
fundamental_vol      15%/year   divided by sqrt(252*steps_per_day)
chartist_aggression  100        below this the volatility clustering disappears
mm_skew              0.9        inventory lean through order sizes, not prices
passive_inflow       30         about 5% of market capitalisation per year
```

With `steps_per_day=240` a daily bar is produced every 240 steps. For the
validation panel the view should be prepared for fewer than 50 days being
available at the start; `metrics.analyse` then returns `{"insufficient": True}`.

## State of the validation

The return autocorrelation that was listed here as an open point (−0.4) is fixed
with the five sectors. The open point is now the tail index. Both, with how they
were derived, are in the `README.md`.

Some of the defaults above are out of date: `chartist_aggression` is set to 55,
`fundamental_vol` to 60%/year. `mes/config.py` is always binding; the values there
are the ones `scripts/calibrate.py` ran against.


---

# Addendum: five sectors

The core now trades **five instruments** at once. Nothing the view already uses
changes: all single-market accessors keep working and show the first instrument
(`TECH`).

## What stayed the same

`sim.price`, `sim.prices`, `sim.book`, `sim.bars`, `sim.daily_returns`,
`sim.volumes`, `sim.returns`, `sim.recent_trades`, `sim.step_volume`,
`sim.step_trades`, `sim.step_fills`, `sim.trend`, `sim.realized_vol`: all
present, all referring to `sim.primary`. `agent.equity(sim.price)` keeps working:
the float is deliberately ignored and the portfolio is valued at the latest
valuation marks, because a single number cannot answer the question for a
portfolio.

## What is new

| Accessor | Contents |
|---|---|
| `sim.markets` | `dict[symbol, Market]`: book, price series, bars per instrument |
| `sim.symbols` | `['TECH','ENRG','FINL','HLTH','CONS']` |
| `sim.primary` | symbol of the instrument the single-market accessors point to |
| `sim.fair` | fundamental value of the primary instrument (**replaces `sim.world.fundamental`**) |
| `sim.sector_returns()` | daily returns per instrument, input for the heatmap |
| `agent.positions` | `dict[symbol, int]`; `agent.shares` is now the read-only sum |
| `agent.symbol` | set for market makers and issuers, otherwise `None` |
| `GET /api/sectors` | all instruments plus the measured correlation matrix |
| `GET /api/sectors/{symbol}` | one instrument: history, book, tape, its own validation |

**Watch out, a rename:** `sim.world.fundamental` no longer exists. The
fundamental values belong to the instruments; two sources of truth were a real bug
(a headline moved one and not the other). `city.py` has already been adapted.

## Warm-up now runs in the background

The server answers within a few seconds and then fast-forwards the market to 110
trading days in the background. The snapshot has two new fields: `warming` (bool)
and `warmProgress` (0…1). A progress bar would make sense there.

## What is open for the view

The town still draws only the primary instrument. Five sector tiles with a
sparkline, a correlation heatmap and a switch for which sector fills the detail
view would make sense. All the data for them is in `/api/sectors`.


---

# Addendum: Central Bank

New: `mes/centralbank.py`. It does not trade; it sets **one number**, the policy
rate, and that reaches the market through three channels.

## Access

| Accessor | Contents |
|---|---|
| `sim.bank` | the `CentralBank` |
| `sim.bank.rate` | policy rate, annualised (0.02 = 2%). **Derived**, not stored: in manual mode it reads the configuration directly |
| `sim.bank.inflation`, `.output_gap`, `.real_rate`, `.stance` | macro state |
| `sim.bank.to_dict()` | ready for display, everything in **percent**, with `history` for the chart |
| `GET /api/centralbank` | rate, macro, plus duration per sector and the three channels |
| `POST /api/centralbank` | `{"rate": 0.045}` sets it by hand, `{"manual": false}` hands it back to the rule |

`to_dict()` returns percentages (4.5 for 4.5%); the internal fields are decimals
(0.045). For a rate chart, use `history`: a list of
`{step, rate, inflation, output_gap}`, one point every five trading days.

## The three channels

1. **Valuation**: a rate move revalues the fundamental values, with the sector's
   duration. FINL has duration 8.8, ENRG 1.6, so the same decision hits the sectors
   with different force. Driven by the *change* in the rate, not its level: a cut
   gives back what a hike took.
2. **Financing costs**: leveraged funds pay `rate + borrow_spread` on borrowed
   money. Their equity erodes, and margin calls come sooner.
   One-sided: savers earn no interest, because that would inject money into the
   market and shift the calibration for a second-order effect.
3. **Inflows**: `bank.flow_multiplier()` scales the savings-plan inflows. At a 10%
   rate about half as much flows into equities.

## What suggests itself for the view

A panel with the policy rate in large type, inflation and output gap below it as
lines, and a "rule / by hand" switch with a rate slider. The interesting moment is
visible: the bank keeps tightening while inflation is already falling, because the
effect arrives with a delay. The **Rate turn 2022** scenario (`rates2022`) runs
through it: rate peak 8.6%, then recession and an undershoot to below zero
inflation. The rate path is **not** scripted, only the inflation shock.

## Two traps that were hidden here

- **Its own random stream.** The bank draws from its own generator
  (`cfg.seed + 7919`). An optional module that draws from the shared stream shifts
  every later number. Then "bank off" is not the same world without a bank but a
  different world. This bug led to wrong conclusions here twice before it was
  fixed.
- **`macro_shock` is more powerful than it looks.** At 0.02 the rate moved so much
  that the duration revaluation dominated everything else in the model, and the
  validation fell from five criteria to three. The default is now 0.006; scenarios
  turn it up when the rate is the point.


---

# Addendum: individual stocks

`stocks_per_sector` (default **0**) switches between two worlds. At 0 the five
sectors trade themselves; that is the calibrated configuration and remains the
default. Above 0 individual stocks trade (`TECH-1`, `TECH-2`, …) and the sector is
no longer an instrument but a common shock with an index.

## Access

| Accessor | Contents |
|---|---|
| `sim.sectors` | `dict[sector, [symbols]]`; with sector instruments `{"TECH": ["TECH"], …}` |
| `sim.sector_of` | `dict[symbol, sector]` |
| `sim.sector_index(sector)` | equal-weighted price index of the members |
| `sim.sector_fair(sector)` | the same for the fundamental values |
| `sim.inject_news(text, mag, symbol=…)` | `symbol` may be an instrument (`TECH-1`), a **sector** (`TECH`, hits all members) or `None` (market-wide, scaled by beta) |

## `/api/sectors` is now grouped

The flat list is gone. New shape:

```json
{
  "groups": [
    {"sector": "TECH", "tradable": false, "index": 101.82, "fair": 227.75,
     "members": [{"symbol": "TECH-1", "price": 102.44, "beta": 1.46,
                  "duration": 7.5, "stretch": 7.9, "spark": [...], ...}]}
  ],
  "stocks_per_sector": 2,
  "correlation":   {"symbols": [...], "matrix": [[...]], "average": 0.036},
  "within_across": {"within": 0.098, "across": 0.028, ...}
}
```

`tradable` says whether the sector itself is an instrument, so the view does not
have to guess. With `tradable=false` the group has an index but no price of its
own; the individual names under it have both.

`within_across` is the interesting figure with individual stocks: correlation
within a sector against correlation across sectors. None of it is configured.

## What is open for the view

With individual stocks two levels would make sense: sector tiles with an index and,
expandable below them, the individual names. `groups` is shaped for exactly that.

Run time: order flow scales per instrument; ten instruments run at ~225 steps/s
against ~440 with five. A switch in the UI should therefore trigger a restart
(`stocks_per_sector` is deliberately **not** live).


---

# Addendum: what the last round changed

Four corrections that matter for the view.

## Capital scales with the number of markets

`initial_cash` and `initial_shares` now apply **per instrument**, not spread across
all of them. An agent with five markets therefore starts with five times the
capital. The reason: with a fifth of the capital per market, prices could not
follow the fundamental values, and the correlation from the factor model did not
reach the prices (0.07 instead of a realistic 0.4–0.6). Now **0.42**.

For the view this only means that the absolute capital figures in the districts are
five times larger than before. The scale adjusts automatically (`chooseScale`).

## Market makers scale too

They are tied to one instrument, so their capital did not grow with the rest. The
book was too thin by exactly the instrument factor, and volatility doubled. New is
`Agent.scale`: for agents tied to a market, the number of markets, otherwise 1. It
multiplies `mm_quote_size` and the normalisation of the inventory skew.

**Watch out, the two sides of the inventory limit are not the same number.**
`MarketMaker.act` normalises its skew against `mm_inventory_limit * agent.scale`
([`mes/agents.py`](mes/agents.py)), but the hard selling limit in
`Simulation._submit` is `-mm_inventory_limit` **without** `scale`. Under the
defaults with five instruments this means: the maker quotes five times the size,
believes its limit is 30,000 shares and is cut off at 6,000. Its skew barely reaches
0.2 at the cap and can never do its job. In the single-instrument case `scale = 1`
and the two definitions coincide, which is why the originally calibrated market
never showed it.

This is **an open question, not a fix.** Which of the two definitions applies
changes the book depth and with it every figure in the README's validation table,
and `tests/test_simulation.py::test_market_makers_respect_their_inventory_limit`
currently checks the unscaled form. It fails as soon as the other is chosen. This
section therefore describes what the code does, not what it should do.

## Margin calls are active under the defaults

`maintenance_margin` is now **0.38** instead of 0.25. The funds reach ~1.6×
leverage, so their ratio of equity to exposure is about 0.62. A threshold of 0.25
was never touched, and the cascade was dead code. At 0.38 calls come occasionally
(654 over 90,000 steps), at 0.44 on every second step.

The alarm on the Leverage Tower (`alarm`, `mcFg`) therefore fires in normal
operation.

## One random stream per agent

`agent.rng`, seeded from `[seed, aid]`. Invisible to the view, but it makes the
A/B comparison reliable: a parameter without effect now produces bit-identical
runs. The warning in the comparison panel has been reworded accordingly. It no
longer warns about path divergence, only about reading too much into one pair of
seeds.

## Error handling in the frontend

`pull()` in `index.html` did not distinguish between "fetch failed" and "drawing
failed" and reported both as "no backend". That cost me a search for the fault in
the wrong place. Now they are separate: a drawing error reports
"Connected · drawing failed: …" and is also logged to the console.
