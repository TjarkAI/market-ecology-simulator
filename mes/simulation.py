"""The simulation loop.

One `step()` is one market period: the world moves, margin calls are enforced, a
random subset of agents decides, their orders hit the books, and whatever trades
happen determine the new prices. There is no price equation anywhere.

Several instruments trade at once. Each has its own order book and price history
(`mes/market.py`); what spans them lives here, because that is where the couplings
are — one portfolio, one margin test across all positions, one strategy review.
The contagion between sectors comes out of that shared balance sheet rather than
out of a correlation matrix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .agents import KIND_TO_CLASS, Agent, LeveragedFund, MarketCtx, Quote
from .centralbank import CentralBank
from .config import Config
from .indices import IndexBook
from .instruments import FactorWorld, build
from .market import Market
from .orderbook import BUY, SELL
from .world import World


@dataclass
class Event:
    ts: int
    kind: str  # margin_call | wipeout | switch_wave | news | scenario
    text: str
    severity: float = 0.5
    symbol: str | None = None

    def to_dict(self) -> dict:
        return {"ts": self.ts, "kind": self.kind, "text": self.text,
                "severity": round(self.severity, 3), "symbol": self.symbol}


class Simulation:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.reset()

    # ------------------------------------------------------------- setup
    def reset(self, cfg: Config | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        cfg = self.cfg

        self.rng = np.random.default_rng(cfg.seed)
        self.t = 0
        # The configuration this run *started* from, snapshotted rather than
        # referenced. `Config.update_live` mutates in place, so the live object no
        # longer describes step 0 as soon as a scripted `params` action fires or a
        # slider moves — and a recording that saved the live object saved a
        # configuration the run never actually began with, then replayed the script
        # on top of it and applied the same change twice.
        self.cfg_start: dict = dict(cfg.to_dict())

        self.instruments = build(
            cfg.initial_price, cfg.symbols,
            stocks_per_sector=cfg.stocks_per_sector,
            stock_idio_multiple=cfg.stock_idio_multiple,
            rng=self.rng,
        )
        self.markets: dict[str, Market] = {i.symbol: Market(instrument=i) for i in self.instruments}
        self.symbols = list(self.markets)
        self.primary = self.symbols[0]
        # sector -> the instruments in it. With sector instruments each sector maps
        # to itself; with stocks it maps to the names inside it.
        self.sectors: dict[str, list[str]] = {}
        for instrument in self.instruments:
            self.sectors.setdefault(instrument.sector, []).append(instrument.symbol)
        self.sector_of = {i.symbol: i.sector for i in self.instruments}

        # The old single-asset World still owns sentiment and the news feed; the
        # factor model owns the fair values.
        self.world = World(cfg=cfg, rng=self.rng)
        self.bank = CentralBank(cfg=cfg)  # own random stream, see centralbank.py
        self._prev_stance = self.bank.stance
        self.factors = FactorWorld(
            instruments=self.instruments,
            rng=self.rng,
            drift=cfg.fundamental_drift,
            vol=cfg.fundamental_vol,
            sector_vol=cfg.sector_vol,
        )

        self._spawn_agents()

        self.trend = 0.0  # primary market's, kept for the city view
        self.realized_vol = 0.0
        self.fitness: dict[str, float] = {"momentum": 0.0, "value": 0.0}
        self._review_price: float | None = None
        self._review_signs: tuple[float, float] = (1.0, 1.0)

        self.script: list[tuple[int, dict]] = []
        # The timeline as it was loaded, never consumed. `script` is popped as the
        # run passes each entry, so by the end of a run it is empty — and a recorder
        # that saved it saved nothing. A recording of a scenario then replayed
        # without its headlines: the same seed, a different market, and no way to
        # tell from the file.
        self.script_source: list[tuple[int, dict]] = []
        self.scenario_key: str | None = None
        self.events: list[Event] = []
        self.margin_calls = 0
        self.wipeouts = 0
        self.step_margin_calls = 0
        self.switched_last_review = 0

        self.chartist_share_hist: list[float] = [cfg.initial_chartist_share]
        self.activity = cfg.activation_rate
        self.step_orders = 0
        self.step_orders_by_group: dict[str, int] = {}
        self.last_orders: dict[int, dict] = {}

        # The aggregate view. Built after the markets exist and before the first
        # step, so its base of 100 is the state the run actually starts from.
        # Reading only — it draws no random numbers, so a run with the index book
        # and a run without it are bit-identical.
        self.indices = IndexBook(self.markets, self.sectors)

        for market in self.markets.values():
            market.seed_book(self.rng)
        self._mark_agents()

    def _spawn_agents(self) -> None:
        cfg = self.cfg
        self.agents: list[Agent] = []
        aid = 0

        # A market's capital has to scale with the number of markets in it.
        #
        # Agents spread themselves across the instruments, so with five of them each
        # market saw a fifth of the capital while its fair value diffused exactly as
        # fast as before. The prices could not keep up: technology and financials
        # settled 135 % away from fair value, and because each price was then driven
        # by its own order flow rather than by its fundamental, the correlation the
        # factor model puts into the fair values barely reached the prices at all.
        #
        # Scaling capital and stock by the instrument count gives every market the
        # same depth of pockets the calibrated one-asset market had.
        breadth = len(self.symbols)
        def spawn(kind: str, count: int, cash_mult=1.0, share_mult=1.0, symbol=None):
            nonlocal aid
            cls = KIND_TO_CLASS[kind]
            # An agent tied to one instrument only needs that market's worth of
            # cash, but it has to be *large* enough for that market — so its
            # quoting size scales instead.
            reach = 1 if symbol else breadth
            scale = float(breadth) if symbol else 1.0
            for _ in range(count):
                agent = cls(
                    aid=aid,
                    cash=cfg.initial_cash * cash_mult * max(reach, scale)
                         * float(self.rng.lognormal(0, 0.4)),
                    kind=kind,
                    symbol=symbol,
                )
                agent.scale = scale
                agent.bias = float(self.rng.standard_normal())
                # Seeded from the run's seed and the agent's id, so an agent draws
                # the same numbers no matter what any other agent did.
                agent.rng = np.random.default_rng([cfg.seed, agent.aid])
                # Starting stock: `initial_shares` per instrument held, not split
                # between them. An issuer starts flat — its float is what it issues.
                if share_mult > 0:
                    per = cfg.initial_shares * share_mult * scale * float(self.rng.lognormal(0, 0.4))
                    for sym in ([symbol] if symbol else self.symbols):
                        agent.positions[sym] = max(0, int(per))
                self.agents.append(agent)
                aid += 1

        spawn("adaptive", cfg.n_adaptive)
        spawn("noise", cfg.n_noise, cash_mult=0.5, share_mult=0.5)
        spawn("passive", cfg.n_passive, cash_mult=0.2, share_mult=3.0)
        spawn("leveraged", cfg.n_leveraged, cash_mult=8.0, share_mult=4.0)

        # Makers and issuers are tied to one instrument each: standing depth and
        # share supply are properties of a specific market, not of the whole
        # portfolio. `n_makers` is therefore per instrument.
        for symbol in self.symbols:
            spawn("maker", cfg.n_makers, cash_mult=20.0, share_mult=10.0, symbol=symbol)
            # `n_companies`, not a literal 1. The parameter was declared, documented
            # as "the only source of new share supply" and never read, so the one
            # experiment the README says the issuer exists for — take it away and
            # watch the price settle at twice fair value — could not be run.
            spawn("company", cfg.n_companies, cash_mult=30.0, share_mult=0.0,
                  symbol=symbol)

        for agent in self.agents:
            if agent.kind == "adaptive":
                agent.strategy = "momentum" if self.rng.random() < self.cfg.initial_chartist_share else "value"
            else:
                agent.strategy = agent.kind

        self.by_id = {a.aid: a for a in self.agents}
        self.makers = [a for a in self.agents if a.kind == "maker"]
        self.always_active = [a for a in self.agents if a.kind in ("maker", "company")]
        for agent in self.agents:
            agent.marks = {s: self.markets[s].price for s in self.symbols}
            agent.last_wealth = agent.equity()
            agent.start_equity = agent.last_wealth

    def _mark_agents(self) -> None:
        """Refresh every agent's price marks once per step, so equity can be asked
        for without threading prices through every call."""
        marks = {s: m.price for s, m in self.markets.items()}
        self._marks = marks
        for agent in self.agents:
            agent.marks = marks

    # -------------------------------------------------------------- step
    def step(self) -> None:
        cfg = self.cfg
        self.t += 1
        self._run_script()
        self.world.step(self.t)  # sentiment and the news feed
        self.bank.step(self.t)

        self.factors.drift = cfg.fundamental_drift
        self.factors.vol = self.world.effective_vol or cfg.fundamental_vol
        self.factors.sector_vol = cfg.sector_vol
        # Channel one: when the rate moves, fair values reprice — harder for a
        # long-duration sector. Driven by the *change* in the stance, so a cut
        # gives back what a hike took, and passed per instrument so the same
        # decision lands differently across the market.
        stance_change = self.bank.stance - self._prev_stance
        self._prev_stance = self.bank.stance
        self.factors.drift_adjust = {
            instrument.symbol: self.bank.valuation_change(instrument.rate_sensitivity, stance_change)
            for instrument in self.instruments
        }
        self.factors.step()

        # Channel two: borrowed money costs something, so a leveraged fund's
        # equity erodes while it waits and margin calls arrive sooner. Charged
        # before the margin test, which is the order it happens in.
        self._charge_funding()

        for market in self.markets.values():
            market.begin_step(self.t)
            market.update_perception(cfg)

        self.step_margin_calls = 0
        self.step_orders = 0
        self.step_orders_by_group = {}

        # Computed once. It used to be computed here and again twenty lines down
        # from the identical expression, which reads as though the second one had a
        # reason to differ from the first.
        self.intensity = self.world.effective_vol / max(cfg.fundamental_vol, 1e-12)
        ctx = self._context()
        self._enforce_margin()

        # Trading activity rises when information is arriving quickly — Clark's
        # (1973) mixture-of-distributions argument: volume and volatility are both
        # consequences of the news rate rather than of each other.
        #
        # Scaled by the number of instruments so that each book sees the same flow
        # it would in a one-asset market. Agents trade one instrument per turn, so
        # without this every book would get a fraction of the order flow the model
        # was calibrated with.
        busyness = float(np.clip(self.intensity ** cfg.activity_elasticity, 0.25, 4.0))
        self.activity = min(1.0, cfg.activation_rate * busyness * len(self.symbols))

        n_active = max(1, min(len(self.agents), int(len(self.agents) * self.activity)))
        chosen = self.rng.choice(len(self.agents), size=n_active, replace=False)
        acting = [self.agents[i] for i in chosen]
        active_ids = {a.aid for a in acting}
        acting.extend(a for a in self.always_active if a.aid not in active_ids)

        for agent in acting:
            # Pull the agent's stale quotes once per turn, before any new ones go
            # in. Two details matter here and both were bugs first.
            #
            # Once per *turn*, not per order: cancelling inside `_submit` makes a
            # market maker delete its own bid the moment it posts the matching
            # offer, so the book never holds two-sided depth.
            #
            # And on every turn, not only when the agent decides to trade. An
            # agent that has just looked at the market and chosen to sit out no
            # longer stands behind the quote it left last time. Letting those
            # linger until expiry roughly tripled resting depth and pushed the
            # price to nearly twice fair value.
            for symbol in (agent.symbol,) if agent.symbol else self.symbols:
                self.markets[symbol].book.cancel_agent(agent.aid)
            for symbol, side, qty, price in agent.act(ctx):
                self._submit(agent, symbol, side, qty, price)

        for market in self.markets.values():
            market.end_step(cfg)
            market.update_bar(self.t, cfg)

        # After the books have marked and the bars are closed, so the index's day
        # closes on the same step the instruments' do.
        self.indices.step(self.markets, self.t, cfg.steps_per_day)

        primary = self.markets[self.primary]
        self.trend = primary.trend
        self.realized_vol = primary.realized_vol
        self._mark_agents()

        if self.t % max(1, cfg.switch_interval) == 0:
            self._review_strategies()
        self.chartist_share_hist.append(self.chartist_share())

        for item in self.world.news:
            if item.ts == self.t:
                self._log(item.headline, "news", min(1.0, abs(item.magnitude) * 30))

    def _charge_funding(self) -> None:
        rate = self.bank.borrow_rate_per_step()
        if rate <= 0:
            return
        for agent in self.agents:
            if agent.cash < 0:
                agent.cash += agent.cash * rate  # cash is negative: this is a cost

    def _context(self) -> MarketCtx:
        cfg = self.cfg
        total_fair = sum(m.instrument.fundamental for m in self.markets.values()) or 1.0
        quotes = {}
        for symbol, market in self.markets.items():
            # Agents re-quote from scratch each turn, as a real participant would.
            depth_ask, depth_bid = market.depth()
            quotes[symbol] = Quote(
                symbol=symbol,
                mid=market.book.mid(market.price),
                best_bid=market.book.best_bid(),
                best_ask=market.book.best_ask(),
                trend=market.trend,
                vol=market.realized_vol,
                fundamental=market.instrument.fundamental,
                fair_slow=market.perceived_fair,
                depth_ask=depth_ask,
                depth_bid=depth_bid,
                index_weight=market.instrument.fundamental / total_fair,
            )
        return MarketCtx(t=self.t, quotes=quotes, sentiment=self.world.sentiment,
                         flow_multiplier=self.bank.flow_multiplier(),
                         intensity=getattr(self, "intensity", 1.0), cfg=cfg)

    # ---------------------------------------------------------- execution
    def _submit(self, agent: Agent, symbol: str, side: int, qty: int, price: float | None) -> None:
        market = self.markets.get(symbol)
        if market is None or qty <= 0:
            return
        book = market.book
        reference = price or (book.best_ask() if side == BUY else book.best_bid()) or market.price
        reference = max(reference, 0.01)

        if side == BUY:
            if isinstance(agent, LeveragedFund):
                headroom = agent.equity() * self.cfg.max_leverage - agent.exposure()
            else:
                headroom = agent.cash
            qty = min(qty, int(max(headroom, 0.0) // reference))
        else:
            # Only market makers and issuers may go short: a maker has to be able
            # to offer stock into a rally it did not anticipate, and an issuer's
            # negative position *is* the float. Everyone else sells what they own.
            if agent.kind == "maker":
                floor = -self.cfg.mm_inventory_limit
            elif agent.kind == "company":
                floor = -self.cfg.max_issuance
            else:
                floor = 0
            qty = min(qty, max(agent.position(symbol) - floor, 0))

        if qty < 1:
            return

        self.step_orders += 1
        market.step_orders += 1
        group = self.group_of(agent)
        self.step_orders_by_group[group] = self.step_orders_by_group.get(group, 0) + 1
        self.last_orders[agent.aid] = {
            "ts": self.t, "symbol": symbol, "side": side, "qty": qty,
            "price": round(price if price is not None else reference, 2),
        }

        trades, _ = book.submit(self.t, agent.aid, side, qty, price, lifetime=self.cfg.order_lifetime)
        for trade in trades:
            self._settle(market, trade)

    def _settle(self, market: Market, trade) -> None:
        buyer = self.by_id.get(trade.buyer_id)
        seller = self.by_id.get(trade.seller_id)
        notional = trade.price * trade.qty
        if buyer is not None:
            buyer.cash -= notional
            buyer.add(market.symbol, trade.qty)
        if seller is not None:
            seller.cash += notional
            seller.add(market.symbol, -trade.qty)
        market.record_fill(trade)

    @staticmethod
    def group_of(agent: Agent) -> str:
        """Which district an agent lives in. Adaptive agents move between the
        momentum and the value quarter, everyone else stays put."""
        return agent.strategy if agent.kind == "adaptive" else agent.kind

    # ------------------------------------------------------------- margin
    def _enforce_margin(self) -> None:
        """Forced selling when portfolio equity falls below the requirement.

        The test is at portfolio level and so is the liquidation: a fund in trouble
        because of one sector sells all of them, proportionally. That is the
        contagion channel — stress crosses from one market to another through a
        shared balance sheet, not through any correlation that was configured.

        This is also the only place an agent trades without deciding to.
        """
        cfg = self.cfg
        for agent in self.agents:
            if not isinstance(agent, LeveragedFund):
                continue
            equity = agent.equity()
            exposure = agent.exposure()
            if exposure <= 0:
                continue

            if equity <= 0:
                agent.liquidations += 1
                self.wipeouts += 1
                self.step_margin_calls += 1
                self._liquidate(agent, 1.0)
                self._log(f"Fonds #{agent.aid} ausgelöscht", "wipeout", 1.0)
                continue

            if equity / exposure < cfg.maintenance_margin:
                target = equity / max(cfg.maintenance_margin * 1.6, 1e-6)
                fraction = float(np.clip(1.0 - target / exposure, 0.0, 1.0))
                if fraction <= 0:
                    continue
                agent.liquidations += 1
                self.margin_calls += 1
                self.step_margin_calls += 1
                self._liquidate(agent, fraction)

    def _liquidate(self, agent: Agent, fraction: float) -> None:
        sold = 0
        for symbol in self.symbols:
            held = agent.position(symbol)
            if held <= 0:
                continue
            qty = int(max(1.0, held * fraction)) if fraction < 1.0 else held
            qty = min(qty, held)
            market = self.markets[symbol]
            market.book.cancel_agent(agent.aid)
            trades, _ = market.book.submit(self.t, agent.aid, SELL, qty, None, lifetime=1)
            for trade in trades:
                self._settle(market, trade)
                sold += trade.qty
        if sold:
            self._log(f"Margin Call: Fonds #{agent.aid} liquidiert {sold} Stück", "margin_call", 0.8)

    # ------------------------------------------------------------ learning
    def _score_strategies(self) -> None:
        """Score each *strategy* on what it earned over the last review period.

        A strategy is scored on its own merits, not on the average result of the
        agents running it: score by membership and the mechanism collapses as soon
        as a camp empties, because there is then nothing to measure and the
        population can never be drawn back. And the score covers a full review
        interval, not one step — per step the mid barely moves, so trend following
        looks profitable almost by construction. Brock & Hommes (1997).

        Measured on the primary market, which is the index proxy here.
        """
        price = self.markets[self.primary].price
        fair = self.markets[self.primary].instrument.fundamental
        if self._review_price is not None:
            realised = math.log(max(price, 1e-9) / max(self._review_price, 1e-9))
            decay = self.cfg.memory
            for rule, position in (("momentum", self._review_signs[0]), ("value", self._review_signs[1])):
                self.fitness[rule] = decay * self.fitness[rule] + (1 - decay) * position * realised

        self._review_price = price
        self._review_signs = (1.0 if self.trend > 0 else -1.0, 1.0 if fair > price else -1.0)

    def _review_strategies(self) -> None:
        cfg = self.cfg
        self._score_strategies()

        for agent in self.agents:
            wealth = agent.equity()
            growth = (wealth - agent.last_wealth) / max(abs(agent.last_wealth), 1.0)
            agent.perf = cfg.memory * agent.perf + (1 - cfg.memory) * growth
            agent.last_wealth = wealth

        scale = abs(self.fitness["momentum"]) + abs(self.fitness["value"]) + 1e-12
        momentum_share = self.chartist_share()
        share = {"momentum": momentum_share, "value": 1.0 - momentum_share}

        switched = 0
        for agent in self.agents:
            if agent.kind != "adaptive":
                continue
            other = "momentum" if agent.strategy == "value" else "value"
            # Relative success (Lux & Marchesi 1999) plus the pull of the crowd
            # (Kirman 1993). The herding term is what makes the population
            # bistable, and that persistence is what clusters volatility.
            gap = (self.fitness[other] - self.fitness[agent.strategy]) / scale
            herd = (share[other] - 0.5) * 2.0
            attraction = cfg.switch_intensity * gap + cfg.herd_strength * herd
            p_switch = 1.0 / (1.0 + math.exp(-float(np.clip(attraction, -30.0, 30.0))))
            if self.rng.random() < p_switch * cfg.switch_rate:
                agent.strategy = other
                switched += 1

        self.switched_last_review = switched
        if switched > len(self.agents) * 0.08:
            self._log(f"Strategiewechsel-Welle: {switched} Trader drehen", "switch_wave", 0.6)

    # ----------------------------------------------------------- scenarios
    def load_scenario(self, scenario) -> None:
        """Restart with a scenario's parameters and queue its events."""
        cfg = Config.from_dict({**self.cfg.to_dict(), **scenario.overrides})
        self.reset(cfg)
        day = max(1, cfg.steps_per_day)
        self.install_script(
            [(offset * day, action) for offset, action in scenario.timeline],
            key=scenario.key,
        )
        self._log(f"Szenario geladen: {scenario.name}", "scenario", 0.5)

    def install_script(self, entries, key: str | None = None) -> None:
        """Queue a timeline of scheduled events, keeping a copy of it.

        Separate from `load_scenario` because a replay has to put a recorded
        timeline back after every backward seek — `reset` clears the queue, and a
        recording that came from a scenario is only that recording if its headlines
        arrive again at the same steps.
        """
        self.script = sorted(((int(step), action) for step, action in entries),
                             key=lambda item: item[0])
        self.script_source = list(self.script)
        if key is not None:
            self.scenario_key = key

    def _run_script(self) -> None:
        while self.script and self.script[0][0] <= self.t:
            _, action = self.script.pop(0)
            if "news" in action:
                headline, magnitude = action["news"][0], float(action["news"][1])
                symbol = action["news"][2] if len(action["news"]) > 2 else None
                self.inject_news(headline, magnitude, symbol)
            elif "params" in action:
                applied = self.cfg.update_live(action["params"])
                if applied:
                    self._log("Rahmenbedingungen geändert: " + ", ".join(applied), "scenario", 0.4)
            elif "inflation" in action:
                # Push the macro state, not the rate. What the bank then does is
                # its own decision, and the overshoot is the interesting part.
                self.bank.inflation = float(action["inflation"])
                self._log(f"Inflation springt auf {self.bank.inflation * 100:.1f} %",
                          "scenario", 0.6)
            elif "note" in action:
                self._log(action["note"], "scenario", 0.3)

    def inject_news(self, headline: str, magnitude: float, symbol: str | None = None):
        """Announce a headline now: it moves fair value and mood, never the price.

        Whether the price moves depends on the agents, and they read it
        differently — a value investor sees a cheaper asset, a trend follower sees
        others selling, the ETF does not read it at all. A sector-specific headline
        hits one instrument; a market-wide one is scaled by each instrument's beta,
        so the same news lands differently across the market.
        """
        self.factors.apply_shock(symbol, magnitude)
        item = self.world.apply_news(self.t, headline, magnitude)
        self._log(headline, "news", min(1.0, abs(magnitude) * 30), symbol)
        return item

    # ------------------------------------------------------------- metrics
    def chartist_share(self) -> float:
        adaptive = [a for a in self.agents if a.kind == "adaptive"]
        if not adaptive:
            return 0.0
        return sum(1 for a in adaptive if a.strategy == "momentum") / len(adaptive)

    def fear_greed(self) -> float:
        """0 = panic, 100 = euphoria. A readable composite, not a real index."""
        primary = self.markets[self.primary]
        window = primary.returns[-60:]
        momentum = float(np.mean(window)) * 400 if window else 0.0
        vol_penalty = -primary.realized_vol * 900
        stretch = primary.stretch() * 120
        crowd = (self.chartist_share() - 0.5) * 60
        return float(np.clip(50 + momentum + vol_penalty + stretch * 0.6 + crowd, 0, 100))

    def wealth_stats(self) -> dict:
        wealth = np.array([max(a.equity(), 0.0) for a in self.agents])
        total = wealth.sum()
        if total <= 0:
            return {"gini": 0.0, "top10": 0.0, "deciles": [0.0] * 10}
        sorted_w = np.sort(wealth)
        n = len(sorted_w)
        index = np.arange(1, n + 1)
        gini = float((2 * (index * sorted_w).sum()) / (n * sorted_w.sum()) - (n + 1) / n)
        top10 = float(sorted_w[int(n * 0.9):].sum() / total)
        deciles = [float(chunk.sum() / total) for chunk in np.array_split(sorted_w, 10)]
        return {"gini": gini, "top10": top10, "deciles": deciles}

    def strategy_performance(self) -> dict:
        out: dict[str, dict] = {}
        for label in dict.fromkeys(self.group_of(a) for a in self.agents):
            members = [a for a in self.agents if self.group_of(a) == label]
            wealth = np.array([a.equity() for a in members])
            out[label] = {
                "count": len(members),
                "mean_wealth": float(wealth.mean()),
                "total_wealth": float(wealth.sum()),
            }
        return out

    def sector_returns(self, window: int = 250) -> dict:
        """Daily returns per instrument — the input to the correlation heatmap."""
        return {s: np.array(m.daily_returns[-window:]) for s, m in self.markets.items()}

    def sector_index(self, sector: str) -> float:
        """Equal-weighted price index of a sector.

        With individual stocks the sector is not tradable, so there is no price for
        it — but an index of its members is what one would quote, and it is what the
        view should show above the individual names.
        """
        members = self.sectors.get(sector, [])
        if not members:
            return 0.0
        return sum(self.markets[s].price for s in members) / len(members)

    def sector_fair(self, sector: str) -> float:
        members = self.sectors.get(sector, [])
        if not members:
            return 0.0
        return sum(self.markets[s].instrument.fundamental for s in members) / len(members)

    def _log(self, text: str, kind: str, severity: float = 0.5, symbol: str | None = None) -> None:
        self.events.append(Event(ts=self.t, kind=kind, text=text, severity=severity, symbol=symbol))
        del self.events[:-50]

    # ------------------------------------------- single-instrument views
    # The city view and the older tests were written when there was one market.
    # These delegate to the primary instrument so that code keeps working and
    # keeps meaning what it did.
    @property
    def market(self) -> Market:
        return self.markets[self.primary]

    @property
    def fair(self) -> float:
        """Fair value of the primary instrument. Fair values live with the
        instruments now, so this is the single-market view of them."""
        return self.market.instrument.fundamental

    @property
    def book(self):
        return self.market.book

    @property
    def price(self) -> float:
        return self.market.price

    @property
    def last_trade(self) -> float:
        return self.market.last_trade

    @property
    def prices(self) -> list[float]:
        return self.market.prices

    @property
    def fundamentals(self) -> list[float]:
        return self.market.fundamentals

    @property
    def volumes(self) -> list[int]:
        return self.market.volumes

    @property
    def returns(self) -> list[float]:
        return self.market.returns

    @property
    def bars(self) -> list[dict]:
        return self.market.bars

    @property
    def daily_returns(self) -> list[float]:
        return self.market.daily_returns

    @property
    def recent_trades(self) -> list[dict]:
        return self.market.recent_trades

    @property
    def step_volume(self) -> int:
        return sum(m.step_volume for m in self.markets.values())

    @property
    def step_trades(self) -> int:
        return sum(m.step_trades for m in self.markets.values())

    @property
    def step_fills(self) -> list[dict]:
        return [fill for m in self.markets.values() for fill in m.step_fills]

