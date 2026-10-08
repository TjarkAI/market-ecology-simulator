"""HTTP layer: one simulation, stepped by a clock, read by the city view.

The simulation runs in a background task at a configurable rate; the frontend
polls `/api/state` and draws whatever it gets. Nothing about the market lives
here — this module only starts, stops, steps and serialises.

    uvicorn mes.api:app --reload      # or: python -m mes.api

Endpoints
    GET    /api/state              current city snapshot (see mes/city.py)
    GET    /api/series?n=&symbol=  price / fair value / volume history, one instrument
    GET    /api/bars?n=            daily OHLC candles
    GET    /api/metrics            stylized-fact report (mes/metrics.py)
    GET    /api/sectors            every instrument, grouped, plus the correlations
    GET    /api/sectors/{symbol}   one instrument: history, book, own validation
    GET    /api/indices            every index live: level, fair index, curve, beta
    GET    /api/traders            the whole population, sorted / filtered / paged
    GET    /api/traders/{aid}      one trader in full, read-only
    GET    /api/agents/{aid}       select an agent and return the snapshot
    GET    /api/params             all parameters, their spec, and the defaults
    POST   /api/params             change live parameters, or reset onto new ones
    POST   /api/control            play / pause / speed / step / reset / select / market
    POST   /api/scenario/{name}    inject a quick shock: crash / calm / boom
    GET    /api/scenarios          preset catalogue, grouped
    POST   /api/scenarios/{key}    restart under a preset and queue its events
    POST   /api/news               announce a headline by hand
    GET    /api/centralbank        policy rate, macro state, the three channels
    POST   /api/centralbank        set the rate by hand, or hand it back to the rule
    GET    /api/explain            what is happening, why, and what to watch
    GET    /api/lessons            the guided experiments
    POST   /api/lessons/{key}      set one up and restart under its conditions
    GET    /api/lessons/{key}/check  has it shown what it set out to show?
    GET    /api/compare            the active comparison, if there is one
    POST   /api/compare            run two configurations from the same seed
    POST   /api/compare/advance    run the active pair on for more steps
    DELETE /api/compare            discard it
    POST   /api/compare/sweep      the same pair over several seeds, with signal/noise
    GET    /api/runs               recorded runs on disk
    GET    /api/replay             the open recording, if there is one
    POST   /api/replay             open a recording, recomputed from its seed
    POST   /api/replay/seek        scrub to a step or a day
    DELETE /api/replay             close it
    GET    /                       the city view from web/
    GET    /sectors                the sector view: sectors, correlation, bank, A/B, replay
    GET    /indices                the index board: every index against every other, live
    GET    /traders                the roster: every agent, sortable and filterable
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import city, indices, lessons, metrics, narrator, recorder, scenarios, traders
from .compare import Comparison, sweep_pair
from .instruments import correlation_matrix, correlation_within_and_across
from .config import PARAM_SPEC, Config
from .simulation import Simulation

WEB = Path(__file__).resolve().parent.parent / "web"

SPEEDS = {"1x": 0.5, "4x": 0.125, "16x": 0.03}

# The validation panel needs MIN_DAYS of daily bars before any of its figures
# mean anything — the Hill tail estimator alone wants a hundred observations, and
# the first few dozen days are the run settling down rather than the model
# behaving. With five instruments that is around fifty seconds of computation, far
# too long to block a server start, so only a short warm-up is done up front and
# the rest is caught up in the background at full speed. The market visibly
# fast-forwards, which is a better answer than a blank screen.
MIN_DAYS = 100
WARM_TARGET_DAYS = 110
EAGER_WARMUP_DAYS = 8
# Steps per catch-up chunk while warming. Each chunk blocks the event loop, so this
# is a latency budget rather than a throughput one: 120 steps is around 200 ms.
WARM_CHUNK = 120


class Runner:
    """Owns the simulation and the clock that advances it."""

    def __init__(self) -> None:
        # The plain defaults, deliberately: those are the values that
        # scripts/calibrate.py was run against. Starting the server with anything
        # else — an extra dose of news noise, say — means the market on screen is
        # not the market that was validated, and the figures in the panel stop
        # meaning what the README says they mean. News is a slider.
        self.sim = Simulation(Config())
        self.running = True
        self.speed = "1x"
        self.selected: int | None = None
        self.symbol: str | None = None  # which market the town's read-outs follow
        self.lesson: str | None = None  # the guided experiment currently running
        # Set when stepping the market raised. The clock then stops instead of
        # dying silently — see `loop`.
        self.failure: str | None = None
        self._task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.warm_target = WARM_TARGET_DAYS * self.sim.cfg.steps_per_day
        self.warmup(EAGER_WARMUP_DAYS * self.sim.cfg.steps_per_day)

    def warmup(self, steps: int) -> None:
        for _ in range(steps):
            self.sim.step()

    @property
    def warming(self) -> bool:
        return self.sim.t < self.warm_target

    async def loop(self) -> None:
        """The clock. Survives a step that raises, and says so.

        It used to be a bare `while True` around `sim.step()`. When a step raised —
        which a bad configuration could arrange, see `Config.from_dict` — the task
        died, `/api/state` went on answering happily, the page went on showing
        "RUNNING", and the step counter simply never moved again. A market that has
        stopped has to say that it has stopped.
        """
        while True:
            if self.failure is not None:
                await asyncio.sleep(0.5)
                continue
            try:
                if self.warming:
                    # Pause applies here too. It did not: the warm-up loop stepped
                    # regardless of `running`, so pressing Pause in the first thirty
                    # seconds set the button to ▶, the lamp to PAUSE, and the step
                    # counter went on climbing. A control that reports success and
                    # does nothing is worse than one that is greyed out.
                    if not self.running:
                        await asyncio.sleep(0.1)
                        continue
                    # Catch up as fast as the event loop allows, in chunks so the
                    # server keeps answering while it happens. The chunk was 400,
                    # which is about 600 ms of blocked event loop — long enough that
                    # the analysis page, which waits on five endpoints at once,
                    # showed nothing but "loading …" for the whole warm-up. That is the
                    # first thirty seconds a new reader ever sees.
                    async with self.lock:
                        for _ in range(WARM_CHUNK):
                            self.sim.step()
                            if not self.warming:
                                break
                    await asyncio.sleep(0)
                    continue
                await asyncio.sleep(SPEEDS.get(self.speed, 0.5))
                if self.running:
                    async with self.lock:
                        self.sim.step()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 — the clock must not die quietly
                self.failure = f"{type(error).__name__}: {error}"
                self.running = False

    async def step(self, n: int = 1) -> None:
        async with self.lock:
            for _ in range(max(1, min(n, 5000))):
                self.sim.step()

    async def reset(self, cfg: Config | None = None) -> None:
        """Restart the run. Built first, swapped in second.

        `Simulation.reset` rebuilds in place, so a configuration the model cannot
        build left the *live* simulation half constructed: agents spawned but never
        assigned a strategy, and every later step raising `KeyError: 'base'`. Building
        the replacement before letting go of the running one means a rejected
        configuration costs an error message and nothing else.
        """
        fresh = Simulation(cfg or Config.from_dict(self.sim.cfg.to_dict()))
        async with self.lock:
            self.sim = fresh
            self.failure = None
            # The population is new, so the id that was selected names a different
            # agent or none at all. `_selected` falls back to the first adaptive
            # trader for an unknown id, so the panel went on showing *an* agent
            # under the number of one that no longer existed.
            if self.selected is not None and self.selected not in fresh.by_id:
                self.selected = None
            # The run that was carrying the lesson is gone, so the lesson is over.
            # This was not cleared, and the experiment panel went on marking one as
            # running and checking it against a market it had never set up.
            self.lesson = None
            self.warm_target = WARM_TARGET_DAYS * self.sim.cfg.steps_per_day
            self.warmup(EAGER_WARMUP_DAYS * self.sim.cfg.steps_per_day)

    def snapshot(self) -> dict:
        snap = city.snapshot(self.sim, self.selected, self.symbol)
        snap["running"] = self.running
        snap["speed"] = self.speed
        snap["warming"] = self.warming
        snap["warmProgress"] = round(min(1.0, self.sim.t / max(self.warm_target, 1)), 3)
        snap["lesson"] = self.lesson
        # None while the market is healthy. Anything else means the clock has
        # stopped and the reader deserves to know why rather than watch a frozen
        # step counter and guess.
        snap["failure"] = self.failure
        return snap


runner = Runner()

# Optional side sessions: a two-armed comparison and a replay of a recorded run.
# Deliberately module-level singletons rather than per-client state — this is a
# single-user research tool, and pretending otherwise would add a session layer
# that nothing needs.
comparison: Comparison | None = None
replay: "recorder.Replay | None" = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(runner.loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Market Ecology Simulator", lifespan=lifespan)


# ----------------------------------------------------------------- reading
@app.get("/api/state")
def state() -> dict:
    return runner.snapshot()


@app.get("/api/series")
def series(n: int = 240, symbol: str | None = None) -> dict:
    """Price against fair value, for one instrument.

    `symbol` defaults to the primary market, which is what this returned before it
    took an argument. The town needs the selected one: a chart labelled with the
    market the reader picked and drawn from a different market is the same class of
    bug as the ticker that used to ignore the selection.

    Deliberately separate from `/api/sectors/{symbol}`, which returns the same
    curves plus a full validation report — running the Hill estimator every time a
    chart repaints is not what that endpoint is for.
    """
    sim = runner.sim
    n = max(10, min(n, 5000))
    market = sim.markets.get((symbol or "").upper(), sim.markets[sim.primary])
    return {
        "symbol": market.symbol,
        "price": [round(p, 2) for p in market.prices[-n:]],
        "fair": [round(f, 2) for f in market.fundamentals[-n:]],
        "volume": market.volumes[-n:],
        "chartist_share": [round(s, 3) for s in sim.chartist_share_hist[-n:]],
    }


@app.get("/api/metrics")
def stylized_facts() -> dict:
    """The validation report, measured on daily bars.

    There is deliberately no fall-back to per-step returns. The stylized facts
    are properties of *daily* returns; on step-level data the same code reports
    an excess kurtosis of 86 and a tail index of 0.85, and a panel showing those
    numbers with green ticks next to them would be worse than an empty one. Until
    MIN_DAYS days have accumulated the report says so and lists nothing.
    """
    sim = runner.sim
    days = len(sim.daily_returns)

    if days < MIN_DAYS:
        return {
            "insufficient": True,
            "days": days,
            "min_days": MIN_DAYS,
            "basis": f"{days} of {MIN_DAYS} days",
            "note": "The stylized facts apply to daily returns. Not enough data yet.",
            "stylized_facts": [],
            "wealth": sim.wealth_stats(),
            "strategies": sim.strategy_performance(),
        }

    report = metrics.analyse(
        np.array(sim.daily_returns),
        np.array([bar["v"] for bar in sim.bars[1:]]),
    )
    report["days"] = days
    report["basis"] = f"{days} days"
    report["wealth"] = sim.wealth_stats()
    report["strategies"] = sim.strategy_performance()
    report["fitness"] = {k: round(v, 6) for k, v in sim.fitness.items()}
    return report


@app.get("/api/bars")
def bars(n: int = 120, symbol: str | None = None) -> dict:
    """Daily OHLC candles, for one instrument.

    A day is `steps_per_day` steps. The close is averaged over the last few
    steps of the day, the way a closing auction aggregates — a single-instant
    close carries enough quote flicker to distort the daily statistics.

    `symbol` defaults to the primary market, which is what this returned before it
    took an argument. The candle view in the town needs the selected one, for the
    same reason the line chart does: a chart labelled TECH drawn from ENRG is a bug,
    not a detail.
    """
    sim = runner.sim
    market = sim.markets.get((symbol or "").upper(), sim.markets[sim.primary])
    return {
        "symbol": market.symbol,
        "bars": market.bars[-max(1, min(n, 2000)):],
        "steps_per_day": sim.cfg.steps_per_day,
        "days": len(market.bars),
    }


@app.get("/api/sectors")
def sectors() -> dict:
    """Every instrument, grouped by sector, plus the correlation between them.

    Two shapes come out of the same endpoint because the model has two: with
    `stocks_per_sector` at 0 each sector *is* the instrument, above 0 the sector is
    a group of stocks with an index but no price of its own. `tradable` says which,
    so the view does not have to guess.

    The correlations are measured, not configured. `within_across` is the one worth
    reading with individual stocks: two names in a sector share its shock, so they
    should move together more than two names in different sectors — and nothing in
    the model says that directly.
    """
    sim = runner.sim
    spd = sim.cfg.steps_per_day

    def row(symbol: str) -> dict:
        market = sim.markets[symbol]
        recent = market.prices[-2 * spd:]
        change = (market.price / recent[0] - 1.0) * 100 if recent else 0.0
        return {
            "symbol": symbol,
            "name": market.instrument.name,
            "sector": market.instrument.sector,
            "beta": round(market.instrument.beta, 2),
            "duration": round(sim.bank.duration(market.instrument.rate_sensitivity), 1),
            "price": round(market.price, 2),
            "fair": round(market.instrument.fundamental, 2),
            # A percentage change, not the log distance. `market.stretch()` is a log
            # ratio, which is the right thing to average and the wrong thing to
            # print: at a price a quarter of fair value it reads as "−137 %", and
            # a price cannot fall by more than all of it.
            "stretch": round((market.price / max(market.instrument.fundamental, 1e-9) - 1) * 100, 1),
            "change": round(change, 2),
            "volume": market.step_volume,
            "depth": sum(market.depth()),
            "spark": [round(p, 2) for p in market.prices[-60:]],
            "days": len(market.bars),
        }

    groups = []
    for sector, members in sim.sectors.items():
        tradable = members == [sector]
        groups.append({
            "sector": sector,
            "name": sim.markets[members[0]].instrument.sector if tradable else sector,
            "tradable": tradable,
            "index": round(sim.sector_index(sector), 2),
            "fair": round(sim.sector_fair(sector), 2),
            "members": [row(symbol) for symbol in members],
        })

    return {
        "groups": groups,
        "stocks_per_sector": sim.cfg.stocks_per_sector,
        "correlation": correlation_matrix(sim.sector_returns()),
        "within_across": correlation_within_and_across(sim.sector_returns(), sim.sector_of),
        "primary": sim.primary,
    }


@app.get("/api/sectors/{symbol}")
def sector(symbol: str, n: int = 240) -> dict:
    """One instrument's history and its own validation report."""
    sim = runner.sim
    market = sim.markets.get(symbol.upper())
    if market is None:
        raise HTTPException(404, f"unknown instrument: {symbol}")
    n = max(10, min(n, 5000))

    days = len(market.daily_returns)
    report = None
    if days >= MIN_DAYS:
        report = metrics.analyse(
            np.array(market.daily_returns),
            np.array([bar["v"] for bar in market.bars[1:]]),
        )
    return {
        "symbol": market.symbol,
        "name": market.instrument.name,
        "price": [round(p, 2) for p in market.prices[-n:]],
        "fair": [round(f, 2) for f in market.fundamentals[-n:]],
        "volume": market.volumes[-n:],
        "bars": market.bars[-120:],
        "trades": market.recent_trades[-30:],
        "bids": market.book.depth(1, 10),
        "asks": market.book.depth(-1, 10),
        "days": days,
        "metrics": report,
    }


