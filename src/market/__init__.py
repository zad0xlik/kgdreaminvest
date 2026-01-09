"""Market module - Data provider routing with Yahoo Finance and Alpaca clients."""

from src.config import Config
from src.market.indicators import compute_indicators
from src.market.signals import compute_signals_from_bells

# Import Yahoo Finance functions (always available as fallback)
from src.market.yahoo_stocks_client import (
    fetch_yahoo_chart,
    fetch_single_ticker as fetch_single_ticker_yahoo,
    last_close_many as last_close_many_yahoo,
)


def last_close_many(symbols, max_workers=10):
    """
    Fetch latest close prices for multiple symbols.
    
    Routes to appropriate data provider based on Config.DATA_PROVIDER.
    
    Args:
        symbols: List of ticker symbols
        max_workers: Maximum concurrent workers for fetching
        
    Returns:
        Dict mapping symbol to price data dict
        
    Example:
        >>> prices = last_close_many(["AAPL", "MSFT", "GOOGL"])
        >>> print(prices["AAPL"]["current"])
    """
    if Config.DATA_PROVIDER == "alpaca":
        try:
            from src.market.alpaca_stocks_client import last_close_many_alpaca
            return last_close_many_alpaca(symbols, max_workers)
        except ImportError as e:
            import logging
            logger = logging.getLogger("kginvest")
            logger.warning(f"Alpaca client not available, falling back to Yahoo: {e}")
            return last_close_many_yahoo(symbols, max_workers)
        except Exception as e:
            import logging
            logger = logging.getLogger("kginvest")
            logger.error(f"Alpaca data fetch failed, falling back to Yahoo: {e}")
            return last_close_many_yahoo(symbols, max_workers)
    else:
        return last_close_many_yahoo(symbols, max_workers)


def fetch_single_ticker(symbol):
    """
    Fetch single ticker data.
    
    Routes to appropriate data provider based on Config.DATA_PROVIDER.
    
    Args:
        symbol: Ticker symbol
        
    Returns:
        Tuple of (symbol, data_dict or None)
    """
    if Config.DATA_PROVIDER == "alpaca":
        try:
            from src.market.alpaca_stocks_client import fetch_single_ticker_alpaca
            return fetch_single_ticker_alpaca(symbol)
        except ImportError as e:
            import logging
            logger = logging.getLogger("kginvest")
            logger.warning(f"Alpaca client not available, falling back to Yahoo: {e}")
            return fetch_single_ticker_yahoo(symbol)
        except Exception as e:
            import logging
            logger = logging.getLogger("kginvest")
            logger.error(f"Alpaca data fetch failed, falling back to Yahoo: {e}")
            return fetch_single_ticker_yahoo(symbol)
    else:
        return fetch_single_ticker_yahoo(symbol)


__all__ = [
    "fetch_yahoo_chart",
    "fetch_single_ticker",
    "last_close_many",
    "compute_indicators",
    "compute_signals_from_bells",
]
