"""Market regime signals derived from bellwether indicators."""
from typing import Dict, Any, Optional, List

from src.utils import clamp01


def compute_signals_from_bells(
    prices: Dict[str, Dict[str, Any]], 
    bellwethers: Optional[List[str]] = None
) -> Dict[str, float]:
    """
    Derive simple, explainable market regime signals from bellwethers.
    
    Computes four normalized signals (0-1 range) based on bellwether changes:
    - risk_off: Higher when VIX up, USD up, equities down
    - rates_up: Higher when yields rise
    - oil_shock: Higher when crude spikes
    - semi_pulse: Higher when semis show strength
    
    Uses smart fallback logic:
    - Prefers Yahoo-specific symbols (^VIX, ^TNX, CL=F) when available
    - Falls back to ETF proxies (VXX, IEF, USO) otherwise
    
    Args:
        prices: Dict mapping ticker to price data with 'change_pct' key
        bellwethers: Optional list of bellwether tickers to use. If None,
                     uses all available bellwethers from prices.
        
    Returns:
        Dict with signal names to 0-1 float values
        
    Example:
        >>> prices = {
        ...     "^VIX": {"change_pct": 5.0},
        ...     "SPY": {"change_pct": -1.0},
        ...     "UUP": {"change_pct": 0.5}
        ... }
        >>> signals = compute_signals_from_bells(prices)
        >>> print(f"Risk-off: {signals['risk_off']:.2f}")
        
    Note:
        Signal formulas are resilient to missing tickers. If a bellwether
        is not available in prices, its contribution defaults to 0.0 (neutral).
    """
    def ch(sym: str) -> float:
        """Helper to get change_pct safely."""
        return float(prices.get(sym, {}).get("change_pct", 0.0) or 0.0)

    # Get bellwether changes with smart fallback (prefer Yahoo-specific, use ETF proxies as backup)
    # Volatility: prefer ^VIX index, fall back to VXX ETF
    vix = ch("^VIX") if "^VIX" in prices else ch("VXX")
    
    # Standard equities
    spy = ch("SPY")
    qqq = ch("QQQ")
    tlt = ch("TLT")
    
    # USD strength: prefer DX-Y.NYB dollar index, fall back to UUP ETF
    usd = ch("DX-Y.NYB") if "DX-Y.NYB" in prices else ch("UUP")
    
    # 10Y yield: prefer ^TNX direct yield, fall back to IEF bond ETF (inverse relationship)
    # Note: IEF moves inversely to yields, so we need to handle this difference
    if "^TNX" in prices:
        tnx = ch("^TNX")
    elif "IEF" in prices:
        # IEF moves opposite to yields, so negate it
        tnx = -ch("IEF")
    else:
        tnx = 0.0
    
    # Oil: prefer CL=F futures, fall back to USO fund
    oil = ch("CL=F") if "CL=F" in prices else ch("USO")
    
    # Semiconductors
    tsm = ch("TSM")

    # Normalize and combine (heuristic formulas)
    # Each signal starts at 0.50 (neutral) and adjusts based on moves
    
    # Risk-off: VIX up, USD up, equities down, bonds up
    risk_off = clamp01(
        0.50 + 0.06 * vix + 0.05 * usd - 0.05 * spy - 0.03 * qqq + 0.03 * tlt
    )
    
    # Rates up: 10Y yield up, bonds down
    rates_up = clamp01(
        0.50 + 0.10 * tnx - 0.03 * tlt
    )
    
    # Oil shock: Crude up
    oil_shock = clamp01(
        0.50 + 0.06 * oil
    )
    
    # Semiconductor pulse: TSM and QQQ strength
    semi_pulse = clamp01(
        0.50 + 0.06 * tsm + 0.03 * qqq
    )

    return {
        "risk_off": round(float(risk_off), 3),
        "rates_up": round(float(rates_up), 3),
        "oil_shock": round(float(oil_shock), 3),
        "semi_pulse": round(float(semi_pulse), 3),
    }
