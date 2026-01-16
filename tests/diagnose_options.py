#!/usr/bin/env python3
"""
Diagnostic script to identify why options trades are not being placed.
Checks database state, worker status, and configuration.
"""
import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.database import db_conn


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_configuration():
    """Check options-related configuration."""
    print_header("OPTIONS CONFIGURATION")
    
    config_items = [
        ("OPTIONS_ENABLED", Config.OPTIONS_ENABLED, "Should be true"),
        ("BROKER_PROVIDER", Config.BROKER_PROVIDER, "'alpaca' for real trades, 'paper' for paper"),
        ("DATA_PROVIDER", Config.DATA_PROVIDER, "'alpaca' or 'yahoo'"),
        ("OPTIONS_MAX_ALLOCATION_PCT", f"{Config.OPTIONS_MAX_ALLOCATION_PCT}%", "Max portfolio in options"),
        ("OPTIONS_WORKER_SPEED", Config.OPTIONS_WORKER_SPEED, "ticks/min"),
        ("OPTIONS_INTERVAL", f"{Config.OPTIONS_INTERVAL:.0f}s", "~6 min at 0.17 speed"),
        ("OPTIONS_MIN_VOLUME", Config.OPTIONS_MIN_VOLUME, "Or OI filter"),
        ("OPTIONS_MIN_OPEN_INTEREST", Config.OPTIONS_MIN_OPEN_INTEREST, "Or volume filter"),
        ("OPTIONS_MIN_DTE", f"{Config.OPTIONS_MIN_DTE} days", "Min days to expiry"),
        ("OPTIONS_MAX_DTE", f"{Config.OPTIONS_MAX_DTE} days", "Max days to expiry"),
        ("OPTIONS_LLM_CALLS_PER_MIN", Config.OPTIONS_LLM_CALLS_PER_MIN, "Shared by both workers!"),
        ("OPTIONS_MIN_TRADE_NOTIONAL", f"${Config.OPTIONS_MIN_TRADE_NOTIONAL}", "Min trade size"),
        ("OPTIONS_MAX_SINGLE_OPTION_PCT", f"{Config.OPTIONS_MAX_SINGLE_OPTION_PCT}%", "Max per single option"),
    ]
    
    for name, value, note in config_items:
        status = "✅" if value else "❌"
        if name == "OPTIONS_ENABLED" and not value:
            status = "❌ CRITICAL"
        print(f"  {status} {name}: {value}  ({note})")
    
    # Critical check
    if not Config.OPTIONS_ENABLED:
        print("\n  🚨 OPTIONS_ENABLED=false - Options trading is disabled!")
        return False
    return True


def check_database_tables():
    """Check if required options tables exist."""
    print_header("DATABASE TABLES")
    
    with db_conn() as conn:
        tables = ["options_monitored", "options_positions", "options_trades", "options_snapshots"]
        
        for table in tables:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            
            if result:
                count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()["cnt"]
                print(f"  ✅ {table}: {count} rows")
            else:
                print(f"  ❌ {table}: TABLE MISSING!")


def check_monitored_options():
    """Check monitored options - critical for trading to work."""
    print_header("MONITORED OPTIONS (Critical for Trading)")
    
    with db_conn() as conn:
        # Total monitored
        total = conn.execute("SELECT COUNT(*) as cnt FROM options_monitored").fetchone()["cnt"]
        enabled = conn.execute("SELECT COUNT(*) as cnt FROM options_monitored WHERE enabled=1").fetchone()["cnt"]
        
        print(f"  Total monitored options: {total}")
        print(f"  Enabled options: {enabled}")
        
        if enabled == 0:
            print("\n  🚨 NO ENABLED MONITORED OPTIONS!")
            print("  The OptionsThinkWorker cannot make trades without monitored options.")
            print("  This means OptionsWorker has not successfully selected any options.")
            print("\n  Possible causes:")
            print("    1. Options data fetch failing (check logs)")
            print("    2. All options filtered out by DTE/volume/OI criteria")
            print("    3. LLM failing to select options (JSON parsing errors)")
            print("    4. LLM budget exhausted before selection")
        else:
            # Show sample
            print("\n  Recent monitored options:")
            rows = conn.execute("""
                SELECT underlying, option_type, strike, expiration, selection_reason, last_updated
                FROM options_monitored
                WHERE enabled=1
                ORDER BY last_updated DESC
                LIMIT 5
            """).fetchall()
            
            for r in rows:
                print(f"    • {r['underlying']} {r['strike']}{r['option_type'][0]} exp:{r['expiration']}")
                print(f"      Reason: {r['selection_reason'][:60]}...")
                print(f"      Updated: {r['last_updated']}")


