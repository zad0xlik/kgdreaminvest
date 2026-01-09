"""Yahoo Finance options data client using yfinance."""
import logging
from typing import List

import pandas as pd
import yfinance as yf

logger = logging.getLogger("kginvest")


def get_options_data_yahoo(symbols: List[str]) -> pd.DataFrame:
    """
    Fetch options data for given symbols from yfinance.
    
    Args:
        symbols: List of ticker symbols to fetch options for
        
    Returns:
        DataFrame with all options data (calls and puts) for all symbols
        
    Columns include:
        contractSymbol, lastTradeDate, strike, lastPrice, bid, ask, change, 
        percentChange, volume, openInterest, impliedVolatility, inTheMoney,
        contractSize, currency, Symbol, OptionType, Expiration
    """
    all_options_data = []

    for symbol in symbols:
        try:
            # Fetch the stock data
            stock = yf.Ticker(symbol)

            # Get all available expiration dates
            expirations = stock.options

            for expiration in expirations:
                # Fetch both calls and puts for this expiration (cache chain to avoid double API call)
                chain = stock.option_chain(expiration)
                calls = chain.calls
                puts = chain.puts

                # Add symbol and expiration information
                calls['Symbol'] = symbol
                calls['OptionType'] = 'Call'
                calls['Expiration'] = expiration

                puts['Symbol'] = symbol
                puts['OptionType'] = 'Put'
                puts['Expiration'] = expiration

                # Combine calls and puts
                options = pd.concat([calls, puts])

                # Add to the main list
                all_options_data.append(options)

            logger.info(f"Successfully fetched options data for {symbol} from Yahoo Finance")
        except Exception as e:
            logger.error(f"Error fetching Yahoo options data for {symbol}: {str(e)}")

    # Combine all data into a single DataFrame
    if all_options_data:
        combined_options = pd.concat(all_options_data, ignore_index=True)
        return combined_options
    else:
        return pd.DataFrame()
