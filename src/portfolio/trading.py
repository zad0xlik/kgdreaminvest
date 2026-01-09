"""Trading execution with broker provider routing."""
import logging
import sqlite3
from typing import Dict, Any, List

from src.config import Config

logger = logging.getLogger("kginvest")


def execute_trades(
    conn: sqlite3.Connection,
    decisions: List[Dict[str, Any]],
    prices: Dict[str, Any],
    reason: str,
    insight_id: int
) -> Dict[str, Any]:
    """
    Universal trading interface - routes to correct broker provider.
    
    Routes to Yahoo paper trading or Alpaca based on Config.BROKER_PROVIDER.
    
    Args:
        conn: Database connection
        decisions: List of trade decisions with ticker, action, allocation_pct
        prices: Dict mapping ticker to price data with 'current' price
        reason: Reason string for trade log
        insight_id: Associated insight ID
        
    Returns:
        Dict with keys: executed (list of trades), skipped (list of reasons), cash (final balance)
        
    Example:
        >>> decisions = [
        ...     {"ticker": "AAPL", "action": "BUY", "allocation_pct": 5.0}
        ... ]
        >>> result = execute_trades(conn, decisions, prices, "test", 1)
        >>> print(f"Executed {len(result['executed'])} trades via {Config.BROKER_PROVIDER}")
    """
    if Config.BROKER_PROVIDER == "alpaca":
        from src.portfolio.alpaca_stocks_trading import execute_alpaca_trades
        logger.info("Routing stocks trades to Alpaca")
        return execute_alpaca_trades(conn, decisions, prices, reason, insight_id)
    else:
        from src.portfolio.yahoo_stocks_trading import execute_yahoo_stocks_trades
        logger.info("Routing stocks trades to Yahoo paper trading")
        return execute_yahoo_stocks_trades(conn, decisions, prices, reason, insight_id)


# Legacy alias for backward compatibility
def execute_paper_trades(
    conn: sqlite3.Connection,
    decisions: List[Dict[str, Any]],
    prices: Dict[str, Any],
    reason: str,
    insight_id: int
) -> Dict[str, Any]:
    """
    Legacy alias for execute_yahoo_stocks_trades.
    
    Maintained for backward compatibility with existing code.
    Use execute_trades() or execute_yahoo_stocks_trades() instead.
    """
    from src.portfolio.yahoo_stocks_trading import execute_yahoo_stocks_trades
    return execute_yahoo_stocks_trades(conn, decisions, prices, reason, insight_id)