def check_options_positions():
    """Check current options positions."""
    print_header("OPTIONS POSITIONS")
    
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT op.*, om.underlying, om.option_type, om.strike, om.expiration
            FROM options_positions op
            JOIN options_monitored om ON op.option_id = om.option_id
            WHERE op.qty > 0
        """).fetchall()
        
        if not rows:
            print("  No open options positions.")
        else:
            print(f"  Open positions: {len(rows)}")
            for r in rows:
                notional = r['qty'] * r['last_price'] * 100
                pl = (r['last_price'] - r['avg_cost']) * r['qty'] * 100
                print(f"    • {r['underlying']} {r['strike']}{r['option_type'][0]} exp:{r['expiration']}")
                print(f"      Qty: {r['qty']}, Avg Cost: ${r['avg_cost']:.2f}, Last: ${r['last_price']:.2f}")
                print(f"      Notional: ${notional:.2f}, P&L: ${pl:.2f}")


def check_options_trades():
    """Check options trades history."""
    print_header("OPTIONS TRADES (Last 10)")
    
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT ot.*, om.underlying, om.option_type, om.strike, om.expiration
            FROM options_trades ot
            JOIN options_monitored om ON ot.option_id = om.option_id
            ORDER BY ot.ts DESC
            LIMIT 10
        """).fetchall()
        
        if not rows:
            print("  ❌ NO OPTIONS TRADES FOUND!")
            print("     No trades have ever been executed.")
        else:
            print(f"  Found {len(rows)} recent trades:")
            for r in rows:
                symbol = f"{r['underlying']} {r['strike']}{r['option_type'][0]}"
                print(f"    • {r['ts']}: {r['side']} {r['qty']}x {symbol} @ ${r['price']:.2f}")
                print(f"      Reason: {r['reason'][:60]}...")


def check_options_snapshots():
    """Check options snapshot data."""
    print_header("OPTIONS SNAPSHOTS")
    
    with db_conn() as conn:
        # Latest snapshots
        count = conn.execute("SELECT COUNT(*) as cnt FROM options_snapshots").fetchone()["cnt"]
        print(f"  Total snapshots: {count}")
        
        if count > 0:
            latest = conn.execute("""
                SELECT ts, option_id FROM options_snapshots
                ORDER BY ts DESC LIMIT 1
            """).fetchone()
            print(f"  Latest snapshot: {latest['ts']}")


def check_events_log():
    """Check events log for options-related issues."""
    print_header("RECENT OPTIONS EVENTS (Last 20)")
    
    with db_conn() as conn:
        # Check if events table exists
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        
        if not table_exists:
            print("  ⚠️  Events table does not exist in database.")
            print("  Checking log_entries table instead...")
            
            # Try log_entries table
            log_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='log_entries'"
            ).fetchone()
            
            if log_table:
                rows = conn.execute("""
                    SELECT ts, category, action, detail
                    FROM log_entries
                    WHERE category LIKE '%options%' OR category = 'alpaca_options_trading'
                    ORDER BY rowid DESC
                    LIMIT 20
                """).fetchall()
                
                if not rows:
                    print("  No options-related log entries found.")
                else:
                    for r in rows:
                        detail_short = r['detail'][:70] if r['detail'] else ""
                        print(f"  {r['ts']}: [{r['category']}] {r['action']}")
                        if detail_short:
                            print(f"    {detail_short}...")
            else:
                print("  No events/log_entries table found. Try checking log file directly:")
                print("  tail -100 data/kginvest_live.log | grep -i options")
            return
        
        rows = conn.execute("""
            SELECT ts, category, action, detail
            FROM events
            WHERE category LIKE '%options%' OR category = 'alpaca_options_trading'
            ORDER BY event_id DESC
            LIMIT 20
        """).fetchall()
        
        if not rows:
            print("  No options-related events found.")
            print("  This suggests the options workers may not be running at all.")
        else:
            for r in rows:
                detail_short = r['detail'][:70] if r['detail'] else ""
                print(f"  {r['ts']}: [{r['category']}] {r['action']}")
                if detail_short:
                    print(f"    {detail_short}...")


