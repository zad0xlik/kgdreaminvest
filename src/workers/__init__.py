"""
Workers Module: Background processing threads for KGDreamInvest.

Provides three autonomous workers:
- MARKET: Fetches prices, computes indicators and signals
- DREAM: Maintains knowledge graph edges via correlation analysis
- THINK: Multi-agent committee for trading decisions

Each worker runs in its own thread and can be started/stopped independently.
"""

from src.workers.market_worker import MARKET, MarketWorker
from src.workers.dream_worker import DREAM, DreamWorker
from src.workers.think_worker import THINK, ThinkWorker

__all__ = [
    "MARKET",
    "MarketWorker",
    "DREAM",
    "DreamWorker",
    "THINK",
    "ThinkWorker",
]
