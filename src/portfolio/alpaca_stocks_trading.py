"""Alpaca live/paper trading execution with guard rails."""
import logging
import sqlite3
from typing import Dict, Any, List, Optional

from src.config import Config
from src.database.operations import get_cash, set_cash
from src.utils import utc_now

logger = logging.getLogger("kginvest")


def get_alpaca_trading_client():
    """
    Create and return Alpaca trading client.
    
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


def sync_alpaca_account(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Sync cash balance and account info from Alpaca to local database.
    
    On first sync, stores the starting balance for accurate portfolio tracking.
    
    Args:
        conn: Database connection
        
    Returns:
        Dict with account info: buying_power, portfolio_value, status, etc.
        
    Example:
        >>> with db_conn() as conn:
        ...     account = sync_alpaca_account(conn)
        ...     print(f"Buying power: ${account['buying_power']:.2f}")
    """
    try:
        client = get_alpaca_trading_client()
        account = client.get_account()
        
        # Update cash in local database
        cash = float(account.cash)
        set_cash(conn, cash)
        
        # On first sync, store the starting balance for accurate reconciliation
        # Check if we've stored this before
        from src.database.operations import kv_get, kv_set
        
        if not kv_get(conn, "alpaca_start_balance"):
            # First time syncing - store the equity as starting balance
            # Use equity (cash + positions) rather than just cash
            starting_balance = float(account.equity)
            kv_set(conn, "alpaca_start_balance", str(starting_balance))
            logger.info(f"Stored Alpaca starting balance: ${starting_balance:.2f}")
        
        logger.info(f"Synced Alpaca account: ${cash:.2f} cash, "
                   f"${account.portfolio_value} total")
        
        return {
            "cash": cash,
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "equity": float(account.equity),
            "status": account.status,
            "pattern_day_trader": account.pattern_day_trader,
        }
        
    except Exception as e:
        logger.error(f"Failed to sync Alpaca account: {e}")
        return {}


