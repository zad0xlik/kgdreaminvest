"""State API routes."""

import json
from flask import Blueprint, jsonify

from src.database import db_conn, init_db, bootstrap_if_empty
from src.database.operations import portfolio_state
from src.llm.budget import LLM_BUDGET
from src.backend.services import fmt_money
from src.workers import MARKET, DREAM, THINK
from src.config import AUTO_TRADE

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/state")
def state():
    """Return full system state for UI updates."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()

        latest = {"spy": "—", "qqq": "—", "vix": "—", "uup": "—", "signals": "{}"}
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
                "signals": json.dumps(sig),
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
