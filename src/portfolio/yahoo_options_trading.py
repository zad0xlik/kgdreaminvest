"""Options trading execution for paper portfolio."""
import logging
import sqlite3
from typing import Dict, List, Optional, Tuple

from src.config import Config
from src.database.operations import get_cash, set_cash, log_event
from src.utils import utc_now, fmt_money

logger = logging.getLogger("kginvest")


def get_options_positions(conn: sqlite3.Connection) -> List[Dict]:
    """
    Get current options positions with latest pricing.
    
    Args:
        conn: SQLite connection
        
    Returns:
        List of position dicts with option details
    """
    rows = conn.execute("""
        SELECT op.position_id, op.option_id, op.qty, op.avg_cost, op.last_price, op.updated_at,
               om.underlying, om.option_type, om.strike, om.expiration, om.contract_symbol,
               om.delta, om.gamma, om.theta, om.vega, om.implied_volatility
        FROM options_positions op
        JOIN options_monitored om ON op.option_id = om.option_id
        WHERE op.qty > 0
        ORDER BY om.underlying, om.option_type, om.strike
    """).fetchall()
    
    positions = []
    for r in rows:
        positions.append({
            "position_id": r["position_id"],
            "option_id": r["option_id"],
            "qty": float(r["qty"]),
            "avg_cost": float(r["avg_cost"]),
            "last_price": float(r["last_price"]),
            "updated_at": r["updated_at"],
            "underlying": r["underlying"],
            "option_type": r["option_type"],
            "strike": float(r["strike"]),
            "expiration": r["expiration"],
            "contract": r["contract_symbol"],
            "delta": float(r["delta"] or 0),
            "gamma": float(r["gamma"] or 0),
            "theta": float(r["theta"] or 0),
            "vega": float(r["vega"] or 0),
            "iv": float(r["implied_volatility"] or 0),
        })
    
    return positions


def update_options_positions_mtm(conn: sqlite3.Connection):
    """
    Mark-to-market options positions with latest snapshot pricing.
    
    Updates last_price in options_positions table with most recent
    snapshot data from options_snapshots.
    
    Args:
        conn: SQLite connection
    """
    # Get latest snapshot for each option
    conn.execute("""
        UPDATE options_positions
        SET last_price = (
            SELECT last
            FROM options_snapshots
            WHERE options_snapshots.option_id = options_positions.option_id
            ORDER BY ts DESC
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM options_snapshots
            WHERE options_snapshots.option_id = options_positions.option_id
        )
    """)


def calculate_options_allocation(conn: sqlite3.Connection, equity_value: float) -> float:
    """
    Calculate current options allocation as percentage of total portfolio.
    
    Args:
        conn: SQLite connection
        equity_value: Total portfolio equity (cash + equities + options)
        
    Returns:
        Options allocation percentage (0-100)
    """
    positions = get_options_positions(conn)
    options_value = sum(p["qty"] * p["last_price"] * 100 for p in positions)  # *100 for contract multiplier
    
    if equity_value <= 0:
        return 0.0
    
    return (options_value / equity_value) * 100