def check_portfolio_state():
    """Check if portfolio has room for options."""
    print_header("PORTFOLIO STATE")
    
    try:
        from src.database.operations import portfolio_state, get_cash
        
        with db_conn() as conn:
            # Get cash using the actual function
            cash = get_cash(conn)
            
            # Get portfolio state
            pf = portfolio_state(conn, prices={})
            total_equity = pf.get("equity", cash)
            
            print(f"  Cash: ${cash:,.2f}")
            print(f"  Total Equity: ${total_equity:,.2f}")
            
            # Check options allocation room
            max_options = total_equity * (Config.OPTIONS_MAX_ALLOCATION_PCT / 100)
            print(f"\n  Max Options Allocation ({Config.OPTIONS_MAX_ALLOCATION_PCT}%): ${max_options:,.2f}")
            
            # Current options value
            options_value = conn.execute("""
                SELECT COALESCE(SUM(op.qty * op.last_price * 100), 0) as total
                FROM options_positions op
                WHERE op.qty > 0
            """).fetchone()["total"]
            
            options_pct = (options_value / total_equity * 100) if total_equity > 0 else 0
            print(f"  Current Options Value: ${options_value:,.2f} ({options_pct:.1f}%)")
            
            remaining = max_options - options_value
            print(f"  Room for Options: ${remaining:,.2f}")
    except Exception as e:
        print(f"  ⚠️  Error checking portfolio state: {e}")
        print("  This may indicate the portfolio tables have a different schema.")


def main():
    print("\n" + "🔍" + " " * 20 + "OPTIONS TRADING DIAGNOSTICS" + " " * 20 + "🔍")
    
    # Run all checks
    config_ok = check_configuration()
    if not config_ok:
        print("\n🛑 STOP: Fix configuration first before other checks.")
        return
    
    check_database_tables()
    check_monitored_options()
    check_options_positions()
    check_options_trades()
    check_options_snapshots()
    check_events_log()
    check_portfolio_state()
    
    print_header("SUMMARY & RECOMMENDATIONS")
    
    with db_conn() as conn:
        monitored = conn.execute("SELECT COUNT(*) as cnt FROM options_monitored WHERE enabled=1").fetchone()["cnt"]
        trades = conn.execute("SELECT COUNT(*) as cnt FROM options_trades").fetchone()["cnt"]
    
    if monitored == 0:
        print("""
  🚨 ROOT CAUSE LIKELY: No monitored options in database
  
  The OptionsWorker is not successfully selecting options to monitor.
  This blocks the entire trading pipeline.
  
  NEXT STEPS:
  1. Check the log file: data/kginvest_live.log
  2. Look for these messages:
     - "No options data fetched" → Data fetch failing
     - "No options passed liquidity/DTE filters" → Filters too strict
     - "LLM failed to return valid options selection" → LLM issue
     - "Options LLM budget exhausted" → Need more LLM budget
  
  3. Try relaxing filters:
     OPTIONS_MIN_VOLUME=100
     OPTIONS_MIN_OPEN_INTEREST=500
  
  4. Increase LLM budget:
     OPTIONS_LLM_CALLS_PER_MIN=10
""")
    elif trades == 0:
        print("""
  🚨 ROOT CAUSE LIKELY: OptionsThinkWorker not generating trades
  
  Options are being monitored but no trades executed.
  
  NEXT STEPS:
  1. Check if OptionsThinkWorker is running (check logs)
  2. Look for "Options trading decisions from LLM" messages
  3. Check if LLM is returning valid BUY decisions
  4. Verify enough room in portfolio allocation
""")
    else:
        print(f"""
  ✅ System appears configured correctly
  
  Monitored options: {monitored}
  Total trades: {trades}
  
  If recent trades are missing, check:
  1. Market hours (options only trade during market hours)
  2. LLM decision quality (may be returning HOLD)
  3. Recent log entries for skipped trades
""")


if __name__ == "__main__":
    main()