@app.get("/api/indices")
def index_book(n: int = 1200, scale: str = "step", points: int = 400) -> dict:
    """Every index, live: the level, the fair-value index beside it, and the curve.

    Two separate numbers, and conflating them is a bug worth naming: `n` is how far
    back the window reaches — steps at `scale=step`, days at `scale=day` — and
    `points` is how many samples come back. One parameter for both means asking for
    a five-day chart with a thousand points quietly returns the whole run thinned to
    a thousand points instead, drawn under a label that says five days.

    `scale=step` is the live view; `scale=day` is built from the daily closes, which
    is also the frequency the volatility, the drawdown and the betas are measured at.

    The betas are the interesting column. `betaSpec` is what the factor model was
    *given* for that sector's fair value; `beta` is what a regression of the index's
    daily returns on the market index's actually produces. They are not the same
    number and the gap is a result, not a defect — see `mes/indices.py`.
    """
    sim = runner.sim
    n = max(2, min(n, 200_000))
    points = max(10, min(points, 2000))
    daily = scale == "day"
    book = sim.indices
    market = book.by_key["MKT"]
    spd = max(1, sim.cfg.steps_per_day)

    out = []
    for index in book.indices:
        source, fair_source = ((index.closes, index.fair_closes) if daily
                               else (index.levels, index.fairs))
        betas = [sim.markets[s].instrument.beta for s in index.members]
        weights = index.weights
        out.append({
            "key": index.key,
            "name": index.name,
            "kind": index.kind,
            "members": index.members,
            "weights": {s: round(w, 4) for s, w in weights.items()},
            "level": round(index.level, 2),
            "fair": round(index.fair, 2),
            "gap": round(index.gap * 100, 2),
            # The same question asked of the members instead of the index: the
            # weighted mean of price ÷ fair value, today. It is not the same number
            # as `gap` and it should not be — a chained index compounds a weighted
            # *arithmetic* mean of returns, and the price series are far noisier
            # than the fair values, so the price index accumulates a larger
            # rebalancing premium than the fair index. Over a year that reads as
            # twenty points of mispricing nobody can find in any member. Both are
            # reported so the two can be told apart.
            "gapMembers": round((sum(
                weights.get(s, 0.0) * sim.markets[s].price
                / max(sim.markets[s].instrument.fundamental, 1e-9)
                for s in index.members) - 1.0) * 100, 2),
            "changeDay": round(index.change(spd) * 100, 2),
            "changeWeek": round(index.change(5 * spd) * 100, 2),
            "changeTotal": round(index.total_change * 100, 2),
            "vol": (None if index.annualised_vol() is None
                    else round(index.annualised_vol(), 3)),
            "drawdown": (None if index.max_drawdown() is None
                         else round(index.max_drawdown() * 100, 1)),
            # Null for the market index itself: regressing a series on itself gives
            # 1.00 by construction, and a table that prints it invites the reading
            # that the model produced it.
            "beta": (None if index.kind == "market" else
                     _round(indices.beta(index.daily_returns, market.daily_returns), 2)),
            "corr": (None if index.kind == "market" else
                     _round(indices.correlation(index.daily_returns,
                                                market.daily_returns), 3)),
            # The beta the factor model was given, weighted the same way the index
            # is. For the market index this is the average beta of everything in it,
            # which is 1 only if the sectors happen to average out.
            "betaSpec": round(sum(weights.get(s, 0.0) * b
                                  for s, b in zip(index.members, betas)), 2),
            "days": len(index.closes),
            "series": [round(v, 3) for v in indices.sample(source[-n:], points)],
            "fairSeries": [round(v, 3) for v in indices.sample(fair_source[-n:], points)],
            # How much of the index is pulling its weight: members above their own
            # fair value. An index up 20 % on one member is a different market from
            # one up 20 % on all five, and the level alone cannot tell them apart.
            "breadth": sum(1 for s in index.members
                           if sim.markets[s].price > sim.markets[s].instrument.fundamental),
            "width": len(index.members),
        })

    return {
        "base": indices.BASE,
        "scale": "day" if daily else "step",
        "step": sim.t,
        "day": sim.t // spd,
        "steps_per_day": sim.cfg.steps_per_day,
        "points": len(out[0]["series"]) if out else 0,
        # What the window actually covers, which is not always what was asked for:
        # the run may be younger than `n`, and the per-step history only reaches back
        # MAX_STEPS. A chart labelled "60 days" over a run of twelve has to say twelve.
        "covers": (min(n, len(market.closes)) if daily
                   else min(n, len(market.levels), indices.MAX_STEPS)),
        # The page reads "… points from 110 days".
        "window": (f"{min(n, len(market.closes)):,} days" if daily
                   else f"{min(n, len(market.levels), indices.MAX_STEPS):,} steps"),
        "indices": out,
    }


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


