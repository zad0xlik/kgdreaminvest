"""Portfolio module - Trading execution and position management."""

from src.portfolio.trading import execute_paper_trades
from src.portfolio.options_trading import (
    execute_option_buy,
    execute_option_sell,
    get_options_positions,
    update_options_positions_mtm,
    calculate_options_allocation
)

__all__ = [
    "execute_paper_trades",
    "execute_option_buy",
    "execute_option_sell",
    "get_options_positions",
    "update_options_positions_mtm",
    "calculate_options_allocation",
]
