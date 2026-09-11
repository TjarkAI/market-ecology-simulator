"""Simulation parameters.

`PARAM_SPEC` is the single source of truth: the backend validates against it
and the frontend builds its control panel from it, so a new knob only has to
be declared once.

`live=True` means the parameter can be changed while the simulation is
running. Everything else only takes effect on reset.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class Config:
    # --- world ---------------------------------------------------------
    seed: int = 42
    initial_price: float = 100.0
    # Which instruments trade. None means all five sectors; a single symbol gives
    # back the one-asset market the model was originally calibrated on.
    symbols: tuple | None = None
    sector_vol: float = 0.6  # sector shock size, relative to the market factor
    # 0 = the five sectors themselves trade, which is the calibrated default.
    # Above 0, each sector is represented by that many individual stocks and the
    # sector becomes a shared shock rather than an instrument. Costs roughly
    # proportionally in runtime, since the order flow is scaled per instrument.
    stocks_per_sector: int = 0
    stock_idio_multiple: float = 1.8  # a single name is noisier than its index
    # Per-step figures, derived from annual ones. One trading year is
    # 252 * steps_per_day steps, so a 7 % annual drift and 15 % annual volatility
    # come out as the numbers below. Setting these by hand without doing that
    # division was a real bug during calibration: the defaults implied 60 %
    # fundamental growth per year and the price never stopped rising.
    fundamental_drift: float = 0.07 / (252 * 240)  # 7 % per year
    fundamental_vol: float = 0.60 / (252 * 240) ** 0.5  # 60 % per year, average
    # Information arrives in bursts, so that volatility is itself persistent.
    # This is the model's source of volatility clustering in the *permanent*
    # component — see the note in World.step.
    fundamental_vol_persistence: float = 0.999
    fundamental_vol_of_vol: float = 0.025

    # --- central bank ---------------------------------------------------
    # Rates are annualised; the bank converts them per step where they are used.
    cb_active: int = 1
    cb_manual: int = 0  # 1 = the rate is set by hand instead of by the rule
    cb_manual_rate: float = 0.02
    neutral_rate: float = 0.02
    inflation_target: float = 0.02
    max_rate: float = 0.15
    taylor_inflation: float = 1.5  # weight on the inflation gap
    taylor_output: float = 0.5  # weight on the output gap
    rate_adjust_days: float = 25.0  # half-life of the move towards the rule's target
    policy_lag_days: float = 90.0  # half-life of transmission into the economy
    macro_half_life_days: float = 120.0  # persistence of the output gap and inflation
    # Calm by default. Real policy rates move over a cycle, not constantly, and
    # this number turned out to matter far more than it looks: at 0.02 the rate
    # wandered enough that repricing fair values by their duration on every move
    # dominated everything else in the model, and the validation fell from five
    # criteria to three. Scenarios turn it up when the point is the rate.
    macro_shock: float = 0.006  # annualised size of macro surprises
    output_rate_response: float = 1.2  # how much a restrictive stance cools output
    phillips_slope: float = 0.35  # how much a hot economy lifts inflation
    rate_report_days: int = 5  # how often a point is kept for the chart
    # The three channels through which the rate reaches the market.
    # Duration in years for a sector with sensitivity 1, so technology sits at
    # 7 and energy at 1.6. Equities really are long-duration, but the product of
    # duration and rate volatility is what reaches the market, and at 8 with a
    # lively macro block that product swamped the fundamentals themselves.
    rate_valuation_channel: float = 4.0
    borrow_spread: float = 0.01  # what leveraged funds pay above the policy rate
    inflow_rate_sensitivity: float = 6.0  # how much high rates dry up savings plans

    # --- population ----------------------------------------------------
    n_adaptive: int = 300  # switch between fundamental and chartist
    n_noise: int = 200
    n_passive: int = 30  # ETF / savings plans
    n_leveraged: int = 20  # margin users, source of cascades
    n_makers: int = 12  # market makers, the only source of standing depth
    initial_chartist_share: float = 0.4

    # --- market making -------------------------------------------------
    mm_spread: float = 0.0006  # base half-spread as a share of price
    mm_quote_size: int = 200  # shares quoted per side per maker
    mm_inventory_limit: int = 6000  # position at which quotes are fully skewed
    mm_skew: float = 0.9  # how hard inventory leans the quoted sizes (0..1)
    mm_vol_sensitivity: float = 0.15  # how much the spread widens with volatility

    # --- share supply --------------------------------------------------
    n_companies: int = 1  # the issuer; the only source of new share supply
    issue_interval: int = 20  # steps between issuance decisions
    issue_threshold: float = 0.12  # premium over fair value that triggers issuance
    issue_rate: float = 0.20  # issue size as a share of resting depth
    buyback_share: float = 0.05  # cash spent per buyback decision
    max_issuance: int = 400_000  # hard cap on shares ever issued

    # --- behaviour -----------------------------------------------------
    # One step is roughly a minute of trading, one day a full session. The day
    # has to be long enough to contain a complete price-adjustment cycle,
    # otherwise a single move is smeared across several bars and the daily
    # returns are autocorrelated by construction rather than by behaviour.
    steps_per_day: int = 240
    activation_rate: float = 0.12  # share of agents acting per step, on average
    # How strongly activity follows the information intensity. Zero means a
    # constant number of agents act each step, which breaks the volume/volatility
    # relationship — see the note in Simulation.step.
    activity_elasticity: float = 0.5
    perception_noise: float = 0.02  # how wrong fundamentalists are
    # How slowly a valuation-driven agent's estimate of fair value follows the real
    # thing, as a half-life in trading days. Zero means no lag, and zero is the
    # default because the lag turned out to make the model worse — see the note in
    # Market.update_perception.
    perception_lag_days: float = 0.0
    mm_size_elasticity: float = 0.6  # how much maker size grows with information flow
    fundamental_aggression: float = 0.15  # position sizing vs. mispricing
    value_price_pull: float = 0.02  # share of the valuation gap conceded per order
    chartist_window: int = 30  # EMA horizon in steps
    chartist_aggression: float = 55.0  # trend extrapolation strength
    noise_spread: float = 0.006  # limit price scatter of noise traders
    order_lifetime: int = 25  # steps before a resting order expires
    max_participation: float = 0.25  # order size cap as a share of resting depth
    # No-trade band: how far a position may drift from its target before the
    # agent acts, as a share of the target. Zero means continuous rebalancing.
    rebalance_band: float = 0.0

    # --- adaptation (the "learning system") ----------------------------
    switch_interval: int = 20  # steps between strategy reviews
    switch_intensity: float = 1.5  # logistic sensitivity to the performance gap
    herd_strength: float = 2.5  # pull towards whatever the majority is doing
    switch_rate: float = 0.2  # max share of agents that can flip per review
    memory: float = 0.96  # EMA decay of an agent's performance record

    # --- leverage ------------------------------------------------------
    max_leverage: float = 3.0
    # Set against the leverage the funds actually reach, not against the leverage
    # they are allowed. They settle near 1.6x because their appetite falls as prices
    # rise above fair value, so equity/exposure sits around 0.62 — and a floor of
    # 0.25 is never touched. The whole cascade mechanism was dead code at the
    # default: it only ran in scenarios that raised this by hand. At 0.38 calls are
    # occasional, at 0.44 they fire every other step.
    maintenance_margin: float = 0.38  # equity/exposure floor before a call

    # --- flows and shocks ----------------------------------------------
    # About 5 % of market capitalisation per year. Set far too high, the savings
    # plans alone buy many times the entire float and the price rises without
    # limit — which is worth knowing, but it is not a starting point.
    passive_inflow: float = 30.0  # cash per passive agent per interval
    passive_interval: int = 40
    news_intensity: float = 0.0  # extra sentiment volatility (0 = off)

    # --- bookkeeping ---------------------------------------------------
    initial_cash: float = 20_000.0
    initial_shares: int = 100

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Build a config from a dictionary, coercing each value to its own type.

        The coercion is not cosmetic. A JSON body sends every number as a float, and
        `n_noise=200.0` reaches `_spawn_agents` as a float, where `range(count)`
        raises `TypeError: 'float' object cannot be interpreted as an integer` — in
        the middle of building the population, leaving the live simulation half
        constructed and every later step raising `KeyError: 'base'`. One frontend
        slider was enough to freeze the market for good.

        `update_live` had this cast all along, via `PARAM_SPEC["kind"]`; this path
        did not, which is exactly why only the parameters that need a restart
        broke.
        """
        known = {f.name: f for f in fields(cls)}
        out: dict = {}
        for name, value in data.items():
            field = known.get(name)
            if field is None:
                continue
            out[name] = _coerce(name, value, field.default)
        return cls(**out)

    def update_live(self, data: dict) -> list[str]:
        """Apply only the parameters marked as live-tunable. Returns names applied.

        Cast first, assign second, so the patch is all or nothing. Casting inside
        the assignment loop meant a body of three parameters whose second value was
        unparseable set the first, raised on the second and never reached the third
        — a configuration nobody asked for, behind an error that named none of it.
        """
        casted: list[tuple[str, object]] = []
        for name, value in data.items():
            spec = PARAM_SPEC.get(name)
            if spec is None or not spec.get("live"):
                continue
            caster = int if spec["kind"] == "int" else float
            casted.append((name, caster(value)))

        for name, value in casted:
            setattr(self, name, value)
        return [name for name, _ in casted]


