"""Market Ecology Simulator — agent-based model of an equity market."""

from .config import PARAM_SPEC, Config
from .simulation import Simulation

__all__ = ["Config", "PARAM_SPEC", "Simulation"]
__version__ = "0.1.0"
