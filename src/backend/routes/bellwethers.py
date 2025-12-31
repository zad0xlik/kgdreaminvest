"""Bellwether configuration API routes."""

from flask import Blueprint, jsonify, request

from src.database import db_conn, bootstrap_bellwethers
from src.utils import utc_now

bp = Blueprint("bellwethers", __name__, url_prefix="/api/bellwethers")


@bp.route("", methods=["GET"])
def list_bellwethers():
    """List all bellwethers with their configuration."""
    bootstrap_bellwethers()  # Ensure table is populated
    
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, category, enabled, added_at, notes "
            "FROM bellwethers ORDER BY category, ticker"
        ).fetchall()
        
        bellwethers = [
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "category": row["category"],
                "enabled": bool(row["enabled"]),
                "added_at": row["added_at"],
                "notes": row["notes"],
            }
            for row in rows
        ]
        
    return jsonify({"bellwethers": bellwethers})


@bp.route("", methods=["POST"])
def add_bellwether():
    """Add a new bellwether ticker."""
    data = request.get_json()
    
    if not data or "ticker" not in data:
        return jsonify({"error": "Missing ticker field"}), 400
    
    ticker = data["ticker"].strip().upper()
    if not ticker:
        return jsonify({"error": "Ticker cannot be empty"}), 400
    
    name = data.get("name", ticker)
    category = data.get("category", "other")
    notes = data.get("notes", "")
    
    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO bellwethers(ticker, name, category, enabled, added_at, notes) "
                "VALUES(?,?,?,1,?,?)",
                (ticker, name, category, utc_now(), notes)
            )
            conn.commit()
            
            return jsonify({
                "success": True,
                "ticker": ticker,
                "message": f"Added bellwether {ticker}"
            })
        except Exception as e:
            return jsonify({"error": f"Failed to add bellwether: {str(e)}"}), 500


@bp.route("/<ticker>", methods=["PUT"])
def update_bellwether(ticker):
    """Update bellwether configuration (enable/disable, notes, etc.)."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    ticker = ticker.upper()
    
    with db_conn() as conn:
        # Check if exists
        exists = conn.execute(
            "SELECT 1 FROM bellwethers WHERE ticker=?", (ticker,)
        ).fetchone()
        
        if not exists:
            return jsonify({"error": f"Bellwether {ticker} not found"}), 404
        
        # Build update query dynamically based on provided fields
        updates = []
        params = []
        
        if "enabled" in data:
            updates.append("enabled=?")
            params.append(1 if data["enabled"] else 0)
        
        if "name" in data:
            updates.append("name=?")
            params.append(data["name"])
        
        if "category" in data:
            updates.append("category=?")
            params.append(data["category"])
        
        if "notes" in data:
            updates.append("notes=?")
            params.append(data["notes"])
        
        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400
        
        params.append(ticker)
        query = f"UPDATE bellwethers SET {', '.join(updates)} WHERE ticker=?"
        
        conn.execute(query, params)
        conn.commit()
        
    return jsonify({
        "success": True,
        "ticker": ticker,
        "message": f"Updated bellwether {ticker}"
    })


@bp.route("/<ticker>", methods=["DELETE"])
def delete_bellwether(ticker):
    """Remove a bellwether ticker."""
    ticker = ticker.upper()
    
    with db_conn() as conn:
        result = conn.execute(
            "DELETE FROM bellwethers WHERE ticker=?", (ticker,)
        )
        conn.commit()
        
        if result.rowcount == 0:
            return jsonify({"error": f"Bellwether {ticker} not found"}), 404
        
    return jsonify({
        "success": True,
        "ticker": ticker,
        "message": f"Removed bellwether {ticker}"
    })
