"""State API routes."""

import json
import time
from flask import Blueprint, jsonify

from src.database import db_conn, init_db, bootstrap_if_empty, bootstrap_bellwethers
from src.database.schema import migrate_add_executed_at
from src.database.operations import portfolio_state
from src.llm.budget import LLM_BUDGET
from src.backend.services import fmt_money
from src.workers import MARKET, DREAM, THINK
from src.config import AUTO_TRADE

bp = Blueprint("api", __name__, url_prefix="/api")

# Cache for Alpaca account sync to avoid excessive API calls
_alpaca_sync_cache = {
    "last_sync": 0,
    "cache_duration": 30  # 30 seconds cache
}


def _get_broker_account_info(conn):
    """
    Fetch broker-specific account information for UI display.
    
    Returns dict with provider, account_type, account_number, etc.
    """
    from src.config import Config
    import logging
    
    logger = logging.getLogger("kginvest")
    
    if Config.BROKER_PROVIDER == "alpaca":
        try:
            from src.portfolio.alpaca_stocks_trading import get_alpaca_trading_client
            
            client = get_alpaca_trading_client()
            account = client.get_account()
            
            # Calculate daily change percentage
            daily_change_pct = 0.0
            try:
                last_equity = float(account.last_equity)
                current_equity = float(account.equity)
                if last_equity > 0:
                    daily_change_pct = (current_equity / last_equity) - 1.0
            except (ValueError, ZeroDivisionError, AttributeError):
                pass
            
            return {
                "provider": "alpaca",
                "account_type": "Paper Account" if Config.ALPACA_PAPER_MODE else "Individual Trading",
                "account_number": str(account.account_number),
                "account_id": str(account.id),
                "status": str(account.status),
                "is_paper": bool(Config.ALPACA_PAPER_MODE),
                "daily_change_pct": float(daily_change_pct)
            }
        except Exception as e:
            logger.warning(f"Failed to fetch Alpaca account info: {e}")
            return {
                "provider": "alpaca",
                "account_type": "Alpaca (Offline)",
                "account_number": "—",
                "is_paper": bool(Config.ALPACA_PAPER_MODE),
                "status": "unavailable",
                "daily_change_pct": 0.0
            }
    else:
        # Paper trading mode (Yahoo Finance)
        return {
            "provider": "paper",
            "account_type": "Local Simulation",
            "account_number": None,
            "is_paper": True,
            "status": "active",
            "daily_change_pct": 0.0
        }


@bp.route("/transactions")
def transactions():
    """Return transaction history and portfolio value timeline."""
    from src.config import Config
    from src.database.operations import kv_get
    
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
        
        # Determine starting balance based on broker provider
        # For Alpaca, use the actual account starting balance; for paper trading, use .env
        if Config.BROKER_PROVIDER == "alpaca":
            alpaca_start = kv_get(conn, "alpaca_start_balance")
            if alpaca_start:
                START_CASH = float(alpaca_start)
            else:
                # Fallback to current equity if starting balance not yet stored
                # This happens on first run before any sync
                START_CASH = current_cash + sum(float(p["market_value"]) for p in positions)
        else:
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
        # Sync Alpaca account if using Alpaca broker (with caching to avoid excessive API calls)
        from src.config import Config
        if Config.BROKER_PROVIDER == "alpaca":
            current_time = time.time()
            time_since_last_sync = current_time - _alpaca_sync_cache["last_sync"]
            
            # Only sync if cache expired (30 seconds)
            if time_since_last_sync >= _alpaca_sync_cache["cache_duration"]:
                try:
                    from src.portfolio.alpaca_stocks_trading import sync_alpaca_account, sync_alpaca_positions
                    
                    # Sync account balance to local database
                    sync_alpaca_account(conn)
                    
                    # Sync positions to local database
                    sync_alpaca_positions(conn)
                    
                    # Update cache timestamp
                    _alpaca_sync_cache["last_sync"] = current_time
                    
                    import logging
                    logging.getLogger("kginvest").debug(
                        f"Alpaca account synced (cache duration: {_alpaca_sync_cache['cache_duration']}s)"
                    )
                except Exception as e:
                    import logging
                    logging.getLogger("kginvest").warning(
                        f"Failed to sync Alpaca account in /api/state: {e}. "
                        f"Using cached local database values."
                    )
        
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
        broker_info = _get_broker_account_info(conn)

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
        "broker": broker_info,
        "llm": llm,
        "logs": [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": r["detail"] or ""} for r in logs],
        "insights": [_ins_row(r) for r in insights],
    })


@bp.route("/symbols/search")
def search_symbols():
    """
    Search for stock symbols using configured data provider.
    
    Query Parameters:
        q (str): Search query (symbol or company name)
        limit (int, optional): Maximum results to return (default: 10)
    
    Returns:
        JSON array of symbol results with fields:
        - symbol: Stock ticker
        - name: Company name
        - exchange: Stock exchange
        - tradable: Whether symbol is tradeable (Alpaca only)
        - provider: Data source used (yahoo/alpaca)
    
    Example:
        GET /api/symbols/search?q=AAPL&limit=5
    """
    from flask import request
    from src.config import Config
    
    query = request.args.get('q', '').strip()
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    
    if limit < 1 or limit > 100:
        return jsonify({"error": "Limit must be between 1 and 100"}), 400
    
    results = []
    provider = Config.DATA_PROVIDER
    
    if provider == "alpaca":
        # Use Alpaca symbol search
        try:
            from src.market.alpaca_stocks_client import search_symbols_alpaca
            
            alpaca_results = search_symbols_alpaca(query, limit=limit)
            
            # Add provider field to each result
            for result in alpaca_results:
                result["provider"] = "alpaca"
            
            results = alpaca_results
            
        except Exception as e:
            # Fall back to Yahoo on error
            import logging
            logging.getLogger("kginvest").warning(
                f"Alpaca symbol search failed, falling back to Yahoo: {e}"
            )
            provider = "yahoo"
    
    if provider == "yahoo" or not results:
        # Use Yahoo Finance search (yfinance doesn't have native search, 
        # so we'll provide manual symbol validation)
        try:
            import yfinance as yf
            
            # Try to look up the symbol directly
            ticker = yf.Ticker(query.upper())
            info = ticker.info
            
            if info and info.get('symbol'):
                results = [{
                    "symbol": info.get('symbol', query.upper()),
                    "name": info.get('longName') or info.get('shortName', query.upper()),
                    "exchange": info.get('exchange', 'Unknown'),
                    "tradable": True,
                    "provider": "yahoo"
                }]
            else:
                # No exact match found
                results = []
                
        except Exception as e:
            import logging
            logging.getLogger("kginvest").warning(f"Yahoo symbol search failed: {e}")
            results = []
    
    return jsonify({
        "query": query,
        "results": results,
        "provider": provider
    })
