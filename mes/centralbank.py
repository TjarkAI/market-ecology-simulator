"""The central bank, and the small macroeconomy it is reacting to.

It does not trade. It sets one number — the policy rate — and that number reaches
the market through three channels, which is the whole point of modelling it: the
same decision arrives differently depending on which channel dominates.

    1. Valuation      a higher rate discounts future earnings harder, so fair
                      values grow more slowly. Rate-sensitive sectors feel it
                      more (`rate_sensitivity` on each instrument).
    2. Funding        leveraged funds pay interest on borrowed money, so their
                      equity erodes and margin calls come sooner.
    3. Flows          savings plans put less into equities when cash pays.

The macro block matters because it closes the loop. A central bank reacting to an
economy that does not react back is a scripted rate path, and then the interesting
question — does policy over- or undershoot — cannot even be asked. Here a tighter
stance cools output with a lag, cooler output brings inflation down with a further
lag, and by the time inflation responds the bank has usually already moved too far.
That is a property of the delays, not something written in.

Everything is stored in annual terms because that is how rates are read, and
converted per step where it is used. `steps_per_year = 252 * steps_per_day`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import Config


def per_step_decay(half_life_days: float, steps_per_day: int) -> float:
    """AR(1) coefficient for a given half-life, expressed in trading days.

    Writing persistence as a half-life keeps the parameters readable: at 240 steps
    a day, a plausible coefficient is 0.99999-something, which is impossible to
    reason about and easy to typo by an order of magnitude.
    """
    steps = max(1.0, half_life_days * steps_per_day)
    return float(0.5 ** (1.0 / steps))


@dataclass
class CentralBank:
    cfg: Config
    # Its own generator, not the market's. An optional module that draws from the
    # shared stream changes every later draw, so switching it off does not give
    # the same world without a central bank — it gives a different world. That
    # confound cost real time here: a comparison of `cb_active` on and off looked
    # like a dramatic policy effect and was mostly a different random path.
    # With a separate stream, `cb_active` is a clean A/B.
    seed_offset: int = 7919
    rng: np.random.Generator = None

    rule_rate: float = 0.0  # what the Taylor rule has smoothed its way to
    inflation: float = 0.0  # annualised
    output_gap: float = 0.0  # per cent of potential output
    stance_transmission: float = 0.0  # lagged stance, what the economy actually feels
    last_decision: int = 0  # step of the last change worth reporting
    history: list = field(default_factory=list)

    def __post_init__(self):
        if self.rng is None:
            self.rng = np.random.default_rng(self.cfg.seed + self.seed_offset)
        self.rule_rate = float(self.cfg.neutral_rate)
        self.inflation = float(self.cfg.inflation_target)

    # ------------------------------------------------------------------ state
    @property
    def rate(self) -> float:
        """The policy rate in force, annualised.

        Derived rather than stored so that manual mode is authoritative the moment
        it is set. Storing it and copying the manual value across on each step
        meant a rate the user had just moved was still the old one until the next
        step — twice a source of confusing behaviour before this was a property.
        """
        cfg = self.cfg
        if cfg.cb_manual:
            return float(np.clip(cfg.cb_manual_rate, 0.0, cfg.max_rate))
        return self.rule_rate

    @property
    def stance(self) -> float:
        """How restrictive policy is: the rate above or below neutral."""
        return self.rate - self.cfg.neutral_rate

    @property
    def real_rate(self) -> float:
        return self.rate - self.inflation

    def borrow_rate_per_step(self) -> float:
        """What a leveraged fund pays on borrowed money, per step."""
        cfg = self.cfg
        annual = max(0.0, self.rate) + cfg.borrow_spread
        return annual / (252.0 * max(1, cfg.steps_per_day))

    def flow_multiplier(self) -> float:
        """Scale on savings-plan inflows. Cash paying more means less goes into
        equities; the sensitivity is a knob because the real elasticity is small
        and arguing about its size is beside the point here."""
        cfg = self.cfg
        return float(np.clip(1.0 - cfg.inflow_rate_sensitivity * self.stance, 0.0, 3.0))

    def duration(self, rate_sensitivity: float) -> float:
        """Effective duration in years: how far fair value moves per point of rate.

        `rate_valuation_channel` is the duration of a sector with sensitivity 1,
        so at the default of 8 a one-point rise takes 8 % off such a sector's fair
        value and 14 % off technology's.
        """
        return self.cfg.rate_valuation_channel * rate_sensitivity

    def valuation_change(self, rate_sensitivity: float, stance_change: float) -> float:
        """Log change in fair value caused by the rate *moving*.

        Driven by the change, not the level, and that is the whole point. A drag
        proportional to the level would accumulate: hold the rate above neutral
        for a year and valuations would keep falling for as long as it stayed
        there, and a cut back to neutral would never give any of it back. Real
        valuations reprice once when the rate moves and stay there — so a hike
        followed by a cut of the same size leaves fair value where it started,
        which is what this does.
        """
        return -self.duration(rate_sensitivity) * stance_change

    # ------------------------------------------------------------------- step
    def step(self, t: int) -> None:
        cfg = self.cfg
        spd = max(1, cfg.steps_per_day)
        # Drawn before the early return so that the bank's own stream advances the
        # same way whether it is active or not, which keeps `cb_active` a clean
        # comparison rather than a different random world.
        draws = self.rng.standard_normal(2)
        if not cfg.cb_active:
            return

        gap_decay = per_step_decay(cfg.macro_half_life_days, spd)
        transmission_decay = per_step_decay(cfg.policy_lag_days, spd)
        shock_scale = cfg.macro_shock / math.sqrt(252.0 * spd)

        # What the economy feels is not today's rate but a smoothed version of it:
        # this is the transmission lag, and it is why policy overshoots.
        self.stance_transmission = (
            transmission_decay * self.stance_transmission
            + (1 - transmission_decay) * self.stance
        )

        # Output responds to the stance it has actually absorbed.
        self.output_gap = (
            gap_decay * self.output_gap
            - (1 - gap_decay) * cfg.output_rate_response * self.stance_transmission * 100.0
            + shock_scale * float(draws[0])
        )

        # Inflation follows output with its own lag — a Phillips-curve shape.
        self.inflation = (
            gap_decay * self.inflation
            + (1 - gap_decay) * (cfg.inflation_target + cfg.phillips_slope * self.output_gap / 100.0)
            + shock_scale * 0.5 * float(draws[1])
        )

        self._set_rate()

        # `max(1, …)` because `rate_report_days = 0` is a legal value of a real
        # field and a modulo by zero here kills the clock: the step raises, the
        # runner catches it, and the market stops with "ZeroDivisionError" on
        # screen. A reporting cadence is not something a run should die of.
        if t % max(1, spd * cfg.rate_report_days) == 0:
            self.history.append({
                "step": t,
                "rate": round(self.rate, 5),
                "inflation": round(self.inflation, 5),
                "output_gap": round(self.output_gap, 3),
            })
            del self.history[:-400]

    def _set_rate(self) -> None:
        """Advance the rule's rate. Manual mode does not go through here at all —
        `rate` reads the configured value directly."""
        cfg = self.cfg
        # The Taylor rule: lean against inflation above target and against a hot
        # economy, starting from neutral.
        target = (
            cfg.neutral_rate
            + cfg.taylor_inflation * (self.inflation - cfg.inflation_target)
            + cfg.taylor_output * self.output_gap / 100.0
        )
        target = float(np.clip(target, 0.0, cfg.max_rate))

        # Central banks move in small steps rather than jumping to the target.
        smoothing = per_step_decay(cfg.rate_adjust_days, max(1, cfg.steps_per_day))
        self.rule_rate = smoothing * self.rule_rate + (1 - smoothing) * target

    # ------------------------------------------------------------------ views
    def to_dict(self) -> dict:
        return {
            "rate": round(self.rate * 100, 2),  # per cent, for display
            "neutral": round(self.cfg.neutral_rate * 100, 2),
            "inflation": round(self.inflation * 100, 2),
            "target": round(self.cfg.inflation_target * 100, 2),
            "output_gap": round(self.output_gap, 2),
            "real_rate": round(self.real_rate * 100, 2),
            "stance": round(self.stance * 100, 2),
            "manual": bool(self.cfg.cb_manual),
            "active": bool(self.cfg.cb_active),
            "flow_multiplier": round(self.flow_multiplier(), 3),
            "history": self.history[-120:],
        }