@app.get("/api/traders")
def trader_list(
    sort: str = "equity", order: str = "desc", kind: str | None = None,
    strategy: str | None = None, symbol: str | None = None, q: str | None = None,
    limit: int = 150, offset: int = 0,
) -> dict:
    """The whole population as a table: filtered, sorted and paged on the server.

    Six hundred traders with a position per instrument is a payload nobody needs in
    full to find the largest fund, so the sort and the filters live where the data
    is. `symbol` selects the agents holding — or making a market in — one instrument.

    Read-only. Unlike `/api/agents/{aid}` this does not select anything in the town.
    """
    try:
        return traders.overview(
            runner.sim, sort=sort, order=order, kind=kind, strategy=strategy,
            symbol=symbol, query=q, limit=limit, offset=offset,
        )
    except KeyError as error:
        raise HTTPException(
            400, f"unknown sort: {error.args[0]}. "
                 f"Allowed are {sorted(traders.SORTS)}") from error


@app.get("/api/traders/{aid}")
def trader_detail(aid: int) -> dict:
    """One trader in full, including its position in each instrument."""
    if aid not in runner.sim.by_id:
        raise HTTPException(404, f"no agent #{aid}")
    return traders.detail(runner.sim, aid)


@app.get("/api/centralbank")
def centralbank() -> dict:
    """The policy rate, the macro state it is reacting to, and its three channels.

    `duration` per instrument is what the valuation channel does with the rate: a
    one-point move changes that sector's fair value by roughly that many per cent.
    Reading it next to the rate is the point — the same decision lands differently
    across the market.
    """
    sim = runner.sim
    report = sim.bank.to_dict()
    report["channels"] = {
        "valuation": [
            {
                "symbol": symbol,
                "rate_sensitivity": market.instrument.rate_sensitivity,
                "duration": round(sim.bank.duration(market.instrument.rate_sensitivity), 1),
            }
            for symbol, market in sim.markets.items()
        ],
        "borrow_rate": round((max(0.0, sim.bank.rate) + sim.cfg.borrow_spread) * 100, 2),
        "flow_multiplier": round(sim.bank.flow_multiplier(), 3),
    }
    return report