def sync_alpaca_positions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Sync open positions from Alpaca to local database.
    
    Updates the positions table with current Alpaca holdings.
    
    Args:
        conn: Database connection
        
    Returns:
        List of position dicts synced from Alpaca
        
    Example:
        >>> with db_conn() as conn:
        ...     positions = sync_alpaca_positions(conn)
        ...     for pos in positions:
        ...         print(f"{pos['symbol']}: {pos['qty']} shares")
    """
    try:
        client = get_alpaca_trading_client()
        alpaca_positions = client.get_all_positions()
        
        synced = []
        now = utc_now()
        
        for pos in alpaca_positions:
            symbol = pos.symbol
            qty = float(pos.qty)
            avg_cost = float(pos.avg_entry_price)
            last_price = float(pos.current_price)
            
            # Check if we already have this position locally
            existing = conn.execute(
                "SELECT executed_at FROM positions WHERE symbol=?",
                (symbol,)
            ).fetchone()
            
            # Preserve original executed_at if exists, otherwise use now
            executed_at = existing["executed_at"] if existing else now
            
            # Upsert position
            conn.execute(
                "INSERT OR REPLACE INTO positions"
                "(symbol, qty, avg_cost, last_price, updated_at, executed_at) "
                "VALUES(?,?,?,?,?,?)",
                (symbol, qty, avg_cost, last_price, now, executed_at)
            )
            
            synced.append({
                "symbol": symbol,
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": last_price,
                "market_value": float(pos.market_value),
                "unrealized_pl": float(pos.unrealized_pl),
            })
        
        # Remove positions that no longer exist in Alpaca
        local_symbols = {row["symbol"] for row in conn.execute(
            "SELECT symbol FROM positions"
        ).fetchall()}
        
        alpaca_symbols = {pos.symbol for pos in alpaca_positions}
        removed = local_symbols - alpaca_symbols
        
        for symbol in removed:
            conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            logger.info(f"Removed closed position: {symbol}")
        
        conn.commit()
        logger.info(f"Synced {len(synced)} Alpaca positions")
        
        return synced
        
    except Exception as e:
        logger.error(f"Failed to sync Alpaca positions: {e}")
        return []


def execute_alpaca_trades(
    conn: sqlite3.Connection,
    decisions: List[Dict[str, Any]],
    prices: Dict[str, Any],
    reason: str,
    insight_id: int
) -> Dict[str, Any]:
    """
    Execute trades via Alpaca API with strict guard rails.
    
    Applies same guard rails as paper trading, then submits real orders to Alpaca.
    Executes SELLs first (to free cash), then BUYs.
    
    Args:
        conn: Database connection
        decisions: List of trade decisions with ticker, action, allocation_pct
        prices: Dict mapping ticker to price data with 'current' price
        reason: Reason string for trade log
        insight_id: Associated insight ID
        
    Returns:
        Dict with keys: executed (list of trades), skipped (list of reasons), cash (final balance)
        
    Example:
        >>> decisions = [
        ...     {"ticker": "AAPL", "action": "BUY", "allocation_pct": 5.0},
        ...     {"ticker": "MSFT", "action": "SELL", "allocation_pct": 10.0}
        ... ]
        >>> result = execute_alpaca_trades(conn, decisions, prices, "test", 1)
        >>> print(f"Executed {len(result['executed'])} Alpaca trades")
    """
    from src.database.operations import portfolio_state
    
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        client = get_alpaca_trading_client()
    except ImportError as e:
        logger.error(f"Alpaca import failed: {e}")
        return {"executed": [], "skipped": ["Alpaca not available"], "cash": get_cash(conn)}
    except ValueError as e:
        logger.error(f"Alpaca configuration error: {e}")
        return {"executed": [], "skipped": [str(e)], "cash": get_cash(conn)}
    
    # Sync account first to get current cash
    sync_alpaca_account(conn)
    sync_alpaca_positions(conn)
    
    cash = get_cash(conn)
    pf = portfolio_state(conn, prices=prices)
    equity = float(pf["equity"])
    
    # Current per-symbol market value and quantities
    mv_by_sym: Dict[str, float] = {p["symbol"]: float(p["mv"]) for p in pf["positions"]}
    qty_by_sym: Dict[str, float] = {p["symbol"]: float(p["qty"]) for p in pf["positions"]}
    
    # Constrain totals
    buy_budget = equity * (Config.MAX_BUY_EQUITY_PCT_PER_CYCLE / 100.0)
    cash_buffer = equity * (Config.MIN_CASH_BUFFER_PCT / 100.0)
    
    executed: List[Dict[str, Any]] = []
    skipped: List[str] = []
    
    def px(sym: str) -> float:
        """Helper to get current price safely."""
        try:
            return float(prices.get(sym, {}).get("current", 0.0) or 0.0)
        except Exception:
            return 0.0
    
    # ==================== SELL PASS ====================
    for d in decisions:
        if d.get("action") != "SELL":
            continue
        
        sym = d.get("ticker")
        if sym not in prices:
            continue
        
        have = float(qty_by_sym.get(sym, 0.0))
        if have <= 0:
            continue
        
        pct = min(
            float(d.get("allocation_pct", 0.0) or 0.0),
            Config.MAX_SELL_HOLDING_PCT_PER_CYCLE
        )
        if pct <= 0:
            continue
        
        sell_sh = have * (pct / 100.0)
        p = px(sym)
        notional = sell_sh * p
        
        if notional < Config.MIN_TRADE_NOTIONAL:
            skipped.append(f"SELL {sym} notional too small")
            continue
        
        # Submit market sell order to Alpaca
        try:
            order_request = MarketOrderRequest(
                symbol=sym,
                qty=sell_sh,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            order = client.submit_order(order_data=order_request)
            logger.info(f"Alpaca SELL order submitted: {sym} {sell_sh} shares (order_id={order.id})")
            
            # Update local state
            new_have = have - sell_sh
            cash += notional
            qty_by_sym[sym] = new_have
            mv_by_sym[sym] = new_have * p
            
            # Update database
            if new_have <= 1e-8:
                conn.execute("DELETE FROM positions WHERE symbol=?", (sym,))
            else:
                conn.execute(
                    "UPDATE positions SET qty=?, last_price=?, updated_at=? WHERE symbol=?",
                    (new_have, p, utc_now(), sym)
                )
            
            # Log trade
            conn.execute(
                "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (utc_now(), sym, "SELL", float(sell_sh), float(p), float(notional), 
                 f"Alpaca: {reason[:390]}", int(insight_id))
            )
            
            executed.append({
                "ticker": sym,
                "side": "SELL",
                "shares": sell_sh,
                "price": p,
                "notional": notional,
                "order_id": order.id
            })
            
        except Exception as e:
            logger.error(f"Alpaca SELL order failed for {sym}: {e}")
            skipped.append(f"SELL {sym} order failed: {str(e)[:50]}")
    
    # ==================== BUY PASS ====================
    for d in decisions:
        if d.get("action") != "BUY":
            continue
        
        sym = d.get("ticker")
        if sym not in prices:
            continue
        
        pct = float(d.get("allocation_pct", 0.0) or 0.0)
        if pct <= 0:
            continue
        
        p = px(sym)
        if p <= 0:
            continue
        
        # Enforce cash buffer
        spendable = max(0.0, cash - cash_buffer)
        if spendable < Config.MIN_TRADE_NOTIONAL:
            skipped.append("BUY: cash buffer prevents spending")
            break
        
        # Requested notional is pct of equity, bounded by buy_budget and spendable
        requested = equity * (pct / 100.0)
        notional = min(requested, buy_budget, spendable)
        
        if notional < Config.MIN_TRADE_NOTIONAL:
            skipped.append(f"BUY {sym} notional too small")
            continue
        
        # Enforce per-symbol weight cap
        current_mv = float(mv_by_sym.get(sym, 0.0))
        cap = equity * (Config.MAX_SYMBOL_WEIGHT_PCT / 100.0)
        
        if current_mv >= cap:
            skipped.append(f"BUY {sym} cap reached")
            continue
        
        notional = min(notional, max(0.0, cap - current_mv))
        if notional < Config.MIN_TRADE_NOTIONAL:
            skipped.append(f"BUY {sym} cap residual too small")
            continue
        
        shares = notional / p
        
        # Submit market buy order to Alpaca
        try:
            order_request = MarketOrderRequest(
                symbol=sym,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            
            order = client.submit_order(order_data=order_request)
            logger.info(f"Alpaca BUY order submitted: {sym} {shares} shares (order_id={order.id})")
            
            # Update local state
            cash -= notional
            buy_budget -= notional
            
            # Update position
            have = float(qty_by_sym.get(sym, 0.0))
            row = conn.execute("SELECT * FROM positions WHERE symbol=?", (sym,)).fetchone()
            avg = float(row["avg_cost"]) if row else p
            new_qty = have + shares
            new_avg = (avg * have + p * shares) / max(1e-9, new_qty)
            
            qty_by_sym[sym] = new_qty
            mv_by_sym[sym] = new_qty * p
            
            # Preserve executed_at for existing position, set it for new position
            now = utc_now()
            executed_at = row["executed_at"] if (row and row["executed_at"]) else now
            
            conn.execute(
                "INSERT OR REPLACE INTO positions(symbol,qty,avg_cost,last_price,updated_at,executed_at) "
                "VALUES(?,?,?,?,?,?)",
                (sym, float(new_qty), float(new_avg), float(p), now, executed_at)
            )
            
            # Log trade
            conn.execute(
                "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (utc_now(), sym, "BUY", float(shares), float(p), float(notional), 
                 f"Alpaca: {reason[:390]}", int(insight_id))
            )
            
            executed.append({
                "ticker": sym,
                "side": "BUY",
                "shares": shares,
                "price": p,
                "notional": notional,
                "order_id": order.id
            })
            
            if buy_budget < Config.MIN_TRADE_NOTIONAL:
                break
                
        except Exception as e:
            logger.error(f"Alpaca BUY order failed for {sym}: {e}")
            skipped.append(f"BUY {sym} order failed: {str(e)[:50]}")
    
    set_cash(conn, cash)
    conn.commit()
    
    return {
        "executed": executed,
        "skipped": skipped,
        "cash": cash
    }
