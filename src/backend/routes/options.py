"""Options API routes."""

import json
from datetime import datetime
from flask import Blueprint, jsonify

from src.database import db_conn
from src.workers.options_worker import OPTIONS
from src.config import Config

bp = Blueprint("options", __name__, url_prefix="/api/options")


def calculate_moneyness(option_type: str, strike: float, spot: float) -> str:
    """
    Calculate if option is ITM, ATM, or OTM.
    
    Args:
        option_type: 'Call' or 'Put'
        strike: Strike price
        spot: Current spot price
        
    Returns:
        'ITM', 'ATM', or 'OTM'
    """
    if spot == 0:
        return 'Unknown'
    
    pct_diff = abs((strike - spot) / spot)
    
    # Within 2% is considered ATM
    if pct_diff < 0.02:
        return 'ATM'
    
    if option_type == 'Call':
        return 'ITM' if strike < spot else 'OTM'
    else:  # Put
        return 'ITM' if strike > spot else 'OTM'


@bp.route("")
def get_options():
    """Get all monitored options with current data."""
    with db_conn() as conn:
        # Get current spot prices
        snap = conn.execute("SELECT prices_json FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if snap:
            prices = json.loads(snap["prices_json"] or "{}")
            spot_prices = {sym: float(p.get("current", 0)) for sym, p in prices.items()}
        else:
            spot_prices = {}
        
        # Get all monitored options with position info
        options_rows = conn.execute("""
            SELECT 
                om.*,
                os.bid, os.ask, os.last, os.ts as snapshot_ts,
                op.position_id, op.qty as position_qty, op.avg_cost, op.updated_at as position_updated
            FROM options_monitored om
            LEFT JOIN options_snapshots os ON om.option_id = os.option_id
            LEFT JOIN options_positions op ON om.option_id = op.option_id AND op.qty > 0
            WHERE om.enabled = 1
            AND os.snapshot_id = (
                SELECT MAX(snapshot_id) 
                FROM options_snapshots 
                WHERE option_id = om.option_id
            )
            ORDER BY om.underlying, om.option_type, om.expiration, om.strike
        """).fetchall()
        
        # Calculate aggregate Greeks
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        
        options_list = []
        for row in options_rows:
            spot = spot_prices.get(row["underlying"], 0)
            moneyness = calculate_moneyness(row["option_type"], row["strike"], spot)
            
            # Calculate DTE (days to expiration)
            try:
                exp_date = datetime.fromisoformat(row["expiration"])
                dte = (exp_date.date() - datetime.now().date()).days
            except:
                dte = 0
            
            # Accumulate Greeks
            total_delta += float(row["delta"] or 0)
            total_gamma += float(row["gamma"] or 0)
            total_theta += float(row["theta"] or 0)
            total_vega += float(row["vega"] or 0)
            
            # Position info (if executed)
            has_position = row["position_id"] is not None
            position_qty = float(row["position_qty"] or 0) if has_position else 0
            avg_cost = float(row["avg_cost"] or 0) if has_position else 0
            position_updated = row["position_updated"] if has_position else None
            
            options_list.append({
                "option_id": int(row["option_id"]),
                "underlying": row["underlying"],
                "type": row["option_type"],
                "strike": float(row["strike"]),
                "expiration": row["expiration"],
                "dte": dte,
                "contract": row["contract_symbol"],
                "last_price": float(row["last"] or 0),
                "bid": float(row["bid"] or 0),
                "ask": float(row["ask"] or 0),
                "volume": int(row["volume"] or 0),
                "open_interest": int(row["open_interest"] or 0),
                "delta": float(row["delta"] or 0),
                "gamma": float(row["gamma"] or 0),
                "theta": float(row["theta"] or 0),
                "vega": float(row["vega"] or 0),
                "iv": float(row["implied_volatility"] or 0),
                "reasoning": row["selection_reason"] or "",
                "moneyness": moneyness,
                "spot_price": spot,
                "last_updated": row["last_updated"],
                "executed": has_position,
                "position_qty": position_qty,
                "avg_cost": avg_cost,
                "executed_at": position_updated
            })
    
    return jsonify({
        "monitored_count": len(options_list),
        "worker_running": OPTIONS.running,
        "worker_enabled": Config.OPTIONS_ENABLED,
        "last_update": options_list[0]["last_updated"] if options_list else None,
        "aggregate_greeks": {
            "delta": round(total_delta, 2),
            "gamma": round(total_gamma, 3),
            "theta": round(total_theta, 2),
            "vega": round(total_vega, 2)
        },
        "options": options_list,
        "stats": OPTIONS.stats
    })


@bp.route("/history/<int:option_id>")
def get_option_history(option_id: int):
    """Get pricing history for a specific option."""
    with db_conn() as conn:
        snapshots = conn.execute("""
            SELECT ts, bid, ask, last, volume, open_interest,
                   implied_volatility, delta, gamma, theta, vega
            FROM options_snapshots
            WHERE option_id = ?
            ORDER BY ts DESC
            LIMIT 100
        """, (option_id,)).fetchall()
        
        return jsonify({
            "option_id": option_id,
            "snapshots": [
                {
                    "ts": row["ts"],
                    "bid": float(row["bid"] or 0),
                    "ask": float(row["ask"] or 0),
                    "last": float(row["last"] or 0),
                    "volume": int(row["volume"] or 0),
                    "open_interest": int(row["open_interest"] or 0),
                    "iv": float(row["implied_volatility"] or 0),
                    "delta": float(row["delta"] or 0),
                    "gamma": float(row["gamma"] or 0),
                    "theta": float(row["theta"] or 0),
                    "vega": float(row["vega"] or 0)
                }
                for row in snapshots
            ]
        })
