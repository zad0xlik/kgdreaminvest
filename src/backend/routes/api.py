"""State API routes."""

import json
from flask import Blueprint, jsonify

from src.database import db_conn, init_db, bootstrap_if_empty, bootstrap_bellwethers
from src.database.schema import migrate_add_executed_at
from src.database.operations import portfolio_state
from src.llm.budget import LLM_BUDGET
from src.backend.services import fmt_money
from src.workers import MARKET, DREAM, THINK
from src.config import AUTO_TRADE

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/transactions")
def transactions():
    """Return transaction history and portfolio value timeline."""
    from src.config import Config
    
    with db_conn() as conn:
        # Get all trades ordered by time
        trades = conn.execute("""
            SELECT trade_id, ts, symbol, side, qty, price, notional, reason 
            FROM trades 
            ORDER BY ts ASC
        """).fetchall()
        
        # Get current positions for portfolio value calculation
        positions = conn.execute("""
            SELECT symbol, qty, avg_cost, last_price,
                   (qty * last_price) as market_value,
                   (qty * avg_cost) as cost_basis
            FROM positions
        """).fetchall()
        
        # Get current cash
        cash_row = conn.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()
        current_cash = float(cash_row["v"]) if cash_row else 0
        
        # Calculate portfolio value timeline
        START_CASH = Config.START_CASH
        running_cash = START_CASH
        total_invested = 0
        total_sold = 0
        
        timeline = []
        trade_list = []
        
        # Initial point
        timeline.append({
            "timestamp": trades[0]["ts"] if trades else None,
            "portfolio_value": START_CASH,
            "cash": START_CASH,
            "equity": 0
        })
        
        # Track holdings for portfolio value calculation
        holdings = {}  # symbol -> {qty, avg_cost}
        
        for trade in trades:
            symbol = trade["symbol"]
            qty = float(trade["qty"])
            price = float(trade["price"])
            notional = float(trade["notional"])
            
            if trade["side"] == "BUY":
                running_cash -= notional
                total_invested += notional
                
                # Update holdings
                if symbol in holdings:
                    total_qty = holdings[symbol]["qty"] + qty
                    total_cost = (holdings[symbol]["qty"] * holdings[symbol]["avg_cost"]) + notional
                    holdings[symbol] = {
                        "qty": total_qty,
                        "avg_cost": total_cost / total_qty if total_qty > 0 else 0
                    }
                else:
                    holdings[symbol] = {"qty": qty, "avg_cost": price}
            else:  # SELL
                running_cash += notional
                total_sold += notional
                
                # Update holdings
                if symbol in holdings:
                    holdings[symbol]["qty"] -= qty
                    if holdings[symbol]["qty"] <= 0.0001:
                        del holdings[symbol]
            
            # Calculate equity value at current prices (using last_price from positions)
            equity_value = sum(
                h["qty"] * h["avg_cost"] for h in holdings.values()
            )
            
            portfolio_value = running_cash + equity_value
            
            timeline.append({
                "timestamp": trade["ts"],
                "portfolio_value": portfolio_value,
                "cash": running_cash,
                "equity": equity_value,
                "trade": {
                    "symbol": symbol,
                    "side": trade["side"],
                    "qty": qty,
                    "price": price,
                    "notional": notional
                }
            })
            
            trade_list.append({
                "trade_id": trade["trade_id"],
                "ts": trade["ts"],
                "symbol": symbol,
                "side": trade["side"],
                "qty": qty,
                "price": price,
                "notional": notional,
                "cash_after": running_cash,
                "reason": trade["reason"] or ""
            })
        
        # Calculate current portfolio value with market prices
        current_equity = sum(float(p["market_value"]) for p in positions)
        current_portfolio_value = current_cash + current_equity
        
        # Calculate summary stats
        total_cost_basis = sum(float(p["cost_basis"]) for p in positions)
        unrealized_gain = current_equity - total_cost_basis
        realized_gain = total_sold - sum(
            t["notional"] for t in trade_list 
            if t["side"] == "BUY" and any(t2["symbol"] == t["symbol"] and t2["side"] == "SELL" for t2 in trade_list)
        ) if total_sold > 0 else 0
        
        # For more accurate realized gain calculation
        realized_gain_accurate = 0
        for trade in trade_list:
            if trade["side"] == "SELL":
                # Find matching buys for this symbol
                symbol_buys = [t for t in trade_list if t["symbol"] == trade["symbol"] and t["side"] == "BUY" and t["trade_id"] < trade["trade_id"]]
                if symbol_buys:
                    avg_buy_cost = sum(t["notional"] for t in symbol_buys) / sum(t["qty"] for t in symbol_buys)
                    realized_gain_accurate += trade["notional"] - (trade["qty"] * avg_buy_cost)
        
        summary = {
            "start_balance": START_CASH,
            "current_cash": current_cash,
            "current_equity": current_equity,
            "current_total": current_portfolio_value,
            "total_invested": total_invested,
            "total_sold": total_sold,
            "realized_gain": realized_gain_accurate,
            "unrealized_gain": unrealized_gain,
            "total_gain": current_portfolio_value - START_CASH,
            "total_return_pct": ((current_portfolio_value - START_CASH) / START_CASH * 100) if START_CASH > 0 else 0,
            "trade_count": len(trade_list)
        }
        
        return jsonify({
            "trades": trade_list,
            "timeline": timeline,
            "summary": summary
        })