class RateSetting(BaseModel):
    rate: float | None = None  # annualised, e.g. 0.045; None restores the rule
    manual: bool = True


@app.post("/api/centralbank")
async def set_rate(setting: RateSetting) -> dict:
    """Take the rate off the rule and set it by hand, or hand it back.

    Nothing about the market is scripted by doing this. The rate reaches prices
    only through the three channels, and what the market then does is its answer.
    """
    async with runner.lock:
        if not setting.manual or setting.rate is None:
            runner.sim.cfg.update_live({"cb_manual": 0})
        else:
            runner.sim.cfg.update_live({
                "cb_manual": 1,
                "cb_manual_rate": max(0.0, min(setting.rate, runner.sim.cfg.max_rate)),
            })
    return runner.sim.bank.to_dict()


@app.get("/api/explain")
def explain() -> dict:
    """What is happening, why, and what to watch — in plain English.

    Exists because a visualisation shows state, and state is not insight: you had to
    know the model already to read the town. Every sentence here comes from a number
    the simulation holds, and "high" or "unusual" is measured against this run's own
    history rather than a constant.
    """
    return narrator.explain(runner.sim)


@app.get("/api/lessons")
def lesson_catalogue() -> dict:
    """The guided experiments: question, setup, what to watch — and how long they take.

    The clock block is not decoration. Every lesson recommends between 45 and 70
    trading days, and at 1× that is two to five hours of wall clock while the panel
    says only "recommended: 70 trading days". A recommendation nobody can price is a
    recommendation nobody follows, so the arithmetic is shipped from here, where
    SPEEDS actually lives, rather than duplicated into two pages.
    """
    per_day = runner.sim.cfg.steps_per_day
    return {
        "lessons": [{**lesson, "steps": lesson["days"] * per_day}
                    for lesson in lessons.catalogue()],
        "clock": {
            "steps_per_day": per_day,
            # Seconds of sleep per step. The step itself costs about a millisecond,
            # which only matters at 16× and is included so the estimate does not
            # read low exactly where people rely on it.
            "seconds_per_step": {name: round(delay + 0.0015, 4)
                                 for name, delay in SPEEDS.items()},
            "fastest": "16x",
        },
    }


