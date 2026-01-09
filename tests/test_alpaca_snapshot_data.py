#!/usr/bin/env python3
"""
Diagnostic test script for Alpaca snapshot data.

Tests what Alpaca returns for bellwether symbols during market closed hours.
NO try-except blocks - let errors surface naturally.

Usage:
    python tests/test_alpaca_snapshot_data.py
"""

import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config

# Test symbols from the Latest Snapshot UI
TEST_SYMBOLS = ["SPY", "QQQ", "VIX", "UUP"]

print("=" * 70)
print("ALPACA SNAPSHOT DATA DIAGNOSTIC TEST")
print("=" * 70)
print(f"Time: {datetime.now()}")
print(f"API Key configured: {bool(Config.ALPACA_API_KEY)}")
print(f"Paper mode: {Config.ALPACA_PAPER_MODE}")
print(f"Test symbols: {', '.join(TEST_SYMBOLS)}")
print("=" * 70)
print()

# Import Alpaca libraries (will fail if not installed/configured)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

# Create client
print("[1] Creating Alpaca client...")
client = StockHistoricalDataClient(
    Config.ALPACA_API_KEY,
    Config.ALPACA_SECRET_KEY
)
print("✓ Client created successfully")
print()

# Test 1: Historical Bars (what market worker uses)
print("=" * 70)
print("[2] TESTING HISTORICAL BARS (last 5 days)")
print("=" * 70)

end = datetime.now()
start = end - timedelta(days=5)

for symbol in TEST_SYMBOLS:
    print(f"\n[{symbol}] Requesting bars from {start.date()} to {end.date()}...")
    
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )
    
    # NO try-except - let it fail naturally
    bars_response = client.get_stock_bars(request)
    
    print(f"  Response type: {type(bars_response)}")
    print(f"  Response object: {bars_response}")
    
    # BarSet is a Pydantic model - try to access data attribute
    if hasattr(bars_response, 'data') and bars_response.data:
        print(f"  Data attribute type: {type(bars_response.data)}")
        print(f"  Data contents: {bars_response.data}")
        
        if symbol in bars_response.data:
            symbol_bars = bars_response.data[symbol]
            print(f"  ✓ Symbol found in data.{symbol}")
            print(f"  Bars count: {len(symbol_bars)}")
            
            if symbol_bars:
                latest = symbol_bars[-1]
                previous = symbol_bars[-2] if len(symbol_bars) >= 2 else None
                
                print(f"  Latest bar:")
                print(f"    Timestamp: {latest.timestamp}")
                print(f"    Close: ${latest.close:.2f}")
                print(f"    Volume: {latest.volume:,}")
                
                if previous:
                    change_pct = ((latest.close - previous.close) / previous.close) * 100
                    print(f"  Previous close: ${previous.close:.2f}")
                    print(f"  Change: {change_pct:+.2f}%")
                else:
                    print(f"  Previous close: N/A (only 1 bar)")
            else:
                print(f"  ⚠️  Empty bars list!")
        else:
            print(f"  ⚠️  Symbol '{symbol}' NOT IN data dict")
            print(f"  Available in data: {list(bars_response.data.keys())}")
    else:
        print(f"  ⚠️  No 'data' attribute or data is empty")
        print(f"  BarSet attributes: {dir(bars_response)}")

print()
print("=" * 70)
print("[3] TESTING LATEST QUOTES (real-time alternative)")
print("=" * 70)

for symbol in TEST_SYMBOLS:
    print(f"\n[{symbol}] Requesting latest quote...")
    
    request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    
    # NO try-except - let it fail naturally
    quotes_response = client.get_stock_latest_quote(request)
    
    print(f"  Response type: {type(quotes_response)}")
    
    # Handle dict-like access for quotes
    if hasattr(quotes_response, '__getitem__'):
        try:
            quote = quotes_response[symbol]
            print(f"  ✓ Quote found")
            print(f"  Quote data:")
            print(f"    Timestamp: {quote.timestamp}")
            print(f"    Bid: ${quote.bid_price:.2f} (size: {quote.bid_size})")
            print(f"    Ask: ${quote.ask_price:.2f} (size: {quote.ask_size})")
            print(f"    Spread: ${quote.ask_price - quote.bid_price:.2f}")
        except KeyError:
            print(f"  ⚠️  Symbol '{symbol}' NOT FOUND")
            if hasattr(quotes_response, 'keys'):
                print(f"  Available: {list(quotes_response.keys())}")
    else:
        print(f"  ⚠️  Unexpected response format")
        print(f"  Response: {quotes_response}")

print()
print("=" * 70)
print("[4] ANALYSIS SUMMARY")
print("=" * 70)

# Test using our actual client function
print("\n[Testing our fetch_single_ticker_alpaca function]")

from src.market.alpaca_stocks_client import fetch_single_ticker_alpaca

for symbol in TEST_SYMBOLS:
    print(f"\n[{symbol}]")
    sym, data = fetch_single_ticker_alpaca(symbol)
    
    if data:
        print(f"  ✓ SUCCESS - Got data")
        print(f"    Current: ${data['current']:.2f}")
        print(f"    Previous: ${data['previous']:.2f}")
        print(f"    Change: {data['change_pct']:+.2f}%")
        print(f"    History length: {len(data.get('history', []))}")
    else:
        print(f"  ✗ FAILED - Returned None")
        print(f"  This symbol will show '—' in Latest Snapshot UI")

print()
print("=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
print("\nNEXT STEPS:")
print("1. Review which symbols succeeded vs failed")
print("2. Check if VIX is supported by Alpaca (it's an index)")
print("3. Determine if failures are due to:")
print("   - Symbol not tradable on Alpaca")
print("   - Market closed and no recent data")
print("   - API rate limiting")
print("   - Network issues")
print()
