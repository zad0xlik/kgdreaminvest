"""Options data fetcher with provider routing and universal utilities."""
import logging
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

from src.config import Config
from src.market.greeks import enrich_option_with_greeks, calculate_dte

logger = logging.getLogger("kginvest")

# Import both providers at module load time to avoid import deadlocks in multi-threaded contexts
from src.market.yahoo_options_client import get_options_data_yahoo
try:
    from src.market.alpaca_options_client import get_options_data_alpaca
    ALPACA_OPTIONS_AVAILABLE = True
except ImportError as e:
    ALPACA_OPTIONS_AVAILABLE = False
    logger.warning(f"Alpaca options client not available: {e}")


def filter_options_by_criteria(options_df: pd.DataFrame, spot_prices: Dict[str, float]) -> pd.DataFrame:
    """
    Filter options based on configuration criteria (DTE, volume, OI).
    
    Args:
        options_df: DataFrame with options data
        spot_prices: Dict mapping symbol to current spot price
        
    Returns:
        Filtered DataFrame with only liquid options in acceptable DTE range
    """
    if options_df.empty:
        return options_df
    
    # Calculate DTE for each option
    options_df['dte'] = options_df['Expiration'].apply(calculate_dte)
    
    # Filter by DTE range
    filtered = options_df[
        (options_df['dte'] >= Config.OPTIONS_MIN_DTE) &
        (options_df['dte'] <= Config.OPTIONS_MAX_DTE)
    ].copy()
    
    # Filter by volume (liquidity requirement)
    filtered = filtered[
        (filtered['volume'].fillna(0) >= Config.OPTIONS_MIN_VOLUME) |
        (filtered['openInterest'].fillna(0) >= Config.OPTIONS_MIN_OPEN_INTEREST)
    ]
    
    # Enrich with calculated Greeks
    enriched_rows = []
    for _, row in filtered.iterrows():
        symbol = row['Symbol']
        spot = spot_prices.get(symbol, 0)
        if spot > 0:
            enriched = enrich_option_with_greeks(row.to_dict(), spot)
            enriched_rows.append(enriched)
    
    if enriched_rows:
        return pd.DataFrame(enriched_rows)
    else:
        return pd.DataFrame()


def prepare_options_for_llm(options_df: pd.DataFrame, underlying: str) -> List[Dict]:
    """
    Prepare options data for LLM analysis.
    
    Args:
        options_df: DataFrame with options data (must be for single underlying)
        underlying: Ticker symbol of underlying
        
    Returns:
        List of dicts with key option metrics for LLM to analyze
    """
    if options_df.empty:
        return []
    
    # Filter to just this underlying
    symbol_options = options_df[options_df['Symbol'] == underlying].copy()
    
    # Sort by expiration and strike
    symbol_options = symbol_options.sort_values(['Expiration', 'strike'])
    
    # Prepare condensed view for LLM
    llm_data = []
    for _, row in symbol_options.iterrows():
        llm_data.append({
            "contract": row.get('contractSymbol', ''),
            "type": row.get('OptionType', ''),
            "strike": float(row.get('strike', 0)),
            "expiration": row.get('Expiration', ''),
            "dte": int(row.get('dte', 0)),
            "bid": float(row.get('bid', 0)),
            "ask": float(row.get('ask', 0)),
            "last": float(row.get('lastPrice', 0)),
            "volume": int(row.get('volume', 0) or 0),
            "open_interest": int(row.get('openInterest', 0) or 0),
            "iv": float(row.get('impliedVolatility', 0)),
            "delta": float(row.get('delta', 0)),
            "gamma": float(row.get('gamma', 0)),
            "theta": float(row.get('theta', 0)),
            "vega": float(row.get('vega', 0)),
            "in_the_money": bool(row.get('inTheMoney', False))
        })
    
    return llm_data


def get_monitored_options_from_db(conn) -> List[Dict]:
    """
    Get currently monitored options from database.
    
    Args:
        conn: Database connection
        
    Returns:
        List of dicts with monitored option data
    """
    rows = conn.execute("""
        SELECT option_id, underlying, option_type, strike, expiration, 
               contract_symbol, delta, gamma, theta, vega,
               volume, open_interest, implied_volatility, selection_reason
        FROM options_monitored
        WHERE enabled = 1
        ORDER BY underlying, option_type, expiration, strike
    """).fetchall()
    
    return [dict(row) for row in rows]


