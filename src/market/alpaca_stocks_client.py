"""Alpaca market data client using alpaca-py."""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

from src.config import Config

logger = logging.getLogger("kginvest")

# Price cache with timestamp (same pattern as Yahoo client)
_ALPACA_PRICE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_ALPACA_CACHE_LOCK = threading.Lock()


def get_alpaca_client():
    """
    Create and return Alpaca historical data client.
    
    Returns:
        StockHistoricalDataClient instance
        
    Raises:
        ImportError: If alpaca-py not installed
        ValueError: If API keys not configured
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        raise ImportError(
            "alpaca-py not installed. Run: pip install alpaca-py"
        )
    
    if not Config.ALPACA_API_KEY or not Config.ALPACA_SECRET_KEY:
        raise ValueError(
            "Alpaca API keys not configured. Set ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY in .env file"
        )
    
    return StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )


def fetch_alpaca_bars(symbol: str, days: int = 60) -> Dict[str, Any]:
    """
    Fetch historical bar data from Alpaca.
    
    Args:
        symbol: Ticker symbol (e.g., "AAPL", "SPY")
        days: Number of days of historical data
        
    Returns:
        Dict with keys: symbol, timestamps, closes, volumes
        Returns {} on failure
        
    Example:
        >>> data = fetch_alpaca_bars("AAPL", days=30)
        >>> if data:
        ...     print(f"Got {len(data['closes'])} prices")
    """
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        
        client = get_alpaca_client()
        
        # Calculate date range
        end = datetime.now()
        start = end - timedelta(days=days)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )
        
        bars = client.get_stock_bars(request)
        
        # Extract data for this symbol (BarSet has .data attribute)
        if not bars.data or symbol not in bars.data:
            return {}
        
        symbol_bars = bars.data[symbol]
        
        if not symbol_bars:
            return {}
        
        # Convert to lists
        timestamps = [int(bar.timestamp.timestamp()) for bar in symbol_bars]
        closes = [float(bar.close) for bar in symbol_bars]
        volumes = [int(bar.volume) for bar in symbol_bars]
        
        return {
            "symbol": symbol,
            "timestamps": timestamps,
            "closes": closes,
            "volumes": volumes
        }
        
    except Exception as e:
        logger.warning(f"Alpaca bars fetch failed for {symbol}: {e}")
        return {}


def fetch_single_ticker_alpaca(symbol: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Cached fetch of ticker with current and previous close from Alpaca.
    
    Uses global cache with configurable TTL to avoid excessive API calls.
    
    Args:
        symbol: Ticker symbol
        
    Returns:
        Tuple of (symbol, data_dict or None)
        data_dict contains: current, previous, change_pct, history
        
    Example:
        >>> sym, data = fetch_single_ticker_alpaca("AAPL")
        >>> if data:
        ...     print(f"{sym}: ${data['current']:.2f} ({data['change_pct']:+.2f}%)")
    """
    now = time.time()
    
    # Check cache
    with _ALPACA_CACHE_LOCK:
        if symbol in _ALPACA_PRICE_CACHE:
            ts, payload = _ALPACA_PRICE_CACHE[symbol]
            if now - ts <= Config.YAHOO_CACHE_SECONDS:  # Reuse same cache TTL
                return symbol, payload
    
    # Fetch fresh data
    bars_data = fetch_alpaca_bars(symbol, days=Config.YAHOO_RANGE_DAYS)
    closes = bars_data.get("closes", [])
    volumes = bars_data.get("volumes", [])
    
    success = len(closes) >= 2
    payload = None
    
    if success:
        current = float(closes[-1])
        previous = float(closes[-2])
        change_pct = ((current - previous) / max(previous, 1e-9)) * 100.0
        volume = int(volumes[-1]) if volumes and len(volumes) >= 1 else 0
        
        payload = {
            "current": current,
            "previous": previous,
            "change_pct": float(change_pct),
            "history": closes,
            "volume": volume
        }
        
        # Update cache
        with _ALPACA_CACHE_LOCK:
            _ALPACA_PRICE_CACHE[symbol] = (now, payload)
    
    return symbol, payload