def _coerce(name: str, value, default):
    """One parameter, cast to the type it is declared with.

    `PARAM_SPEC` is the authority where it says something; otherwise the default's
    own type decides. `symbols` is a tuple or None and is passed through — there is
    nothing to cast and guessing would be worse than leaving it alone.
    """
    if value is None or isinstance(value, (tuple, list, str)):
        return value
    spec = PARAM_SPEC.get(name)
    if spec is not None:
        return int(value) if spec["kind"] == "int" else float(value)
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


# label / group / min / max / step / kind / live
PARAM_SPEC: dict[str, dict] = {
    # Population
    "n_adaptive":            {"label": "Adaptive Trader",     "group": "Population", "min": 0,    "max": 1000, "step": 10,     "kind": "int",   "live": False},
    "n_noise":               {"label": "Noise Trader",        "group": "Population", "min": 0,    "max": 1000, "step": 10,     "kind": "int",   "live": False},
    "n_passive":             {"label": "ETF / Sparplan",      "group": "Population", "min": 0,    "max": 300,  "step": 5,      "kind": "int",   "live": False},
    "n_leveraged":           {"label": "Hebel-Fonds",         "group": "Population", "min": 0,    "max": 200,  "step": 5,      "kind": "int",   "live": False},
    "n_makers":              {"label": "Market Maker",        "group": "Population", "min": 0,    "max": 60,   "step": 1,      "kind": "int",   "live": False},
    "mm_spread":             {"label": "MM-Spanne",           "group": "Liquidität", "min": 0.0001,"max": 0.01,"step": 0.0001, "kind": "float", "live": True},
    "mm_quote_size":         {"label": "MM-Quotengröße",      "group": "Liquidität", "min": 10,   "max": 1000, "step": 10,     "kind": "int",   "live": True},
    "mm_inventory_limit":    {"label": "MM-Bestandsgrenze",   "group": "Liquidität", "min": 500,  "max": 30000,"step": 500,    "kind": "int",   "live": True},
    "max_participation":     {"label": "Beteiligungsgrenze",  "group": "Liquidität", "min": 0.02, "max": 1.0,  "step": 0.02,   "kind": "float", "live": True},
    "issue_threshold":       {"label": "Emissions-Schwelle",  "group": "Aktienangebot","min": 0.02,"max": 1.0, "step": 0.02,   "kind": "float", "live": True},
    "issue_rate":            {"label": "Emissions-Tempo",     "group": "Aktienangebot","min": 0.0, "max": 1.0, "step": 0.02,   "kind": "float", "live": True},
    "issue_interval":        {"label": "Emissions-Takt",      "group": "Aktienangebot","min": 5,   "max": 200, "step": 5,      "kind": "int",   "live": True},
    "initial_chartist_share":{"label": "Startanteil Chartisten","group": "Population","min": 0.0, "max": 1.0,  "step": 0.05,   "kind": "float", "live": False},
    # Behaviour
    "activation_rate":       {"label": "Handelsaktivität",    "group": "Verhalten",  "min": 0.01, "max": 0.5,  "step": 0.01,   "kind": "float", "live": True},
    "activity_elasticity":   {"label": "Aktivität folgt News", "group": "Verhalten",  "min": 0.0,  "max": 3.0,  "step": 0.1,    "kind": "float", "live": True},
    "chartist_aggression":   {"label": "Trendfolge-Stärke",   "group": "Verhalten",  "min": 0.0,  "max": 150.0,"step": 1.0,    "kind": "float", "live": True},
    "fundamental_aggression":{"label": "Value-Stärke",        "group": "Verhalten",  "min": 0.0,  "max": 2.0,  "step": 0.05,   "kind": "float", "live": True},
    "value_price_pull":      {"label": "Rückholkraft",        "group": "Verhalten",  "min": 0.0,  "max": 0.5,  "step": 0.01,   "kind": "float", "live": True},
    "chartist_window":       {"label": "Trend-Fenster",       "group": "Verhalten",  "min": 5,    "max": 200,  "step": 5,      "kind": "int",   "live": True},
    "perception_noise":      {"label": "Bewertungs-Unsicherheit","group":"Verhalten","min": 0.0,  "max": 0.15, "step": 0.005,  "kind": "float", "live": True},
    "perception_lag_days":   {"label": "Bewertungs-Verzögerung","group": "Verhalten", "min": 0.0,  "max": 120.0,"step": 0.5,    "kind": "float", "live": True},
    "mm_size_elasticity":    {"label": "MM-Größe folgt News",  "group": "Liquidität", "min": 0.0,  "max": 2.0,  "step": 0.1,    "kind": "float", "live": True},
    "noise_spread":          {"label": "Rausch-Streuung",     "group": "Verhalten",  "min": 0.001,"max": 0.05, "step": 0.001,  "kind": "float", "live": True},
    # Adaptation
    "switch_intensity":      {"label": "Erfolgs-Orientierung","group": "Lernen",     "min": 0.0,  "max": 10.0, "step": 0.1,    "kind": "float", "live": True},
    "herd_strength":         {"label": "Herdentrieb",         "group": "Lernen",     "min": 0.0,  "max": 8.0,  "step": 0.1,    "kind": "float", "live": True},
    "switch_rate":           {"label": "Wechselgeschwindigkeit","group": "Lernen",   "min": 0.0,  "max": 1.0,  "step": 0.05,   "kind": "float", "live": True},
    "switch_interval":       {"label": "Review-Intervall",    "group": "Lernen",     "min": 5,    "max": 200,  "step": 5,      "kind": "int",   "live": True},
    "memory":                {"label": "Gedächtnis",          "group": "Lernen",     "min": 0.5,  "max": 0.999,"step": 0.005,  "kind": "float", "live": True},
    # Leverage
    "max_leverage":          {"label": "Max. Hebel",          "group": "Hebel",      "min": 1.0,  "max": 10.0, "step": 0.5,    "kind": "float", "live": True},
    "maintenance_margin":    {"label": "Margin-Schwelle",     "group": "Hebel",      "min": 0.05, "max": 0.6,  "step": 0.01,   "kind": "float", "live": True},
    # Flows
    "passive_inflow":        {"label": "ETF-Zufluss",         "group": "Kapitalflüsse","min": 0.0,"max": 600.0,"step": 5.0,   "kind": "float", "live": True},
    "passive_interval":      {"label": "Zufluss-Takt",        "group": "Kapitalflüsse","min": 5,  "max": 250,  "step": 5,      "kind": "int",   "live": True},
    # World
    "fundamental_vol":       {"label": "Fundamental-Vola",    "group": "Welt",       "min": 0.0,  "max": 0.004,"step": 0.00005,"kind": "float", "live": True},
    "fundamental_vol_of_vol":{"label": "Nachrichten-Schübe",  "group": "Welt",       "min": 0.0,  "max": 0.10, "step": 0.002,  "kind": "float", "live": True},
    "sector_vol":            {"label": "Sektor-Eigenleben",   "group": "Welt",       "min": 0.0,  "max": 2.0,  "step": 0.05,   "kind": "float", "live": True},
    "stocks_per_sector":     {"label": "Aktien je Sektor",    "group": "Welt",       "min": 0,    "max": 4,    "step": 1,      "kind": "int",   "live": False},
    # Central bank
    "cb_active":             {"label": "Zentralbank aktiv",   "group": "Zentralbank","min": 0,    "max": 1,    "step": 1,      "kind": "int",   "live": True},
    "cb_manual":             {"label": "Zins von Hand",       "group": "Zentralbank","min": 0,    "max": 1,    "step": 1,      "kind": "int",   "live": True},
    "cb_manual_rate":        {"label": "Zins (manuell)",      "group": "Zentralbank","min": 0.0,  "max": 0.15, "step": 0.0025, "kind": "float", "live": True},
    "neutral_rate":          {"label": "Neutraler Zins",      "group": "Zentralbank","min": 0.0,  "max": 0.08, "step": 0.0025, "kind": "float", "live": True},
    "inflation_target":      {"label": "Inflationsziel",      "group": "Zentralbank","min": 0.0,  "max": 0.06, "step": 0.0025, "kind": "float", "live": True},
    "taylor_inflation":      {"label": "Taylor: Inflation",   "group": "Zentralbank","min": 0.0,  "max": 4.0,  "step": 0.1,    "kind": "float", "live": True},
    "taylor_output":         {"label": "Taylor: Konjunktur",  "group": "Zentralbank","min": 0.0,  "max": 2.0,  "step": 0.05,   "kind": "float", "live": True},
    "rate_adjust_days":      {"label": "Zinsschritt-Tempo",   "group": "Zentralbank","min": 2.0,  "max": 200.0,"step": 1.0,    "kind": "float", "live": True},
    "policy_lag_days":       {"label": "Wirkungsverzögerung", "group": "Zentralbank","min": 5.0,  "max": 400.0,"step": 5.0,    "kind": "float", "live": True},
    "macro_shock":           {"label": "Konjunktur-Schocks",  "group": "Zentralbank","min": 0.0,  "max": 0.10, "step": 0.002,  "kind": "float", "live": True},
    "rate_valuation_channel":{"label": "Kanal: Bewertung",    "group": "Zentralbank","min": 0.0,  "max": 30.0, "step": 0.5,    "kind": "float", "live": True},
    "borrow_spread":         {"label": "Kanal: Hebelkosten",  "group": "Zentralbank","min": 0.0,  "max": 0.10, "step": 0.0025, "kind": "float", "live": True},
    "inflow_rate_sensitivity":{"label": "Kanal: Zuflüsse",    "group": "Zentralbank","min": 0.0,  "max": 30.0, "step": 0.5,    "kind": "float", "live": True},
    "fundamental_vol_persistence": {"label": "Schub-Dauer",   "group": "Welt",       "min": 0.9,  "max": 0.9999,"step": 0.0005,"kind": "float", "live": True},
    "fundamental_drift":     {"label": "Fundamental-Drift",   "group": "Welt",       "min": -0.00001,"max": 0.00001,"step":0.0000005,"kind":"float","live": True},
    "mm_skew":               {"label": "MM-Bestandsscheu",    "group": "Liquidität", "min": 0.0,  "max": 1.0,  "step": 0.05,   "kind": "float", "live": True},
    "mm_vol_sensitivity":    {"label": "MM-Vola-Scheu",       "group": "Liquidität", "min": 0.0,  "max": 3.0,  "step": 0.05,   "kind": "float", "live": True},
    "news_intensity":        {"label": "Nachrichten-Rauschen","group": "Welt",       "min": 0.0,  "max": 1.0,  "step": 0.05,   "kind": "float", "live": True},
    "seed":                  {"label": "Zufalls-Seed",        "group": "Welt",       "min": 0,    "max": 9999, "step": 1,      "kind": "int",   "live": False},
}
