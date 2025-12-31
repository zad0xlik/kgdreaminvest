"""Knowledge graph correlation analysis."""
import math
from typing import List

import numpy as np


def corr(a: List[float], b: List[float]) -> float:
    """
    Compute correlation between two price series.
    
    Uses percentage returns over the last 60 periods.
    Returns 0.0 if insufficient data or invalid calculation.
    
    Args:
        a: First price series  
        b: Second price series
        
    Returns:
        Correlation coefficient between -1.0 and 1.0
        Returns 0.0 if insufficient data or calculation fails
        
    Example:
        >>> prices_a = [100, 102, 101, 103, ...]  # 60+ prices
        >>> prices_b = [50, 51, 50.5, 51.5, ...]
        >>> correlation = corr(prices_a, prices_b)
        >>> print(f"Correlation: {correlation:+.2f}")
    """
    if len(a) < 20 or len(b) < 20:
        return 0.0
    
    # Use last 60 periods
    x = np.array(a[-60:], dtype=float)
    y = np.array(b[-60:], dtype=float)
    
    # Compute percentage returns
    rx = np.diff(x) / np.maximum(x[:-1], 1e-9)
    ry = np.diff(y) / np.maximum(y[:-1], 1e-9)
    
    if len(rx) < 10 or len(ry) < 10:
        return 0.0
    
    # Pearson correlation
    c = float(np.corrcoef(rx, ry)[0, 1])
    
    # Handle NaN/Inf
    if math.isnan(c) or math.isinf(c):
        return 0.0
    
    # Clamp to valid range
    return max(-1.0, min(1.0, c))