def update_monitored_option(
    conn,
    underlying: str,
    option_type: str,
    strike: float,
    expiration: str,
    contract_symbol: str,
    greeks: Dict,
    volume: int,
    open_interest: int,
    iv: float,
    reason: str
) -> int:
    """
    Insert or update monitored option in database.
    
    Args:
        conn: Database connection
        underlying: Ticker symbol
        option_type: 'Call' or 'Put'
        strike: Strike price
        expiration: Expiration date string
        contract_symbol: Option contract symbol
        greeks: Dict with delta, gamma, theta, vega
        volume: Daily volume
        open_interest: Open interest
        iv: Implied volatility
        reason: LLM reasoning for selection
        
    Returns:
        option_id of inserted/updated row
    """
    from src.utils import utc_now
    
    # Try to find existing option
    existing = conn.execute("""
        SELECT option_id FROM options_monitored
        WHERE underlying=? AND option_type=? AND strike=? AND expiration=?
    """, (underlying, option_type, float(strike), expiration)).fetchone()
    
    if existing:
        # Update existing
        option_id = existing["option_id"]
        conn.execute("""
            UPDATE options_monitored
            SET contract_symbol=?, last_updated=?, delta=?, gamma=?, theta=?, vega=?,
                volume=?, open_interest=?, implied_volatility=?, selection_reason=?
            WHERE option_id=?
        """, (
            contract_symbol, utc_now(),
            float(greeks.get('delta', 0)), float(greeks.get('gamma', 0)),
            float(greeks.get('theta', 0)), float(greeks.get('vega', 0)),
            int(volume), int(open_interest), float(iv), reason[:500], option_id
        ))
    else:
        # Insert new
        conn.execute("""
            INSERT INTO options_monitored (
                underlying, option_type, strike, expiration, contract_symbol,
                added_at, last_updated, enabled,
                delta, gamma, theta, vega,
                volume, open_interest, implied_volatility, selection_reason
            ) VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)
        """, (
            underlying, option_type, float(strike), expiration, contract_symbol,
            utc_now(), utc_now(),
            float(greeks.get('delta', 0)), float(greeks.get('gamma', 0)),
            float(greeks.get('theta', 0)), float(greeks.get('vega', 0)),
            int(volume), int(open_interest), float(iv), reason[:500]
        ))
        option_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    
    return int(option_id)


def store_options_snapshot(conn, option_id: int, option_data: Dict):
    """
    Store options pricing snapshot in database.
    
    Args:
        conn: Database connection
        option_id: ID of monitored option
        option_data: Dict with bid, ask, last, volume, OI, IV, Greeks
    """
    from src.utils import utc_now
    
    conn.execute("""
        INSERT INTO options_snapshots (
            ts, option_id, bid, ask, last, volume, open_interest,
            implied_volatility, delta, gamma, theta, vega
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        utc_now(), option_id,
        float(option_data.get('bid', 0)), float(option_data.get('ask', 0)),
        float(option_data.get('last', 0)),
        int(option_data.get('volume', 0) or 0),
        int(option_data.get('open_interest', 0) or 0),
        float(option_data.get('iv', 0)),
        float(option_data.get('delta', 0)), float(option_data.get('gamma', 0)),
        float(option_data.get('theta', 0)), float(option_data.get('vega', 0))
    ))


def get_options_data(symbols: List[str]) -> pd.DataFrame:
    """
    Fetch options data for given symbols using configured DATA_PROVIDER.
    
    Routes to Alpaca or Yahoo Finance based on Config.DATA_PROVIDER setting.
    Uses pre-imported modules to avoid import deadlocks in multi-threaded contexts.
    
    Args:
        symbols: List of ticker symbols to fetch options for
        
    Returns:
        DataFrame with all options data (calls and puts) for all symbols
    """
    if Config.DATA_PROVIDER == "alpaca" and ALPACA_OPTIONS_AVAILABLE:
        try:
            logger.info(f"Fetching options data from Alpaca for {len(symbols)} symbols")
            return get_options_data_alpaca(symbols)
        except Exception as e:
            logger.error(f"Alpaca options fetch failed, falling back to Yahoo: {e}")
            logger.debug(f"Full error:", exc_info=True)
            return get_options_data_yahoo(symbols)
    else:
        logger.info(f"Fetching options data from Yahoo Finance for {len(symbols)} symbols")
        return get_options_data_yahoo(symbols)