@app.post("/api/lessons/{key}")
async def start_lesson(key: str) -> dict:
    """Set a lesson up and restart the market under its conditions."""
    lesson = lessons.get(key)
    if lesson is None:
        raise HTTPException(404, f"unknown experiment: {key}")
    async with runner.lock:
        if lesson.scenario:
            scenario = scenarios.get(lesson.scenario)
            runner.sim.load_scenario(scenario)
            if lesson.setup:
                runner.sim.cfg.update_live(lesson.setup)
        else:
            # Built on the calibrated defaults, not on whatever is running. Basing
            # it on the live config made every lesson inherit the previous one:
            # start "no market makers", then start "no issuer", and the second
            # experiment quietly ran without makers too — with its own panel
            # reporting on a market it had not arranged.
            cfg = Config.from_dict({**Config().to_dict(),
                                    "seed": runner.sim.cfg.seed,
                                    **lesson.setup})
            runner.sim.reset(cfg)
        # A lesson restarts the market, and a restarted market is not the one that
        # broke. Leaving the old failure set left the clock parked for ever with an
        # error message from a simulation that no longer exists.
        runner.failure = None
        runner.lesson = key
        runner.warm_target = 0  # a lesson is watched from its beginning
        runner.warmup(EAGER_WARMUP_DAYS * runner.sim.cfg.steps_per_day)
    return {**lesson.to_dict(), "started": True,
            "day": runner.sim.t // max(1, runner.sim.cfg.steps_per_day)}


@app.get("/api/lessons/{key}/check")
def check_lesson(key: str) -> dict:
    """Has the experiment shown what it set out to show? Measured, not asserted."""
    if key not in lessons.ALL:
        raise HTTPException(404, f"unknown experiment: {key}")
    sim = runner.sim
    result = lessons.evaluate(key, sim)
    day = sim.t // max(1, sim.cfg.steps_per_day)
    needed = lessons.get(key).days
    result["day"] = day
    result["days_needed"] = needed
    # How much longer, at the speed the clock is actually set to. "Day 12 of 70"
    # says nothing about whether that is two minutes away or two hours.
    remaining = max(0, needed - day) * sim.cfg.steps_per_day
    result["steps_left"] = remaining
    result["seconds_left"] = round(remaining * (SPEEDS.get(runner.speed, 0.5) + 0.0015))
    result["speed"] = runner.speed
    return result


@app.get("/api/agents/{aid}")
def agent(aid: int) -> dict:
    if aid not in runner.sim.by_id:
        raise HTTPException(404, f"no agent #{aid}")
    runner.selected = aid
    return runner.snapshot()


@app.get("/api/params")
def params() -> dict:
    """Current values, the spec the panel is built from, and the defaults.

    The defaults are shipped because they are not an arbitrary starting point: they
    are the values `scripts/calibrate.py` was run against, so they are the only
    configuration for which the figures in the README mean what it says they mean.
    Without them a reader who moved four sliders had no way back.
    """
    return {"values": runner.sim.cfg.to_dict(), "spec": PARAM_SPEC,
            "defaults": Config().to_dict()}


# ----------------------------------------------------------------- writing
class ParamPatch(BaseModel):
    # Deliberately not `dict[str, float]`. That rejected any body containing
    # `symbols: null` — which is what a caller sends when it hands back the whole
    # default configuration — with a 422 naming a field it never meant to set.
    # `Config.from_dict` ignores unknown keys and coerces the rest, and
    # `update_live` only applies what PARAM_SPEC declares, so both paths are
    # already safe against whatever arrives here.
    values: dict[str, object]
    reset: bool = False


@app.post("/api/params")
async def set_params(patch: ParamPatch) -> dict:
    if patch.reset:
        cfg = Config.from_dict({**runner.sim.cfg.to_dict(), **patch.values})
        try:
            await runner.reset(cfg)
        except (TypeError, ValueError, KeyError, IndexError) as error:
            # A rejected configuration is a 400, not a 500, and the market that was
            # running is still running — `Runner.reset` builds before it swaps.
            raise HTTPException(
                400, f"configuration cannot be built: {type(error).__name__}: {error}"
            ) from error
        return {"applied": sorted(patch.values), "reset": True}
    # All or nothing, and a bad value is a 400. `update_live` casts as it goes, so
    # a patch of three parameters whose second one is unparseable used to set the
    # first, raise a 500 on the second and leave the third untouched — a partially
    # applied configuration behind an error message that named none of it.
    try:
        applied = runner.sim.cfg.update_live(patch.values)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            400, f"value not usable: {type(error).__name__}: {error}"
        ) from error
    return {"applied": applied, "reset": False}


