"""Statistics and history routes."""

from flask import Blueprint, jsonify, request

from src.database import db_conn, init_db, bootstrap_if_empty
from src.config import INVESTIBLES
from src.workers import MARKET, DREAM, THINK

bp = Blueprint("stats", __name__, url_prefix="/api")


@bp.route("/stats")
def stats():
    """Return system statistics."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        # Lookup statistics
        total_lookups = conn.execute("SELECT COUNT(*) AS count FROM ticker_lookups").fetchone()["count"]
        successful_lookups = conn.execute(
            "SELECT COUNT(*) AS count FROM ticker_lookups WHERE success=1"
        ).fetchone()["count"]
        failed_lookups = total_lookups - successful_lookups
        success_rate = (successful_lookups / max(total_lookups, 1)) * 100.0
        
        # Recent lookup activity (last 24 hours)
        recent_lookups = conn.execute("""
            SELECT COUNT(*) AS count FROM ticker_lookups 
            WHERE datetime(ts) >= datetime('now', '-1 day')
        """).fetchone()["count"]
        
        # Top successful tickers by lookup frequency
        top_tickers = conn.execute("""
            SELECT ticker, COUNT(*) AS lookup_count, AVG(price) AS avg_price
            FROM ticker_lookups 
            WHERE success=1 AND ticker IN ({})
            GROUP BY ticker 
            ORDER BY lookup_count DESC 
            LIMIT 10
        """.format(','.join(['?' for _ in INVESTIBLES])), INVESTIBLES).fetchall()
        
        # Performance stats
        worker_stats = {
            "market": MARKET.stats,
            "dream": DREAM.stats,
            "think": THINK.stats
        }
        
        return jsonify({
            "lookup_stats": {
                "total_lookups": total_lookups,
                "successful_lookups": successful_lookups,
                "failed_lookups": failed_lookups,
                "success_rate": round(success_rate, 1),
                "recent_24h": recent_lookups
            },
            "top_tickers": [
                {
                    "ticker": r["ticker"],
                    "lookup_count": int(r["lookup_count"]),
                    "avg_price": round(float(r["avg_price"]) if r["avg_price"] else 0.0, 2)
                } for r in top_tickers
            ],
            "worker_performance": worker_stats
        })


@bp.route("/ticker-history")
def ticker_history():
    """Return ticker lookup history."""
    init_db()
    bootstrap_if_empty()
    
    limit = min(int(request.args.get("limit", 50)), 200)  # Cap at 200 for performance
    
    with db_conn() as conn:
        history = conn.execute("""
            SELECT ts, ticker, success, price, change_pct, volume
            FROM ticker_lookups 
            ORDER BY lookup_id DESC 
            LIMIT ?
        """, (limit,)).fetchall()
        
        return jsonify({
            "history": [
                {
                    "ts": r["ts"][:19] if r["ts"] else "",
                    "ticker": r["ticker"],
                    "success": bool(r["success"]),
                    "price": round(float(r["price"]), 2) if r["price"] else None,
                    "change_pct": round(float(r["change_pct"]), 2) if r["change_pct"] else None,
                    "volume": int(r["volume"]) if r["volume"] else None
                } for r in history
            ]
        })
