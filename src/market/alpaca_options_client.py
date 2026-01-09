"""Alpaca options data client."""
import logging
from datetime import datetime
from typing import List, Dict

import pandas as pd
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest

from src.config import Config
from src.market.greeks import calculate_dte

logger = logging.getLogger("kginvest")


def get_options_data_alpaca(symbols: List[str]) -> pd.DataFrame:
    """
    Fetch options data for given symbols from Alpaca.
    
    Args:
        symbols: List of ticker symbols to fetch options for
        
    Returns:
        DataFrame with all options data (calls and puts) for all symbols
        
    Columns include:
        contractSymbol, lastTradeDate, strike, lastPrice, bid, ask, change, 
        percentChange, volume, openInterest, impliedVolatility, inTheMoney,
        contractSize, currency, Symbol, OptionType, Expiration, delta, gamma,
        theta, vega, rho
    """
    if not Config.ALPACA_API_KEY or not Config.ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not configured for options data")
        return pd.DataFrame()
    
    # Initialize Alpaca options client
    client = OptionHistoricalDataClient(
        api_key=Config.ALPACA_API_KEY,
        secret_key=Config.ALPACA_SECRET_KEY
    )
    
    all_options_data = []

    for symbol in symbols:
        try:
            # Fetch option chain for this underlying
            # This gets ALL available options with greeks in ONE API call!
            request = OptionChainRequest(underlying_symbol=symbol)
            chain = client.get_option_chain(request)
            
            if not chain:
                logger.warning(f"No option chain data for {symbol}")
                continue
            
            # Convert Alpaca format to our DataFrame format
            for contract_symbol, snapshot in chain.items():
                # Parse contract symbol to extract type, strike, expiration
                # Format: AAPL260117C00150000 = AAPL, exp 2026-01-17, Call, strike 150.00
                # Format: BRKB261218P00270000 = BRK.B, exp 2026-12-18, Put, strike 270.00
                # Note: Input symbol might be "BRK.B" but contract uses "BRKB" (no dot)
                try:
                    import re
                    
                    # Use regex to find the date pattern (6 digits followed by C/P and 8 digits)
                    # This handles any ticker length including symbols with dots (BRK.B -> BRKB)
                    match = re.search(r'(\d{6})([CP])(\d{8})$', contract_symbol)
                    
                    if not match:
                        logger.warning(f"Failed to match OCC format in contract symbol {contract_symbol}")
                        continue
                    
                    exp_date_str = match.group(1)  # YYMMDD
                    option_type_char = match.group(2)  # C or P
                    strike_str = match.group(3)  # Strike * 1000
                    
                    # Extract underlying ticker (everything before the date)
                    underlying = contract_symbol[:match.start()]
                    
                    # Parse expiration
                    year = int("20" + exp_date_str[0:2])
                    month = int(exp_date_str[2:4])
                    day = int(exp_date_str[4:6])
                    expiration = f"{year}-{month:02d}-{day:02d}"
                    
                    # Parse option type
                    option_type = "Call" if option_type_char == "C" else "Put"
                    
                    # Parse strike (divided by 1000)
                    strike = float(strike_str) / 1000.0
                    
                except Exception as e:
                    logger.warning(f"Failed to parse contract symbol {contract_symbol}: {e}")
                    continue
                
                # Extract data from snapshot
                latest_quote = snapshot.latest_quote
                latest_trade = snapshot.latest_trade
                greeks = snapshot.greeks
                
                # Build data row
                row = {
                    'contractSymbol': contract_symbol,
                    'Symbol': underlying,
                    'OptionType': option_type,
                    'Expiration': expiration,
                    'strike': strike,
                    
                    # Quote data
                    'bid': float(latest_quote.bid_price) if latest_quote else 0.0,
                    'ask': float(latest_quote.ask_price) if latest_quote else 0.0,
                    'bidSize': int(latest_quote.bid_size) if latest_quote else 0,
                    'askSize': int(latest_quote.ask_size) if latest_quote else 0,
                    
                    # Trade data
                    'lastPrice': float(latest_trade.price) if latest_trade else 0.0,
                    'volume': int(latest_trade.size) if latest_trade else 0,
                    'lastTradeDate': latest_trade.timestamp if latest_trade else None,
                    
                    # Greeks (from Alpaca, not calculated!)
                    'delta': float(greeks.delta) if greeks and greeks.delta else 0.0,
                    'gamma': float(greeks.gamma) if greeks and greeks.gamma else 0.0,
                    'theta': float(greeks.theta) if greeks and greeks.theta else 0.0,
                    'vega': float(greeks.vega) if greeks and greeks.vega else 0.0,
                    'rho': float(greeks.rho) if greeks and greeks.rho else 0.0,
                    
                    # IV and other data
                    'impliedVolatility': float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0,
                    
                    # Placeholder for fields Yahoo provides but Alpaca doesn't directly
                    'openInterest': 0,  # Alpaca doesn't provide OI in snapshot
                    'change': 0.0,
                    'percentChange': 0.0,
                    'inTheMoney': (option_type == "Call" and strike < 0) or (option_type == "Put" and strike > 0),  # Will calculate properly
                    'contractSize': "REGULAR",
                    'currency': "USD"
                }
                
                all_options_data.append(row)
            
            logger.info(f"Successfully fetched {len(chain)} option contracts for {symbol} from Alpaca")
            
        except Exception as e:
            logger.error(f"Error fetching Alpaca options data for {symbol}: {str(e)}")
            logger.debug(f"Full error:", exc_info=True)
            continue

    # Combine all data into a single DataFrame
    if all_options_data:
        combined_options = pd.DataFrame(all_options_data)
        return combined_options
    else:
        return pd.DataFrame()