class Control(BaseModel):
    action: str  # play | pause | step | reset | speed | select | market
    n: int = 1
    speed: str | None = None
    agent: int | None = None
    symbol: str | None = None


@app.post("/api/control")
async def control(cmd: Control) -> dict:
    if cmd.action == "play":
        runner.running = True
    elif cmd.action == "pause":
        runner.running = False
    elif cmd.action == "step":
        await runner.step(cmd.n)
    elif cmd.action == "reset":
        await runner.reset()
    elif cmd.action == "speed":
        if cmd.speed not in SPEEDS:
            raise HTTPException(400, f"speed must be one of {list(SPEEDS)}")
        runner.speed = cmd.speed
    elif cmd.action == "select":
        # Validated, because it was not: any integer was accepted, and `_selected`
        # quietly falls back to the first adaptive agent for an id it does not know.
        # The panel then showed a different agent than the one that was asked for,
        # with nothing anywhere saying so.
        if cmd.agent is not None and cmd.agent not in runner.sim.by_id:
            raise HTTPException(404, f"no agent #{cmd.agent}")
        runner.selected = cmd.agent
    elif cmd.action == "market":
        if cmd.symbol not in runner.sim.markets:
            raise HTTPException(400, f"unknown instrument: {cmd.symbol}")
        runner.symbol = cmd.symbol
    else:
        raise HTTPException(400, f"unknown action: {cmd.action}")
    return runner.snapshot()


