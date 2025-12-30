"""Technical indicators calculation."""
from typing import Dict, List

import numpy as np


def compute_indicators(closes: List[float]) -> Dict[str, float]:
    """
    Compute technical indicators from price history.
    
    Calculates momentum, volatility, z-score, and RSI from close prices.
    
    Args:
        closes: List of closing prices (most recent last)
        
    Returns:
        Dict with indicators: mom5, mom20, volatility, zscore, rsi
        Returns default values if insufficient data
        
    Example:
        >>> closes = [100, 102, 101, 103, 105, 104, 106, ...]  # 21+ prices
        >>> indicators = compute_indicators(closes)
        >>> print(f"RSI: {indicators['rsi']:.1f}")
    """
    if len(closes) < 21:
        return {
            "mom5": 0.0,
            "mom20": 0.0,
            "volatility": 0.0,
            "zscore": 0.0,
            "rsi": 50.0
        }
    
    arr = np.array(closes, dtype=float)
    
    # Momentum: 5-day and 20-day returns
    mom5 = (arr[-1] / arr[-6] - 1.0) if len(arr) >= 6 else 0.0
    mom20 = (arr[-1] / arr[-21] - 1.0) if len(arr) >= 21 else 0.0

    # Volatility: std dev of recent returns
    returns = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
    volatility = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.0

    # Z-score: how many std devs from 20-day mean
    ma20 = float(np.mean(arr[-20:]))
    sd20 = float(np.std(arr[-20:]))
    zscore = (arr[-1] - ma20) / (sd20 + 1e-9) if sd20 > 0 else 0.0

    # RSI: Relative Strength Index (14-period)
    gains = np.maximum(returns[-14:], 0)
    losses = np.abs(np.minimum(returns[-14:], 0))
    avg_gain = float(np.mean(gains)) if len(gains) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    return {
        "mom5": round(float(mom5), 4),
        "mom20": round(float(mom20), 4),
        "volatility": round(float(volatility), 4),
        "zscore": round(float(zscore), 2),
        "rsi": round(float(rsi), 1),
    }
