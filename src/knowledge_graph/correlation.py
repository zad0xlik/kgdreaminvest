"""Knowledge graph correlation analysis."""
import math
from typing import List, Tuple

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


def iv_corr(iv_a: List[float], iv_b: List[float]) -> float:
    """
    Compute correlation between two implied volatility series.
    
    Uses raw IV values (not returns) over last 30 periods to capture
    volatility regime clustering.
    
    Args:
        iv_a: First IV series (e.g., [0.25, 0.26, 0.28, ...])
        iv_b: Second IV series
        
    Returns:
        Correlation coefficient between -1.0 and 1.0
        Returns 0.0 if insufficient data or calculation fails
    """
    if len(iv_a) < 10 or len(iv_b) < 10:
        return 0.0
    
    # Use last 30 periods for IV correlation
    x = np.array(iv_a[-30:], dtype=float)
    y = np.array(iv_b[-30:], dtype=float)
    
    # Remove any zero/invalid IVs
    valid = (x > 0) & (y > 0) & ~np.isnan(x) & ~np.isnan(y)
    x = x[valid]
    y = y[valid]
    
    if len(x) < 5:
        return 0.0
    
    # Pearson correlation on raw IV values
    c = float(np.corrcoef(x, y)[0, 1])
    
    # Handle NaN/Inf
    if math.isnan(c) or math.isinf(c):
        return 0.0
    
    return max(-1.0, min(1.0, c))


def delta_alignment(delta_a: float, delta_b: float) -> float:
    """
    Compute directional alignment between two options based on delta.
    
    Returns high value (0.7-1.0) when deltas point same direction,
    low value (0.0-0.3) when opposite directions.
    
    Args:
        delta_a: Delta of first option (-1.0 to 1.0)
        delta_b: Delta of second option (-1.0 to 1.0)
        
    Returns:
        Alignment score between 0.0 and 1.0
        
    Examples:
        >>> delta_alignment(0.55, 0.60)  # Both bullish calls
        0.95
        >>> delta_alignment(-0.45, -0.50)  # Both bearish puts
        0.95
        >>> delta_alignment(0.55, -0.50)  # Opposite directions
        0.05
    """
    # Normalize deltas to [-1, 1]
    d_a = max(-1.0, min(1.0, delta_a))
    d_b = max(-1.0, min(1.0, delta_b))
    
    # Dot product normalized to [0, 1]
    # Same direction (both positive or both negative) -> high
    # Opposite direction -> low
    alignment = (d_a * d_b + 1.0) / 2.0
    
    return float(alignment)


def vega_similarity(vega_a: float, vega_b: float) -> float:
    """
    Compute similarity in volatility sensitivity between two options.
    
    Returns high value when both have similar vega exposure.
    
    Args:
        vega_a: Vega of first option (absolute value)
        vega_b: Vega of second option (absolute value)
        
    Returns:
        Similarity score between 0.0 and 1.0
    """
    v_a = abs(vega_a)
    v_b = abs(vega_b)
    
    if v_a < 0.01 and v_b < 0.01:
        return 0.5  # Both have negligible vega
    
    # Ratio-based similarity (closer to 1.0 = more similar)
    ratio = min(v_a, v_b) / max(v_a, v_b, 0.01)
    
    return float(ratio)


def spread_score(opt_type_a: str, opt_type_b: str, strike_a: float, strike_b: float, 
                 exp_a: str, exp_b: str) -> Tuple[str, float]:
    """
    Determine if two options could form a spread strategy and assign score.
    
    Returns:
        Tuple of (strategy_name, strength_score)
        strategy_name: "vertical", "horizontal", "diagonal", "collar", "none"
        strength_score: 0.0-1.0 indicating how well they fit the strategy
        
    Args:
        opt_type_a: "Call" or "Put"
        opt_type_b: "Call" or "Put"
        strike_a: Strike price of first option
        strike_b: Strike price of second option
        exp_a: Expiration date of first option (YYYY-MM-DD)
        exp_b: Expiration date of second option (YYYY-MM-DD)
    """
    same_type = opt_type_a == opt_type_b
    same_exp = exp_a == exp_b
    strike_diff = abs(strike_a - strike_b)
    strike_ratio = strike_diff / max(strike_a, strike_b, 1.0)
    
    # Collar: Long put + Short call (or vice versa)
    if opt_type_a != opt_type_b and same_exp:
        if 0.05 < strike_ratio < 0.25:  # Strikes reasonably spaced
            return ("collar", 0.85)
        return ("collar", 0.65)
    
    # Vertical spread: Same type, same exp, different strikes
    if same_type and same_exp and strike_a != strike_b:
        if 0.02 < strike_ratio < 0.15:  # Good strike spacing for vertical
            return ("vertical", 0.90)
        return ("vertical", 0.70)
    
    # Horizontal (calendar) spread: Same type, same strike, different exp
    if same_type and not same_exp and strike_a == strike_b:
        return ("horizontal", 0.80)
    
    # Diagonal spread: Same type, different strike AND exp
    if same_type and not same_exp and strike_a != strike_b:
        if 0.02 < strike_ratio < 0.15:
            return ("diagonal", 0.75)
        return ("diagonal", 0.60)
    
    return ("none", 0.0)