@app.post("/api/scenario/{name}")
async def scenario(name: str) -> dict:
    """Shock the world and let the model do the rest.

    `crash` does not script a crash: it drops the fundamental value, turns the
    trend followers up and lets the leverage do the cascading. Whether the
    price falls 5 % or 40 % is the simulation's answer, not ours.
    """
    sim = runner.sim
    if name == "crash":
        async with runner.lock:
            # Two channels, because a bubble ignores information: the fundamental
            # value drops for the value camp, and the mood collapses for the trend
            # followers. Which one transmits is up to the market's composition.
            sim.inject_news("Geopolitical tensions escalate", -0.35)
            sim.world.sentiment -= 3.0
            sim.cfg.update_live({"chartist_aggression": 120.0, "activation_rate": 0.35})
            for _ in range(60):
                sim.step()
    elif name == "calm":
        async with runner.lock:
            sim.cfg.update_live({"chartist_aggression": 45.0, "activation_rate": 0.12})
            for _ in range(40):
                sim.step()
    elif name == "boom":
        async with runner.lock:
            sim.inject_news("Central Bank signals rate cut", 0.12)
            sim.cfg.update_live({"chartist_aggression": 110.0})
            for _ in range(60):
                sim.step()
    else:
        raise HTTPException(404, f"unknown shock: {name}")
    return runner.snapshot()


# ---------------------------------------------------------- full scenarios
@app.get("/api/scenarios")
def scenario_catalogue() -> dict:
    """The presets, grouped for the picker.

    Each carries the question it is meant to answer. A scenario sets conditions
    and supplies news; what the price then does is the model's answer, not a
    scripted outcome.
    """
    return {"groups": scenarios.catalogue()}


@app.post("/api/scenarios/{key}")
async def load_scenario(key: str) -> dict:
    """Restart the run under a scenario's conditions and queue its events."""
    scenario = scenarios.get(key)
    if scenario is None:
        raise HTTPException(404, f"unknown scenario: {key}")
    async with runner.lock:
        runner.sim.load_scenario(scenario)
        # A scenario replaces whatever set the market up before it, a lesson
        # included. Leaving `lesson` set left the experiment panel reporting on a
        # market the experiment had not arranged.
        runner.lesson = None
        runner.failure = None
        runner.warm_target = WARM_TARGET_DAYS * runner.sim.cfg.steps_per_day
        runner.warmup(EAGER_WARMUP_DAYS * runner.sim.cfg.steps_per_day)
    return runner.snapshot()


class Headline(BaseModel):
    text: str = "Breaking news"
    magnitude: float = -0.1  # log shock to fair value; negative is bad news


@app.post("/api/news")
async def news(item: Headline) -> dict:
    """Announce a headline by hand.

    It moves fair value and mood, never the price. Each group reads it
    differently and the ETF does not read it at all — what reaches the price is
    whatever the agents decide to trade on.
    """
    magnitude = max(-0.6, min(0.6, item.magnitude))
    async with runner.lock:
        runner.sim.inject_news(item.text[:120], magnitude)
    return runner.snapshot()


# ------------------------------------------------------- comparing two runs
class ComparisonRequest(BaseModel):
    a: dict = {}
    b: dict = {}
    label_a: str = "A"
    label_b: str = "B"
    # Enough that the metrics exist: 5 warm-up days plus the 50 the stylized facts
    # need is 55, and a day is 240 steps. A shorter comparison reports
    # "insufficient" rather than a number, which is correct and useless.
    steps: int = 16_000


@app.post("/api/compare")
def start_comparison(request: ComparisonRequest) -> dict:
    """Run two configurations from the same seed and report the difference.

    Read the `caveat` field in the response before drawing a conclusion: the two
    runs do not stay on the same random path, because how many random numbers the
    agents consume depends on what they decide. Use `/api/compare/sweep` when the
    difference matters.
    """
    global comparison
    # Deliberately not holding `runner.lock` and deliberately a sync endpoint. The
    # arms are their own simulations, so the live one does not need protecting, and
    # a synchronous handler is run in a worker thread — an `async def` doing a
    # minute of arithmetic would freeze every other request including the market.
    steps = max(0, min(request.steps, 200_000))
    comparison = Comparison.build(
        Config.from_dict(runner.sim.cfg.to_dict()),
        request.a, request.b, request.label_a, request.label_b,
    )
    comparison.advance(steps)
    return comparison.to_dict()


@app.get("/api/compare")
def get_comparison() -> dict:
    if comparison is None:
        return {"active": False}
    return {"active": True, **comparison.to_dict()}


