"""Insight management routes."""

import json
from flask import Blueprint, jsonify

from src.database import db_conn, init_db, bootstrap_if_empty, log_event
from src.portfolio.trading import execute_paper_trades
from src.config import TRADE_ANYTIME
from src.utils import market_is_open_et

bp = Blueprint("insights", __name__, url_prefix="/api")


@bp.post("/insight/<int:insight_id>/approve")
def insight_approve(insight_id: int):
    """Manually approve and execute an insight's trades."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        ins = conn.execute("SELECT * FROM insights WHERE insight_id=?", (insight_id,)).fetchone()
        if not ins:
            return jsonify({"ok": False, "error": "insight not found"}), 404
        
        if ins["status"] == "applied":
            return jsonify({"ok": True, "message": "already applied"})

        snap = conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id=?", 
            (int(ins["evidence_snapshot_id"]),)
        ).fetchone()
        if not snap:
            snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        
        prices = json.loads((snap["prices_json"] if snap else "{}") or "{}")

        try:
            decisions = json.loads(ins["decisions_json"] or "[]")
        except Exception:
            decisions = []

        can_trade_now = TRADE_ANYTIME or (not market_is_open_et())
        if not can_trade_now:
            conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("queued", insight_id))
            log_event(conn, "trade", "approve_queued", f"id={insight_id} market_open=True")
            conn.commit()
            return jsonify({"ok": True, "status": "queued", "message": "market open; queued"})

        res = execute_paper_trades(
            conn, decisions, prices, 
            reason=f"manual approve insight {insight_id}", 
            insight_id=insight_id
        )
        conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("applied", insight_id))
        log_event(conn, "trade", "approve_applied", f"id={insight_id} executed={len(res['executed'])}")
        conn.commit()
        
        return jsonify({"ok": True, "status": "applied", "result": res})
