"""Alpaca options trading execution with guard rails."""
import logging
import sqlite3
from typing import Dict, Any, List, Optional, Tuple

from src.config import Config
from src.database.operations import get_cash, set_cash, log_event
from src.utils import utc_now, fmt_money

logger = logging.getLogger("kginvest")


def get_alpaca_options_trading_client():
    """
    Create and return Alpaca trading client for options trading.
    
    Note: Options use the same TradingClient as stocks.
    The account must have options trading enabled.
    
    Returns:
        TradingClient instance configured for paper or live trading
        
    Raises:
        ImportError: If alpaca-py not installed
        ValueError: If API keys not configured
    """
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        raise ImportError(
            "alpaca-py not installed. Run: pip install alpaca-py"
        )
    
    if not Config.ALPACA_API_KEY or not Config.ALPACA_SECRET_KEY:
        raise ValueError(
            "Alpaca API keys not configured. Set ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY in .env file"
        )
    
    return TradingClient(
        api_key=Config.ALPACA_API_KEY,
        secret_key=Config.ALPACA_SECRET_KEY,
        paper=Config.ALPACA_PAPER_MODE
    )


def sync_alpaca_options_account(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Sync options-specific account info from Alpaca.
    
    Retrieves options buying power and approval levels from Alpaca account.
    
    Args:
        conn: Database connection
        
    Returns:
        Dict with options-specific account info:
            - options_buying_power: Available buying power for options
            - options_approved_level: Approval level for options trading
            - options_trading_level: Current trading level
            - account_blocked: Whether options trading is blocked
            
    Example:
        >>> with db_conn() as conn:
        ...     info = sync_alpaca_options_account(conn)
        ...     print(f"Options buying power: ${info['options_buying_power']:.2f}")
    """
    try:
        client = get_alpaca_options_trading_client()
        account = client.get_account()
        
        options_info = {
            "options_buying_power": float(account.options_buying_power) if hasattr(account, 'options_buying_power') else 0.0,
            "options_approved_level": int(account.options_approved_level) if hasattr(account, 'options_approved_level') else 0,
            "options_trading_level": int(account.options_trading_level) if hasattr(account, 'options_trading_level') else 0,
            "account_blocked": account.account_blocked if hasattr(account, 'account_blocked') else False,
        }
        
        logger.info(f"Synced Alpaca options account: "
                   f"buying_power=${options_info['options_buying_power']:.2f}, "
                   f"level={options_info['options_trading_level']}")
        
        return options_info
        
    except Exception as e:
        logger.error(f"Failed to sync Alpaca options account: {e}")
        return {
            "options_buying_power": 0.0,
            "options_approved_level": 0,
            "options_trading_level": 0,
            "account_blocked": True,
        }


def sync_alpaca_options_positions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Sync open options positions from Alpaca to local database.
    
    Updates the options_positions table with current Alpaca options holdings.
    Alpaca is the source of truth - local positions are updated to match.
    
    Args:
        conn: Database connection
        
    Returns:
        List of position dicts synced from Alpaca
        
    Example:
        >>> with db_conn() as conn:
        ...     positions = sync_alpaca_options_positions(conn)
        ...     for pos in positions:
        ...         print(f"{pos['contract_symbol']}: {pos['qty']} contracts")
    """
    try:
        client = get_alpaca_options_trading_client()
        alpaca_positions = client.get_all_positions()
        
        # Filter for options positions only (options have specific symbol format)
        options_positions = [p for p in alpaca_positions if len(p.symbol) > 10 and p.asset_class == "us_option"]
        
        synced = []
        now = utc_now()
        
        for pos in options_positions:
            contract_symbol = pos.symbol
            qty = float(pos.qty)
            avg_cost = float(pos.avg_entry_price)
            last_price = float(pos.current_price)
            
            # Find corresponding option_id in our options_monitored table
            opt = conn.execute(
                "SELECT option_id FROM options_monitored WHERE contract_symbol=?",
                (contract_symbol,)
            ).fetchone()
            
            if not opt:
                logger.warning(f"Alpaca position {contract_symbol} not in options_monitored table, skipping")
                continue
            
            option_id = opt["option_id"]
            
            # Check if we already have this position locally
            existing = conn.execute(
                "SELECT * FROM options_positions WHERE option_id=?",
                (option_id,)
            ).fetchone()
            
            if existing:
                # Update existing position
                conn.execute(
                    "UPDATE options_positions SET qty=?, avg_cost=?, last_price=?, updated_at=? "
                    "WHERE option_id=?",
                    (qty, avg_cost, last_price, now, option_id)
                )
            else:
                # Create new position
                conn.execute(
                    "INSERT INTO options_positions(option_id, qty, avg_cost, last_price, updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (option_id, qty, avg_cost, last_price, now)
                )
            
            synced.append({
                "contract_symbol": contract_symbol,
                "option_id": option_id,
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": last_price,
                "market_value": float(pos.market_value),
                "unrealized_pl": float(pos.unrealized_pl),
            })
        
        # Remove local positions that no longer exist in Alpaca
        local_option_ids = {row["option_id"] for row in conn.execute(
            """SELECT op.option_id FROM options_positions op
               JOIN options_monitored om ON op.option_id = om.option_id"""
        ).fetchall()}
        
        alpaca_option_ids = {p["option_id"] for p in synced}
        removed = local_option_ids - alpaca_option_ids
        
        for option_id in removed:
            conn.execute("DELETE FROM options_positions WHERE option_id=?", (option_id,))
            logger.info(f"Removed closed options position: option_id={option_id}")
        
        conn.commit()
        logger.info(f"Synced {len(synced)} Alpaca options positions")
        
        return synced
        
    except Exception as e:
        logger.error(f"Failed to sync Alpaca options positions: {e}")
        return []


def execute_option_buy_alpaca(
    conn: sqlite3.Connection,
    option_id: int,
    contracts: float,
    price: float,
    reason: str = "",
    insight_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Execute option BUY order via Alpaca with strict guard rails.
    
    Applies same guard rails as Yahoo paper trading, then submits real order to Alpaca.
    
    Guard rails enforced:
    - Max 10% total options allocation
    - Max 3% in any single option
    - Minimum trade notional ($25)
    - Sufficient options buying power
    
    Args:
        conn: SQLite connection
        option_id: Option ID from options_monitored table
        contracts: Number of contracts to buy
        price: Option price per share (multiply by 100 for notional)
        reason: Trade reason/explanation
        insight_id: Optional insight ID that triggered trade
        
    Returns:
        Tuple of (success: bool, message: str)
        
    Example:
        >>> success, msg = execute_option_buy_alpaca(conn, 123, 1, 2.50, "bullish signal")
        >>> if success:
        ...     print(f"Order submitted: {msg}")
    """
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        client = get_alpaca_options_trading_client()
    except ImportError as e:
        return False, f"Alpaca not available: {e}"
    except ValueError as e:
        return False, f"Alpaca config error: {e}"
    
    # Get option details
    opt = conn.execute(
        "SELECT * FROM options_monitored WHERE option_id=?", (option_id,)
    ).fetchone()
    
    if not opt:
        return False, f"Option {option_id} not found"
    
    if not opt["enabled"]:
        return False, f"Option {opt['underlying']} {opt['strike']}{opt['option_type'][0]} disabled"
    
    contract_symbol = opt["contract_symbol"]
    if not contract_symbol:
        return False, f"No contract symbol for option {option_id}"
    
    # Calculate notional (options are $100 multiplier)
    notional = contracts * price * 100
    
    # Check minimum trade size
    if notional < Config.OPTIONS_MIN_TRADE_NOTIONAL:
        return False, f"Trade too small: {fmt_money(notional)} < {fmt_money(Config.OPTIONS_MIN_TRADE_NOTIONAL)}"
    
    # Sync account to get latest buying power
    options_account = sync_alpaca_options_account(conn)
    options_buying_power = options_account["options_buying_power"]
    
    if notional > options_buying_power:
        return False, f"Insufficient options buying power: need {fmt_money(notional)}, have {fmt_money(options_buying_power)}"
    
    # Calculate current portfolio value for allocation checks
    from src.database.operations import portfolio_state
    pf = portfolio_state(conn, prices={})
    total_equity = pf["equity"]
    
    # Check total options allocation
    from src.portfolio.yahoo_options_trading import calculate_options_allocation
    current_options_alloc = calculate_options_allocation(conn, total_equity)
    new_options_alloc = (notional / total_equity) * 100
    
    if (current_options_alloc + new_options_alloc) > Config.OPTIONS_MAX_ALLOCATION_PCT:
        return False, f"Exceeds max options allocation: {current_options_alloc + new_options_alloc:.1f}% > {Config.OPTIONS_MAX_ALLOCATION_PCT}%"
    
    # Check single option allocation
    if new_options_alloc > Config.OPTIONS_MAX_SINGLE_OPTION_PCT:
        return False, f"Single option too large: {new_options_alloc:.1f}% > {Config.OPTIONS_MAX_SINGLE_OPTION_PCT}%"
    
    # Submit market buy order to Alpaca
    try:
        order_request = MarketOrderRequest(
            symbol=contract_symbol,
            qty=contracts,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        order = client.submit_order(order_data=order_request)
        logger.info(f"Alpaca options BUY order submitted: {contract_symbol} {contracts} contracts (order_id={order.id})")
        
        # Record trade
        ts = utc_now()
        conn.execute(
            "INSERT INTO options_trades(ts, option_id, side, qty, price, notional, reason, insight_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (ts, option_id, "BUY", contracts, price, notional, f"Alpaca: {reason[:390]}", insight_id)
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
        
        # Deduct cash (options purchases deduct from cash)
        cash = get_cash(conn)
        set_cash(conn, cash - notional)
        
        # Log event
        symbol = f"{opt['underlying']} {opt['strike']}{opt['option_type'][0]} {opt['expiration']}"
        log_event(
            conn,
            "alpaca_options_trading",
            "buy",
            f"Alpaca BUY {contracts} {symbol} @ ${price:.2f} = {fmt_money(notional)} | order_id={order.id} | {reason}"
        )
        
        conn.commit()
        
        logger.info(f"✅ Alpaca Option BUY: {contracts}x {symbol} @ ${price:.2f} = {fmt_money(notional)} (order_id={order.id})")
        
        return True, f"Alpaca order submitted: {symbol} (order_id={order.id})"
        
    except Exception as e:
        logger.error(f"Alpaca options BUY order failed for {contract_symbol}: {e}")
        return False, f"Alpaca order failed: {str(e)[:100]}"


def execute_option_sell_alpaca(
    conn: sqlite3.Connection,
    option_id: int,
    contracts: float,
    price: float,
    reason: str = "",
    insight_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Execute option SELL order via Alpaca.
    
    Args:
        conn: SQLite connection
        option_id: Option ID from options_monitored table
        contracts: Number of contracts to sell
        price: Option price per share (multiply by 100 for notional)
        reason: Trade reason/explanation
        insight_id: Optional insight ID that triggered trade
        
    Returns:
        Tuple of (success: bool, message: str)
        
    Example:
        >>> success, msg = execute_option_sell_alpaca(conn, 123, 1, 3.00, "take profit")
        >>> if success:
        ...     print(f"Position closed: {msg}")
    """
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        client = get_alpaca_options_trading_client()
    except ImportError as e:
        return False, f"Alpaca not available: {e}"
    except ValueError as e:
        return False, f"Alpaca config error: {e}"
    
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
    
    contract_symbol = opt["contract_symbol"]
    if not contract_symbol:
        return False, f"No contract symbol for option {option_id}"
    
    # Calculate proceeds
    notional = contracts * price * 100
    
    # Submit market sell order to Alpaca
    try:
        order_request = MarketOrderRequest(
            symbol=contract_symbol,
            qty=contracts,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        
        order = client.submit_order(order_data=order_request)
        logger.info(f"Alpaca options SELL order submitted: {contract_symbol} {contracts} contracts (order_id={order.id})")
        
        # Record trade
        ts = utc_now()
        conn.execute(
            "INSERT INTO options_trades(ts, option_id, side, qty, price, notional, reason, insight_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (ts, option_id, "SELL", contracts, price, notional, f"Alpaca: {reason[:390]}", insight_id)
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
        
        # Add cash (options sales add to cash)
        cash = get_cash(conn)
        set_cash(conn, cash + notional)
        
        # Log event
        symbol = f"{opt['underlying']} {opt['strike']}{opt['option_type'][0]} {opt['expiration']}"
        log_event(
            conn,
            "alpaca_options_trading",
            "sell",
            f"Alpaca SELL {contracts} {symbol} @ ${price:.2f} = {fmt_money(notional)} | order_id={order.id} | {reason}"
        )
        
        conn.commit()
        
        logger.info(f"✅ Alpaca Option SELL: {contracts}x {symbol} @ ${price:.2f} = {fmt_money(notional)} (order_id={order.id})")
        
        return True, f"Alpaca order submitted: {symbol} (order_id={order.id})"
        
    except Exception as e:
        logger.error(f"Alpaca options SELL order failed for {contract_symbol}: {e}")
        return False, f"Alpaca order failed: {str(e)[:100]}"


def close_all_alpaca_options_positions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Close all open options positions via Alpaca.
    
    Useful for emergency exits or end-of-day cleanup.
    Submits SELL orders for all current positions.
    
    Args:
        conn: Database connection
        
    Returns:
        List of closed position results
        
    Example:
        >>> with db_conn() as conn:
        ...     results = close_all_alpaca_options_positions(conn)
        ...     print(f"Closed {len(results)} positions")
    """
    try:
        client = get_alpaca_options_trading_client()
    except Exception as e:
        logger.error(f"Cannot close positions: {e}")
        return []
    
    # Get all current positions
    from src.portfolio.yahoo_options_trading import get_options_positions
    positions = get_options_positions(conn)
    
    results = []
    for pos in positions:
        try:
            # Use Alpaca's close position endpoint
            contract_symbol = pos["contract"]
            
            response = client.close_position(
                symbol_or_asset_id=contract_symbol
            )
            
            logger.info(f"Closed Alpaca options position: {contract_symbol}")
            
            results.append({
                "contract_symbol": contract_symbol,
                "option_id": pos["option_id"],
                "qty_closed": pos["qty"],
                "success": True,
                "order_id": response.order_id if hasattr(response, 'order_id') else None
            })
            
            # Remove from local database
            conn.execute("DELETE FROM options_positions WHERE option_id=?", (pos["option_id"],))
            
        except Exception as e:
            logger.error(f"Failed to close position {pos['contract']}: {e}")
            results.append({
                "contract_symbol": pos.get("contract"),
                "option_id": pos["option_id"],
                "qty_closed": 0,
                "success": False,
                "error": str(e)[:100]
            })
    
    conn.commit()
    return results