class Advance(BaseModel):
    steps: int = 2_000


@app.post("/api/compare/advance")
def advance_comparison(request: Advance) -> dict:
    if comparison is None:
        raise HTTPException(404, "no comparison running")
    comparison.advance(max(0, min(request.steps, 100_000)))
    return comparison.to_dict()


@app.delete("/api/compare")
def clear_comparison() -> dict:
    global comparison
    comparison = None
    return {"active": False}


class SweepRequest(BaseModel):
    a: dict = {}
    b: dict = {}
    steps: int = 16_000
    seeds: list[int] = [1000, 1137, 1274]


@app.post("/api/compare/sweep")
def compare_across_seeds(request: SweepRequest) -> dict:
    """The honest A/B: the same pair over several seeds.

    `signal_to_noise` per figure is what to read — above one the gap stands out
    from the seed-to-seed spread, below one it does not, whatever a single pair of
    charts looks like.
    """
    return sweep_pair(
        Config.from_dict(runner.sim.cfg.to_dict()),
        request.a, request.b,
        steps=max(500, min(request.steps, 60_000)),
        seeds=request.seeds[:6],
    )


# -------------------------------------------------------------- replaying a run
@app.get("/api/runs")
def runs() -> dict:
    """Recorded runs on disk, newest first."""
    return {"runs": recorder.catalogue()}


class ReplayRequest(BaseModel):
    path: str


@app.post("/api/replay")
def open_replay(request: ReplayRequest) -> dict:
    """Open a recorded run.

    Recomputed from its seed rather than read back from a series, so every position
    has the whole state — the book, the districts, the agents — not just the curves
    that happened to be exported.
    """
    global replay
    try:
        replay = recorder.Replay.open(request.path)
    except (FileNotFoundError, OSError, KeyError) as error:
        raise HTTPException(404, f"recording not readable: {error}") from error
    return replay.to_dict()


class Seek(BaseModel):
    step: int | None = None
    day: int | None = None


def _replay_frame() -> dict:
    """One replay position, shaped exactly like `/api/state`.

    A recording is recomputed rather than read back, so every position holds the
    whole state — the book, the districts, the agents. That was already true and
    unusable: the payload was a bare `city.snapshot`, missing the five fields the
    HTTP layer adds, so the town could not draw it without special-casing every
    read-out. Shaped like the live state, the town draws a replay position with the
    same code path it draws the live market with.

    The market and the agent follow the town's own selection, because "which market
    am I looking at" is a question about the view and not about which simulation is
    behind it. The curves ride along for the same reason the order book does: they
    exist in this simulation, and a second request for them would only be able to
    answer from the live one.
    """
    snap = city.snapshot(replay.sim, runner.selected, runner.symbol)
    market = replay.sim.markets[snap["focus"]]
    snap.update(
        running=False, speed=runner.speed, warming=False, warmProgress=1.0,
        lesson=None, failure=None,
        replay=replay.to_dict(),
        series={
            "symbol": market.symbol,
            "price": [round(p, 2) for p in market.prices[-240:]],
            "fair": [round(f, 2) for f in market.fundamentals[-240:]],
        },
        bars={"symbol": market.symbol, "bars": market.bars[-120:],
              "days": len(market.bars)},
    )
    return snap


@app.post("/api/replay/seek")
def seek_replay(request: Seek) -> dict:
    """Scrub to a step or a day.

    Sync rather than async, and without the runner lock: seeking backwards
    recomputes from the start, which can be tens of thousands of steps, and the
    replay is its own simulation.
    """
    if replay is None:
        raise HTTPException(404, "no replay open")
    if request.day is not None:
        replay.seek(request.day * max(1, replay.cfg.steps_per_day))
    elif request.step is not None:
        replay.seek(request.step)
    return {**replay.to_dict(), "snapshot": _replay_frame()}


@app.get("/api/replay")
def get_replay() -> dict:
    if replay is None:
        return {"active": False}
    return {"active": True, **replay.to_dict(), "snapshot": _replay_frame()}


@app.delete("/api/replay")
def close_replay() -> dict:
    global replay
    replay = None
    return {"active": False}


# ------------------------------------------------------------------ the app
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/sectors")
def sector_view() -> FileResponse:
    """The sector view. A separate page rather than an addition to the town: the
    town draws one market and reads well doing it, and the two answer different
    questions."""
    return FileResponse(WEB / "sectors.html")


@app.get("/indices")
def index_view() -> FileResponse:
    """The index board: every index on one rebased axis, live.

    Separate from `/sectors` for the same reason `/sectors` is separate from the
    town. That page compares instruments as instruments — price, book, candles,
    correlation. This one asks the only question a level answers: which of these
    ran, when, and against what.
    """
    return FileResponse(WEB / "indices.html")


@app.get("/traders")
def trader_view() -> FileResponse:
    """The roster: the whole population as one table.

    The town shows one agent at a time, which is right for reading a decision and
    useless for reading a population.
    """
    return FileResponse(WEB / "traders.html")


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


def main() -> None:
    import uvicorn

    uvicorn.run("mes.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
