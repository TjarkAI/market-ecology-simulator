"""The world outside the order books: the news flow, the mood, and how fast
information is arriving.

Fair values themselves live with the instruments (`mes/instruments.py`), because
with several sectors there is no single fundamental value. This module owns what
is genuinely shared: one sentiment, one news feed, one information intensity.
Keeping a second copy of "the" fundamental value here was a real bug — a headline
moved one of them and not the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import Config

# Headlines are cosmetic — the number that matters is the shock magnitude.
# They exist so the news ticker in the UI reads like a market, not a log file.
GOOD_NEWS = [
    "Quarterly results beat expectations",
    "Major order from Asia reported",
    "Analysts raise price target",
    "New product beats forecasts",
    "Central Bank signals rate cut",
    "Takeover rumours in the market",
]
BAD_NEWS = [
    "Profit warning issued",
    "Supply chain disrupted",
    "Regulator opens proceedings",
    "Major investor pulls out",
    "Rate hike announced",
    "Geopolitical tensions escalate",
]


@dataclass
class NewsItem:
    ts: int
    headline: str
    magnitude: float  # log-shock applied to the fundamental value

    def to_dict(self) -> dict:
        return {"ts": self.ts, "headline": self.headline, "magnitude": round(self.magnitude, 4)}


@dataclass
class World:
    cfg: Config
    rng: np.random.Generator
    sentiment: float = 0.0  # mean-reverting mood, shared by all agents
    vol_state: float = 0.0  # log deviation of the current information intensity
    effective_vol: float = 0.0  # fundamental volatility actually in force
    news: list = field(default_factory=list)

    def __post_init__(self):
        self.effective_vol = self.cfg.fundamental_vol

    def step(self, t: int) -> None:
        cfg = self.cfg

        # Information does not arrive evenly. Quiet weeks are followed by quiet
        # weeks and busy ones by busy ones, so the volatility of the fundamental
        # value is itself persistent — an AR(1) in log variance.
        #
        # This is not decoration. Volatility clustering has to come from
        # somewhere, and if the only source is the population switching between
        # trend-following and value regimes, then clustering and mean reversion
        # are the same phenomenon: the price trends, then the value camp takes
        # over and pulls it back. Every attempt to reduce the resulting negative
        # return autocorrelation also destroyed the clustering, because they were
        # two views of one mechanism. Clustered *information* gives clustered
        # volatility in the permanent component, which needs no reversion at all.
        self.vol_state = (
            cfg.fundamental_vol_persistence * self.vol_state
            + cfg.fundamental_vol_of_vol * self.rng.standard_normal()
        )
        # The instruments draw their own shocks with this as the scale.
        self.effective_vol = cfg.fundamental_vol * float(np.exp(self.vol_state))

        # Sentiment: Ornstein-Uhlenbeck. Decays on its own, so a shock fades
        # unless the agents keep it alive through their own trading.
        self.sentiment = 0.97 * self.sentiment + 0.08 * cfg.news_intensity * self.rng.standard_normal()

        # Random headlines, rate scales with the news intensity slider.
        if cfg.news_intensity > 0 and self.rng.random() < 0.004 * cfg.news_intensity:
            good = self.rng.random() < 0.5
            magnitude = float(self.rng.normal(0.012, 0.008)) * (1 if good else -1)
            headline = self.rng.choice(GOOD_NEWS if good else BAD_NEWS)
            self.apply_news(t, str(headline), magnitude)

    def apply_news(self, t: int, headline: str, magnitude: float) -> NewsItem:
        """Record a headline and move the mood.

        The fair-value shock is applied by the caller, which knows which
        instruments a headline concerns. What this never does is touch a price:
        the price only moves if agents decide to act on the news, and they read it
        differently — that asymmetry is the point of the whole model.
        """
        self.sentiment += magnitude * 6.0
        item = NewsItem(ts=t, headline=headline, magnitude=magnitude)
        self.news.append(item)
        del self.news[:-40]
        return item
