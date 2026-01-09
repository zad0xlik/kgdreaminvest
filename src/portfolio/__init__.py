"""Portfolio module - Trading execution and position management with provider routing."""

from src.portfolio.trading import execute_trades, execute_paper_trades
from src.portfolio.yahoo_options_trading import (
    execute_option_buy,
    execute_option_sell,
    get_options_positions,
    update_options_positions_mtm,
    calculate_options_allocation
)
from src.portfolio.alpaca_options_trading import (
    execute_option_buy_alpaca,
    execute_option_sell_alpaca,
    sync_alpaca_options_account,
    sync_alpaca_options_positions,
    close_all_alpaca_options_positions,
    get_alpaca_options_trading_client
)

__all__ = [
    "execute_trades",
    "execute_paper_trades",  # Legacy alias
    "execute_option_buy",
    "execute_option_sell",
    "get_options_positions",
    "update_options_positions_mtm",
    "calculate_options_allocation",
]