def last_close_many_alpaca(symbols: List[str], max_workers: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Thread pool fetch for multiple tickers from Alpaca.
    
    Args:
        symbols: List of ticker symbols
        max_workers: Maximum concurrent requests
        
    Returns:
        Dict mapping symbol to data dict
        
    Example:
        >>> prices = last_close_many_alpaca(["AAPL", "MSFT", "GOOGL"])
        >>> for sym, data in prices.items():
        ...     print(f"{sym}: ${data['current']:.2f}")
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results: Dict[str, Dict[str, Any]] = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_single_ticker_alpaca, s): s for s in symbols}
        for fut in as_completed(futs):
            try:
                sym, data = fut.result()
                if data:
                    results[sym] = data
            except Exception as e:
                logger.warning(f"Alpaca fetch error: {e}")
                continue
    
    return results


def get_latest_quote_alpaca(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get latest quote data for a symbol from Alpaca.
    
    Useful for more recent prices than daily bars provide.
    
    Args:
        symbol: Ticker symbol
        
    Returns:
        Dict with bid, ask, bid_size, ask_size or None on failure
        
    Example:
        >>> quote = get_latest_quote_alpaca("AAPL")
        >>> if quote:
        ...     print(f"Bid: ${quote['bid']:.2f}, Ask: ${quote['ask']:.2f}")
    """
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        
        client = get_alpaca_client()
        
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = client.get_stock_latest_quote(request)
        
        if symbol not in quotes:
            return None
        
        quote = quotes[symbol]
        
        return {
            "bid": float(quote.bid_price),
            "ask": float(quote.ask_price),
            "bid_size": int(quote.bid_size),
            "ask_size": int(quote.ask_size),
            "timestamp": quote.timestamp.isoformat() if quote.timestamp else None
        }
        
    except Exception as e:
        logger.warning(f"Alpaca quote fetch failed for {symbol}: {e}")
        return None


def search_symbols_alpaca(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search for tradeable symbols using Alpaca Trading API.
    
    Uses the /v2/assets endpoint to search by symbol or company name.
    Only returns active, tradeable US equities.
    
    Args:
        query: Search query (symbol or company name)
        limit: Maximum number of results to return
        
    Returns:
        List of dicts with keys: symbol, name, exchange, tradable, status
        Returns [] on failure or no results
        
    Example:
        >>> results = search_symbols_alpaca("AAPL")
        >>> for asset in results:
        ...     print(f"{asset['symbol']}: {asset['name']}")
        AAPL: Apple Inc.
        
        >>> results = search_symbols_alpaca("Apple")
        >>> # Returns multiple Apple-related stocks
    """
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass, AssetStatus
        
        if not Config.ALPACA_API_KEY or not Config.ALPACA_SECRET_KEY:
            logger.warning("Alpaca API keys not configured for symbol search")
            return []
        
        # Create trading client
        client = TradingClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY,
            paper=Config.ALPACA_PAPER_MODE
        )
        
        # Search for assets
        search_params = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY
        )
        
        assets = client.get_all_assets(search_params)
        
        # Filter by query (case-insensitive search in symbol or name)
        query_lower = query.lower().strip()
        matching_assets = []
        
        for asset in assets:
            symbol_match = query_lower in asset.symbol.lower()
            name_match = query_lower in (asset.name or "").lower()
            
            if symbol_match or name_match:
                matching_assets.append({
                    "symbol": asset.symbol,
                    "name": asset.name or asset.symbol,
                    "exchange": asset.exchange.value if asset.exchange else "Unknown",
                    "tradable": asset.tradable,
                    "status": asset.status.value if asset.status else "unknown",
                    "asset_class": asset.asset_class.value if asset.asset_class else "unknown"
                })
                
                if len(matching_assets) >= limit:
                    break
        
        # Sort by symbol length (exact/shorter matches first)
        matching_assets.sort(key=lambda x: (len(x["symbol"]), x["symbol"]))
        
        return matching_assets[:limit]
        
    except Exception as e:
        logger.warning(f"Alpaca symbol search failed for '{query}': {e}")
        return []
