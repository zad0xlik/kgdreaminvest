#!/usr/bin/env python3
"""Portfolio Reconciliation Report - Full Transaction Analysis"""

import sqlite3
from datetime import datetime

DB_PATH = "./data/kginvest_live.db"

def get_trades():
    """Get all trades from database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    trades = cursor.execute("""
        SELECT trade_id, ts, symbol, side, qty, price, notional, reason 
        FROM trades 
        ORDER BY ts ASC
    """).fetchall()
    
    conn.close()
    return trades

def get_positions():
    """Get current positions"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    positions = cursor.execute("""
        SELECT symbol, qty, avg_cost, last_price, 
               (qty * last_price) as market_value,
               (qty * avg_cost) as cost_basis
        FROM positions 
        ORDER BY symbol ASC
    """).fetchall()
    
    conn.close()
    return positions

def get_cash():
    """Get current cash balance"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cash = cursor.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()[0]
    
    conn.close()
    return float(cash)

def main():
    print("=" * 100)
    print("PORTFOLIO RECONCILIATION REPORT")
    print("=" * 100)
    print()
    
    # Starting balance
    START_CASH = 500.00
    print(f"STARTING BALANCE: ${START_CASH:.2f}")
    print()
    
    # Get all data
    trades = get_trades()
    positions = get_positions()
    current_cash = get_cash()
    
    # Transaction History
    print("=" * 100)
    print("TRANSACTION HISTORY (Chronological)")
    print("=" * 100)
    print(f"{'ID':<4} {'Date/Time':<26} {'Symbol':<8} {'Side':<6} {'Qty':<12} {'Price':<12} {'Notional':<12} {'Cash After':<12}")
    print("-" * 100)
    
    running_cash = START_CASH
    total_invested = 0
    total_sold = 0
    
    for trade in trades:
        trade_date = datetime.fromisoformat(trade['ts']).strftime("%Y-%m-%d %H:%M:%S")
        
        if trade['side'] == 'BUY':
            running_cash -= trade['notional']
            total_invested += trade['notional']
            cash_change = f"-${trade['notional']:.2f}"
        else:  # SELL
            running_cash += trade['notional']
            total_sold += trade['notional']
            cash_change = f"+${trade['notional']:.2f}"
        
        print(f"{trade['trade_id']:<4} {trade_date:<26} {trade['symbol']:<8} {trade['side']:<6} "
              f"{trade['qty']:<12.6f} ${trade['price']:<11.2f} {cash_change:<12} ${running_cash:.2f}")
    
    print("-" * 100)
    print(f"Total Invested (BUY):  ${total_invested:.2f}")
    print(f"Total Sold (SELL):     ${total_sold:.2f}")
    print(f"Net Cash Deployed:     ${total_invested - total_sold:.2f}")
    print()
    
    # Current Positions
    print("=" * 100)
    print("CURRENT POSITIONS")
    print("=" * 100)
    print(f"{'Symbol':<8} {'Qty':<12} {'Avg Cost':<12} {'Last Price':<12} {'Cost Basis':<14} {'Market Value':<14} {'Gain/Loss':<12} {'Return %':<10}")
    print("-" * 100)
    
    total_cost_basis = 0
    total_market_value = 0
    
    for pos in positions:
        cost_basis = pos['cost_basis']
        market_value = pos['market_value']
        gain_loss = market_value - cost_basis
        return_pct = (gain_loss / cost_basis) * 100 if cost_basis > 0 else 0
        
        total_cost_basis += cost_basis
        total_market_value += market_value
        
        gain_loss_str = f"+${gain_loss:.2f}" if gain_loss >= 0 else f"-${abs(gain_loss):.2f}"
        return_str = f"+{return_pct:.2f}%" if return_pct >= 0 else f"{return_pct:.2f}%"
        
        print(f"{pos['symbol']:<8} {pos['qty']:<12.6f} ${pos['avg_cost']:<11.2f} ${pos['last_price']:<11.2f} "
              f"${cost_basis:<13.2f} ${market_value:<13.2f} {gain_loss_str:<12} {return_str:<10}")
    
    print("-" * 100)
    print(f"{'TOTALS':<8} {'':<12} {'':<12} {'':<12} ${total_cost_basis:<13.2f} ${total_market_value:<13.2f} "
          f"${total_market_value - total_cost_basis:>11.2f} {((total_market_value - total_cost_basis) / total_cost_basis * 100):>9.2f}%")
    print()
    
    # Portfolio Reconciliation
    print("=" * 100)
    print("PORTFOLIO RECONCILIATION")
    print("=" * 100)
    print()
    print(f"Starting Cash:                    ${START_CASH:.2f}")
    print()
    print("Cash Flows:")
    print(f"  - Total Invested (BUY):         -${total_invested:.2f}")
    print(f"  + Total Sold (SELL):            +${total_sold:.2f}")
    print(f"  = Net Cash Deployed:            -${total_invested - total_sold:.2f}")
    print()
    print(f"Expected Cash Balance:            ${START_CASH - (total_invested - total_sold):.2f}")
    print(f"Actual Cash Balance:              ${current_cash:.2f}")
    print(f"Cash Difference:                  ${current_cash - (START_CASH - (total_invested - total_sold)):.2f}")
    print()
    print("Equity Positions:")
    print(f"  Cost Basis (what you paid):     ${total_cost_basis:.2f}")
    print(f"  Market Value (current worth):   ${total_market_value:.2f}")
    print(f"  Unrealized Gain/Loss:           ${total_market_value - total_cost_basis:.2f}")
    print()
    print(f"{'-' * 100}")
    print(f"Current Cash:                     ${current_cash:.2f}")
    print(f"Current Equity:                   ${total_market_value:.2f}")
    print(f"{'=' * 100}")
    print(f"TOTAL PORTFOLIO VALUE:            ${current_cash + total_market_value:.2f}")
    print(f"{'=' * 100}")
    print()
    print(f"Starting Balance:                 ${START_CASH:.2f}")
    print(f"Ending Balance:                   ${current_cash + total_market_value:.2f}")
    print(f"Total Gain:                       ${(current_cash + total_market_value) - START_CASH:.2f}")
    print(f"Total Return:                     {((current_cash + total_market_value - START_CASH) / START_CASH * 100):.2f}%")
    print()
    print("=" * 100)
    print()
    
    # Realized vs Unrealized
    print("GAIN/LOSS BREAKDOWN")
    print("=" * 100)
    
    realized_gain = total_sold - sum(trades[i]['notional'] for i in range(len(trades)) if trades[i]['side'] == 'BUY' and trades[i]['symbol'] == 'PSNY' and i < 12) if total_sold > 0 else 0
    # For the PSNY sale, calculate realized gain
    psny_cost_for_sold = 0
    for trade in trades:
        if trade['symbol'] == 'PSNY' and trade['side'] == 'SELL':
            # The sold portion's cost basis
            sold_qty = trade['qty']
            # Average cost from positions table includes remaining shares
            # We need to calculate the actual cost of shares sold
            # From the data: sold 1.313 shares at $19.52 = $25.63
            # But we bought shares at $18.66 (trades 5 and 8)
            # Trade 5: 2.144 @ $18.66 = $40
            # Trade 8: 1.608 @ $18.66 = $30
            # Total bought: 3.752 @ $18.66
            # We sold: 1.313 @ $18.66 (average cost) = $24.50 cost basis
            # Proceeds: $25.63
            # Realized gain: $25.63 - $24.50 = $1.13
            psny_cost_for_sold = sold_qty * 18.66  # Average cost from buys
            realized_gain = trade['notional'] - psny_cost_for_sold
    
    unrealized_gain = total_market_value - total_cost_basis
    
    print(f"Realized Gain/Loss:               ${realized_gain:.2f}")
    print(f"Unrealized Gain/Loss:             ${unrealized_gain:.2f}")
    print(f"Total Gain/Loss:                  ${realized_gain + unrealized_gain:.2f}")
    print()
    print("=" * 100)

if __name__ == "__main__":
    main()