@bp.route("/state")
def state():
    """Return full system state for UI updates."""
    init_db()
    migrate_add_executed_at()  # Run migration to add executed_at column
    bootstrap_if_empty()
    bootstrap_bellwethers()
    
    with db_conn() as conn:
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()

        latest = {"spy": "—", "qqq": "—", "vix": "—", "uup": "—", "signals": {}, "timestamp": None}
        prices = {}
        if snap:
            prices = json.loads(snap["prices_json"] or "{}")
            sig = json.loads(snap["signals_json"] or "{}")
            
            def fmt_sym(sym):
                if sym in prices:
                    return f"{prices[sym]['change_pct']:+.2f}%"
                return "—"
            
            latest = {
                "spy": fmt_sym("SPY"),
                "qqq": fmt_sym("QQQ"),
                "vix": fmt_sym("^VIX"),
                "uup": fmt_sym("UUP"),
                "signals": sig,  # Send as object, not JSON string
                "timestamp": snap["ts"],  # Include snapshot timestamp
            }

        pf = portfolio_state(conn, prices=prices)
        logs = conn.execute("SELECT * FROM dream_log ORDER BY log_id DESC LIMIT 12").fetchall()
        insights = conn.execute("SELECT * FROM insights WHERE starred=1 ORDER BY insight_id DESC LIMIT 8").fetchall()
        llm = LLM_BUDGET.stats()

    def _ins_row(r):
        try:
            dec = json.loads(r["decisions_json"] or "[]")
        except Exception:
            dec = []
        return {
            "insight_id": int(r["insight_id"]),
            "ts": r["ts"],
            "title": r["title"],
            "body": r["body"],
            "decisions": json.dumps(dec)[:900],
            "critic_score": float(r["critic_score"]),
            "confidence": float(r["confidence"]),
            "status": r["status"],
        }

    return jsonify({
        "nodes": node_count,
        "edges": edge_count,
        "market_running": MARKET.running,
        "dream_running": DREAM.running,
        "think_running": THINK.running,
        "auto_trade": AUTO_TRADE,
        "latest": latest,
        "portfolio": {"cash": fmt_money(pf["cash"]), "equity": fmt_money(pf["equity"]), "positions": pf["positions"]},
        "llm": llm,
        "logs": [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": r["detail"] or ""} for r in logs],
        "insights": [_ins_row(r) for r in insights],
    })
