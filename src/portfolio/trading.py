"""Trading execution with broker provider routing."""
import logging
import sqlite3
from typing import Dict, Any, List

from src.config import Config
from src.database.operations import get_cash, set_cash
from src.utils import utc_now

logger = logging.getLogger("kginvest")


def execute_trades(
    conn: sqlite3.Connection,
    decisions: List[Dict[str, Any]],
    prices: Dict[str, Any],
    reason: str,
    insight_id: int
) -> Dict[str, Any]:
    """
    Universal trading interface - routes to correct broker provider.
    
    Routes to paper trading (Yahoo+DB) or Alpaca based on Config.BROKER_PROVIDER.
    
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
        ...     {"ticker": "AAPL", "action": "BUY", "allocation_pct": 5.0}
        ... ]
        >>> result = execute_trades(conn, decisions, prices, "test", 1)
        >>> print(f"Executed {len(result['executed'])} trades via {Config.BROKER_PROVIDER}")
    """
    if Config.BROKER_PROVIDER == "alpaca":
        from src.portfolio.alpaca_trading import execute_alpaca_trades
        logger.info("Routing trades to Alpaca")
        return execute_alpaca_trades(conn, decisions, prices, reason, insight_id)
    else:
        logger.info("Routing trades to paper trading")
        return execute_paper_trades(conn, decisions, prices, reason, insight_id)


def execute_paper_trades(
    conn: sqlite3.Connection,
    decisions: List[Dict[str, Any]],
    prices: Dict[str, Any],
    reason: str,
    insight_id: int
) -> Dict[str, Any]:
    """
    Execute paper trades with strict guard rails.
    
    Executes SELLs first (to free cash), then BUYs. Enforces:
    - Minimum trade notional
    - Maximum buy/sell percentages per cycle
    - Per-symbol weight caps
    - Cash buffer requirement
    
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
        >>> result = execute_paper_trades(conn, decisions, prices, "test", 1)
        >>> print(f"Executed {len(result['executed'])} trades")
    """
    from src.database.operations import portfolio_state
    
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

        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (utc_now(), sym, "SELL", float(sell_sh), float(p), float(notional), reason[:400], int(insight_id))
        )
        
        executed.append({
            "ticker": sym,
            "side": "SELL",
            "shares": sell_sh,
            "price": p,
            "notional": notional
        })

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
        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (utc_now(), sym, "BUY", float(shares), float(p), float(notional), reason[:400], int(insight_id))
        )
        
        executed.append({
            "ticker": sym,
            "side": "BUY",
            "shares": shares,
            "price": p,
            "notional": notional
        })

        if buy_budget < Config.MIN_TRADE_NOTIONAL:
            break

    set_cash(conn, cash)
    
    return {
        "executed": executed,
        "skipped": skipped,
        "cash": cash
    }