def execute_option_buy(
    conn: sqlite3.Connection,
    option_id: int,
    contracts: float,
    price: float,
    reason: str = "",
    insight_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Execute option BUY order for paper trading.
    
    Checks guard rails:
    - Max 10% total options allocation
    - Max 3% in any single option
    - Sufficient cash
    
    Args:
        conn: SQLite connection
        option_id: Option ID from options_monitored
        contracts: Number of contracts to buy
        price: Option price per share (multiply by 100 for notional)
        reason: Trade reason/explanation
        insight_id: Optional insight ID that triggered trade
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Get option details
    opt = conn.execute(
        "SELECT * FROM options_monitored WHERE option_id=?", (option_id,)
    ).fetchone()
    
    if not opt:
        return False, f"Option {option_id} not found"
    
    if not opt["enabled"]:
        return False, f"Option {opt['underlying']} {opt['strike']}{opt['option_type'][0]} disabled"
    
    # Calculate notional (options are $100 multiplier)
    notional = contracts * price * 100
    
    # Check cash
    cash = get_cash(conn)
    if notional > cash:
        return False, f"Insufficient cash: need {fmt_money(notional)}, have {fmt_money(cash)}"
    
    # Check minimum trade size
    if notional < Config.OPTIONS_MIN_TRADE_NOTIONAL:
        return False, f"Trade too small: {fmt_money(notional)} < {fmt_money(Config.OPTIONS_MIN_TRADE_NOTIONAL)}"
    
    # Calculate current portfolio value
    from src.database.operations import portfolio_state
    pf = portfolio_state(conn, prices={})
    total_equity = pf["equity"]
    
    # Check total options allocation
    current_options_alloc = calculate_options_allocation(conn, total_equity)
    new_options_alloc = ((notional) / total_equity) * 100
    
    if (current_options_alloc + new_options_alloc) > Config.OPTIONS_MAX_ALLOCATION_PCT:
        return False, f"Exceeds max options allocation: {current_options_alloc + new_options_alloc:.1f}% > {Config.OPTIONS_MAX_ALLOCATION_PCT}%"
    
    # Check single option allocation
    if new_options_alloc > Config.OPTIONS_MAX_SINGLE_OPTION_PCT:
        return False, f"Single option too large: {new_options_alloc:.1f}% > {Config.OPTIONS_MAX_SINGLE_OPTION_PCT}%"
    
    # Execute trade
    ts = utc_now()
    
    # Record trade
    conn.execute(
        "INSERT INTO options_trades(ts, option_id, side, qty, price, notional, reason, insight_id) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (ts, option_id, "BUY", contracts, price, notional, reason, insight_id)
    )
    
    # Update or create position
    existing = conn.execute(
        "SELECT * FROM options_positions WHERE option_id=?", (option_id,)
    ).fetchone()
    
    if existing:
        # Average up
        old_qty = float(existing["qty"])
        old_cost = float(existing["avg_cost"])
        new_qty = old_qty + contracts
        new_avg = ((old_qty * old_cost) + (contracts * price)) / new_qty
        
        conn.execute(
            "UPDATE options_positions SET qty=?, avg_cost=?, last_price=?, updated_at=? "
            "WHERE option_id=?",
            (new_qty, new_avg, price, ts, option_id)
        )
    else:
        # New position
        conn.execute(
            "INSERT INTO options_positions(option_id, qty, avg_cost, last_price, updated_at) "
            "VALUES(?,?,?,?,?)",
            (option_id, contracts, price, price, ts)
        )
    
    # Deduct cash
    set_cash(conn, cash - notional)
    
    # Log event
    symbol = f"{opt['underlying']} {opt['strike']}{opt['option_type'][0]} {opt['expiration']}"
    log_event(
        conn,
        "options_trading",
        "buy",
        f"BUY {contracts} {symbol} @ ${price:.2f} = {fmt_money(notional)} | {reason}"
    )
    
    logger.info(f"✅ Option BUY: {contracts}x {symbol} @ ${price:.2f} = {fmt_money(notional)}")
    
    return True, f"Bought {contracts} contracts of {symbol}"


def execute_option_sell(
    conn: sqlite3.Connection,
    option_id: int,
    contracts: float,
    price: float,
    reason: str = "",
    insight_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Execute option SELL order for paper trading.
    
    Args:
        conn: SQLite connection
        option_id: Option ID from options_monitored
        contracts: Number of contracts to sell
        price: Option price per share (multiply by 100 for notional)
        reason: Trade reason/explanation
        insight_id: Optional insight ID that triggered trade
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Get position
    pos = conn.execute(
        "SELECT * FROM options_positions WHERE option_id=?", (option_id,)
    ).fetchone()
    
    if not pos:
        return False, f"No position for option {option_id}"
    
    current_qty = float(pos["qty"])
    if contracts > current_qty:
        return False, f"Cannot sell {contracts} contracts, only have {current_qty}"
    
    # Get option details
    opt = conn.execute(
        "SELECT * FROM options_monitored WHERE option_id=?", (option_id,)
    ).fetchone()
    
    # Calculate proceeds
    notional = contracts * price * 100
    ts = utc_now()
    
    # Record trade
    conn.execute(
        "INSERT INTO options_trades(ts, option_id, side, qty, price, notional, reason, insight_id) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (ts, option_id, "SELL", contracts, price, notional, reason, insight_id)
    )
    
    # Update position
    new_qty = current_qty - contracts
    if new_qty < 0.001:  # Close position
        conn.execute("DELETE FROM options_positions WHERE option_id=?", (option_id,))
    else:
        conn.execute(
            "UPDATE options_positions SET qty=?, last_price=?, updated_at=? WHERE option_id=?",
            (new_qty, price, ts, option_id)
        )
    
    # Add cash
    cash = get_cash(conn)
    set_cash(conn, cash + notional)
    
    # Log event
    symbol = f"{opt['underlying']} {opt['strike']}{opt['option_type'][0]} {opt['expiration']}"
    log_event(
        conn,
        "options_trading",
        "sell",
        f"SELL {contracts} {symbol} @ ${price:.2f} = {fmt_money(notional)} | {reason}"
    )
    
    logger.info(f"✅ Option SELL: {contracts}x {symbol} @ ${price:.2f} = {fmt_money(notional)}")
    
    return True, f"Sold {contracts} contracts of {symbol}"
