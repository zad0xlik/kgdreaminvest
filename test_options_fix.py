#!/usr/bin/env python3
"""Test script to verify options data fetching and template formatting."""

import json
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.market.options_fetcher import get_options_data, filter_options_by_criteria, prepare_options_for_llm
from src.llm.prompts import get_prompt, format_prompt

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger("test_options")

def test_options_fetch():
    """Test fetching options data from Yahoo Finance."""
    print("\n" + "="*60)
    print("TEST 1: Fetching Options Data from Yahoo Finance")
    print("="*60)
    
    test_symbols = ["AAPL"]  # Use a single liquid stock for testing
    
    print(f"\nFetching options for: {test_symbols}")
    options_df = get_options_data(test_symbols)
    
    if options_df.empty:
        print("❌ FAILED: No options data returned")
        return False
    
    print(f"✅ SUCCESS: Fetched {len(options_df)} options contracts")
    print(f"\nSample data (first 3 rows):")
    print(options_df.head(3)[['Symbol', 'OptionType', 'strike', 'Expiration', 'volume', 'openInterest']])
    
    return True

def test_template_formatting():
    """Test that the prompt template formats correctly without errors."""
    print("\n" + "="*60)
    print("TEST 2: Template Formatting (The Bug Fix)")
    print("="*60)
    
    # Load the options prompt
    prompt_config = get_prompt("options", "select_chains", force_reload=True)
    
    if not prompt_config:
        print("❌ FAILED: Could not load options prompt")
        return False
    
    print("\n✅ Prompt loaded successfully")
    
    # Test data
    test_options = [
        {
            "contract": "AAPL250117C00200000",
            "type": "Call",
            "strike": 200.0,
            "expiration": "2025-01-17",
            "dte": 18,
            "bid": 5.0,
            "ask": 5.5,
            "last": 5.2,
            "volume": 10000,
            "open_interest": 50000,
            "iv": 0.25,
            "delta": 0.55,
            "gamma": 0.02,
            "theta": -0.15,
            "vega": 0.30,
            "in_the_money": True
        }
    ]
    
    # Try to format the template - this is where the bug was happening
    try:
        formatted_user = format_prompt(
            prompt_config["user_template"],
            ticker="AAPL",
            spot_price=205.50,
            options_json=json.dumps(test_options, indent=2),
            max_allocation_pct=10.0,
            min_volume=500,
            min_open_interest=1000
        )
        
        print("✅ SUCCESS: Template formatted without errors!")
        print(f"\nFormatted prompt length: {len(formatted_user)} characters")
        print(f"\nFirst 500 characters of formatted prompt:")
        print("-" * 60)
        print(formatted_user[:500])
        print("-" * 60)
        
        # Verify the JSON example is in the prompt
        if '{"' in formatted_user and '"selected_options"' in formatted_user:
            print("✅ JSON example structure preserved in output")
        else:
            print("⚠️  WARNING: JSON example structure may be malformed")
        
        return True
        
    except KeyError as e:
        print(f"❌ FAILED: Missing template variable: {e}")
        print("This is the bug we were trying to fix!")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error: {e}")
        return False

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("OPTIONS TRADING FIX VERIFICATION")
    print("="*60)
    print("\nThis script tests:")
    print("1. Options data is being fetched successfully from Yahoo Finance")
    print("2. Template formatting works after escaping curly braces")
    print("")
    
    results = []
    
    # Test 1: Options fetching
    results.append(("Options Data Fetch", test_options_fetch()))
    
    # Test 2: Template formatting
    results.append(("Template Formatting", test_template_formatting()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! The fix is working correctly.")
        print("\nNext steps:")
        print("1. Restart your application")
        print("2. Wait for options worker cycle (~6 minutes)")
        print("3. Check logs for 'LLM selected X options' (should see no more template errors)")
    else:
        print("⚠️  SOME TESTS FAILED - Please review errors above")
    print("="*60 + "\n")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
