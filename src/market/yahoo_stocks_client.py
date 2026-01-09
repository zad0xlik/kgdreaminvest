"""Yahoo Finance API client (no yfinance dependency)."""
import random
import threading
import time
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import quote as urlquote

import requests

from src.config import Config

# User agents for request rotation
UA_LIST = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
]

# Price cache with timestamp
_PRICE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_PRICE_CACHE_LOCK = threading.Lock()


def _headers() -> Dict[str, str]:
    """Get random user agent headers for Yahoo requests."""
    return {
        "User-Agent": random.choice(UA_LIST),
        "Accept": "application/json",
        "Connection": "keep-alive"
    }


def fetch_yahoo_chart(symbol: str, range_days: int = 60) -> Dict[str, Any]:
    """
    Direct call to Yahoo's chart API.
    
    Args:
        symbol: Ticker symbol (e.g., "AAPL", "^VIX")
        range_days: Number of days of historical data
        
    Returns:
        Dict with keys: symbol, timestamps, closes, volumes
        Returns {} on failure
        
    Example:
        >>> data = fetch_yahoo_chart("AAPL", range_days=30)
        >>> if data:
        ...     print(f"Got {len(data['closes'])} prices")
    """
    sym = urlquote(symbol, safe="")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"interval": "1d", "range": f"{range_days}d"}
    
    try:
        resp = requests.get(
            url,
            params=params,
            headers=_headers(),
            timeout=Config.YAHOO_TIMEOUT
        )
        
        if resp.status_code != 200:
            return {}
        
        data = resp.json()
        result = (data.get("chart", {}).get("result") or [])
        if not result:
            return {}
        
        result = result[0]
        ts = result.get("timestamp", []) or []
        quotes = result.get("indicators", {}).get("quote", []) or []
        
        if not quotes:
            return {}
        
        q = quotes[0]
        closes = q.get("close", []) or []
        volumes = q.get("volume", []) or []
        
        # Filter out None values
        valid = [(t, c, v) for t, c, v in zip(ts, closes, volumes) if c is not None]
        if not valid:
            return {}
        
        ts, closes, volumes = zip(*valid)
        
        return {
            "symbol": symbol,
            "timestamps": list(ts),
            "closes": list(map(float, closes)),
            "volumes": list(volumes)
        }
        
    except Exception:
        return {}


def fetch_single_ticker(symbol: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Cached fetch of ticker with current and previous close.
    
    Uses global cache with configurable TTL to avoid hammering Yahoo API.
    
    Args:
        symbol: Ticker symbol
        
    Returns:
        Tuple of (symbol, data_dict or None)
        data_dict contains: current, previous, change_pct, history
        
    Example:
        >>> sym, data = fetch_single_ticker("AAPL")
        >>> if data:
        ...     print(f"{sym}: ${data['current']:.2f} ({data['change_pct']:+.2f}%)")
    """
    now = time.time()
    
    # Check cache
    with _PRICE_CACHE_LOCK:
        if symbol in _PRICE_CACHE:
            ts, payload = _PRICE_CACHE[symbol]
            if now - ts <= Config.YAHOO_CACHE_SECONDS:
                return symbol, payload

    # Fetch fresh data
    chart = fetch_yahoo_chart(symbol, range_days=Config.YAHOO_RANGE_DAYS)
    closes = chart.get("closes", [])
    volumes = chart.get("volumes", [])
    
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
        with _PRICE_CACHE_LOCK:
            _PRICE_CACHE[symbol] = (now, payload)
    
    return symbol, payload


def last_close_many(symbols: List[str], max_workers: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Thread pool fetch for multiple tickers.
    
    Keeps this implementation dependency-light (no heavy libraries).
    
    Args:
        symbols: List of ticker symbols
        max_workers: Maximum concurrent requests
        
    Returns:
        Dict mapping symbol to data dict
        
    Example:
        >>> prices = last_close_many(["AAPL", "MSFT", "GOOGL"])
        >>> for sym, data in prices.items():
        ...     print(f"{sym}: ${data['current']:.2f}")
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[str, Dict[str, Any]] = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_single_ticker, s): s for s in symbols}
        for fut in as_completed(futs):
            try:
                sym, data = fut.result()
                if data:
                    results[sym] = data
            except Exception:
                continue
    
    return results
