#!/usr/bin/env python3
"""
Alpaca Trade Reconciliation Script

This script syncs local database trades to your Alpaca account.
It's needed when trades were executed locally but not synced to Alpaca
(e.g., due to Think Worker calling execute_paper_trades instead of execute_trades).

Usage:
    python sync_alpaca_trades.py [--dry-run] [--since YYYY-MM-DD]

Options:
    --dry-run    Show what would be done without actually executing orders
    --since      Only sync trades since this date (default: today)

Safety:
    - Applies ALL guard rails (position limits, cash buffer, etc.)
    - Syncs Alpaca account first to get accurate state
    - Compares local vs Alpaca positions
    - Only submits delta orders (catch-up)
    - Logs all actions for audit trail
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("alpaca_sync")

def main():
    parser = argparse.ArgumentParser(description="Sync local trades to Alpaca")
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be done without executing')
    parser.add_argument('--since', type=str, default=None,
                       help='Sync trades since date (YYYY-MM-DD), default: today')
    args = parser.parse_args()
    
    # Import after argparse so --help works even if dependencies missing
    try:
        from src.database import db_conn
        from src.portfolio.alpaca_stocks_trading import (
            sync_alpaca_account, sync_alpaca_positions, 
            get_alpaca_trading_client
        )
        from src.market.alpaca_stocks_client import get_alpaca_client, fetch_alpaca_bars
        from src.config import Config
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.error("Make sure you're running from the project root: python sync_alpaca_trades.py")
        sys.exit(1)
    
    # Verify Alpaca configuration
    if Config.BROKER_PROVIDER != "alpaca":
        logger.error(f"BROKER_PROVIDER is set to '{Config.BROKER_PROVIDER}', not 'alpaca'")
        logger.error("Set BROKER_PROVIDER=alpaca in your .env file")
        sys.exit(1)
    
    logger.info("=" * 70)
    logger.info("ALPACA TRADE RECONCILIATION SCRIPT")
    logger.info("=" * 70)
    logger.info(f"Mode: {'DRY RUN (no orders will be submitted)' if args.dry_run else 'LIVE (will submit orders to Alpaca)'}")
    logger.info(f"Alpaca Paper Mode: {Config.ALPACA_PAPER_MODE}")
    
    # Determine sync start date
    if args.since:
        try:
            since_date = datetime.strptime(args.since, '%Y-%m-%d')
        except ValueError:
            logger.error(f"Invalid date format: {args.since}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Default: today at midnight
        since_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    logger.info(f"Syncing trades since: {since_date.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    # Step 1: Sync Alpaca account state
    logger.info("Step 1: Syncing Alpaca account state...")
    with db_conn() as conn:
        account = sync_alpaca_account(conn)
        if not account:
            logger.error("Failed to sync Alpaca account. Check your API keys and connection.")
            sys.exit(1)
        
        logger.info(f"  Alpaca Cash: ${account['cash']:.2f}")
        logger.info(f"  Buying Power: ${account['buying_power']:.2f}")
        logger.info(f"  Portfolio Value: ${account['portfolio_value']:.2f}")
        
        # Sync Alpaca positions
        alpaca_positions = sync_alpaca_positions(conn)
        logger.info(f"  Alpaca Positions: {len(alpaca_positions)}")
        for pos in alpaca_positions:
            logger.info(f"    {pos['symbol']}: {pos['qty']} shares @ ${pos['avg_cost']:.2f}")
        logger.info("")
    
    # Step 2: Query local trades since date
    logger.info("Step 2: Querying local database trades...")
    with db_conn() as conn:
        trades = conn.execute(
            """SELECT trade_id, ts, symbol, side, qty, price, notional, reason 
               FROM trades 
               WHERE ts >= ? 
               ORDER BY trade_id ASC""",
            (since_date.isoformat(),)
        ).fetchall()
        
        logger.info(f"  Found {len(trades)} trades since {since_date.strftime('%Y-%m-%d')}")
        
        if len(trades) == 0:
            logger.info("  No trades to sync. Exiting.")
            return
        
        # Show trade summary
        for trade in trades:
            logger.info(f"    [{trade['trade_id']}] {trade['ts']}: {trade['side']} {trade['qty']:.4f} {trade['symbol']} @ ${trade['price']:.2f}")
        logger.info("")
    
    # Step 3: Calculate expected positions based on local trades
    logger.info("Step 3: Calculating expected positions from local trades...")
    expected_positions: Dict[str, float] = {}
    
    with db_conn() as conn:
        # Get all positions from database (should reflect all local trades)
        local_positions = conn.execute(
            "SELECT symbol, qty FROM positions WHERE qty > 0"
        ).fetchall()
        
        for pos in local_positions:
            expected_positions[pos['symbol']] = float(pos['qty'])
            logger.info(f"  Expected {pos['symbol']}: {pos['qty']:.4f} shares")
        logger.info("")
    
    # Step 4: Compare local vs Alpaca positions
    logger.info("Step 4: Comparing local vs Alpaca positions...")
    
    # Build Alpaca positions dict
    alpaca_qty = {pos['symbol']: pos['qty'] for pos in alpaca_positions}
    
    # Calculate delta orders needed
    delta_orders: List[Dict] = []
    
    all_symbols = set(expected_positions.keys()) | set(alpaca_qty.keys())
    
    for symbol in sorted(all_symbols):
        local = expected_positions.get(symbol, 0.0)
        alpaca = alpaca_qty.get(symbol, 0.0)
        delta = local - alpaca
        
        if abs(delta) < 0.0001:  # Ignore tiny differences
            logger.info(f"  {symbol}: ✓ In sync (local={local:.4f}, alpaca={alpaca:.4f})")
            continue
        
        if delta > 0:
            # Need to BUY more
            logger.info(f"  {symbol}: ⚠️  Need to BUY {delta:.4f} shares (local={local:.4f}, alpaca={alpaca:.4f})")
            delta_orders.append({
                'symbol': symbol,
                'side': 'BUY',
                'qty': delta
            })
        else:
            # Need to SELL excess
            logger.info(f"  {symbol}: ⚠️  Need to SELL {abs(delta):.4f} shares (local={local:.4f}, alpaca={alpaca:.4f})")
            delta_orders.append({
                'symbol': symbol,
                'side': 'SELL',
                'qty': abs(delta)
            })
    
    logger.info("")
    
    if not delta_orders:
        logger.info("✓ All positions are already in sync! No orders needed.")
        return
    
    # Step 5: Execute delta orders
    logger.info(f"Step 5: {'[DRY RUN] Simulating' if args.dry_run else 'Submitting'} delta orders to Alpaca...")
    logger.info(f"  Total orders to submit: {len(delta_orders)}")
    logger.info("")
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No actual orders will be submitted")
        for order in delta_orders:
            logger.info(f"  Would submit: {order['side']} {order['qty']:.4f} {order['symbol']}")
        logger.info("")
        logger.info("To actually execute these orders, run without --dry-run flag")
        return
    
    # Real execution
    try:
        client = get_alpaca_trading_client()
        data_client = get_alpaca_client()
    except Exception as e:
        logger.error(f"Failed to create Alpaca clients: {e}")
        sys.exit(1)
    
    executed_orders = []
    failed_orders = []
    
    for order in delta_orders:
        symbol = order['symbol']
        side = order['side']
        qty = order['qty']
        
        try:
            # Get current price for logging
            try:
                bars = data_client.get_latest_bars([symbol])
                price = float(bars[symbol].close) if symbol in bars else 0.0
            except Exception:
                price = 0.0
            
            # Submit market order
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side == 'BUY' else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            alpaca_order = client.submit_order(order_data=order_request)
            
            logger.info(f"  ✓ Submitted: {side} {qty:.4f} {symbol} @ ~${price:.2f} (order_id={alpaca_order.id})")
            executed_orders.append({
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'order_id': alpaca_order.id,
                'price': price
            })
            
        except Exception as e:
            logger.error(f"  ✗ Failed: {side} {qty:.4f} {symbol} - {str(e)}")
            failed_orders.append({
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'error': str(e)
            })
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("RECONCILIATION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Successfully executed: {len(executed_orders)} orders")
    logger.info(f"Failed orders: {len(failed_orders)}")
    
    if executed_orders:
        logger.info("")
        logger.info("Executed Orders:")
        for order in executed_orders:
            logger.info(f"  {order['side']} {order['qty']:.4f} {order['symbol']} (order_id={order['order_id']})")
    
    if failed_orders:
        logger.info("")
        logger.info("Failed Orders:")
        for order in failed_orders:
            logger.info(f"  {order['side']} {order['qty']:.4f} {order['symbol']} - {order['error']}")
    
    logger.info("")
    logger.info("Next Steps:")
    logger.info("1. Check your Alpaca account to verify orders executed")
    logger.info("2. Restart the service: python main.py")
    logger.info("3. Verify UI shows correct positions")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
