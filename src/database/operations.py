"""Database CRUD operations."""
import sqlite3
from typing import Dict, Optional, Tuple, Any, List

from src.utils import utc_now, fmt_money


# ---------------------- Key-Value Store ----------------------

def kv_get(conn: sqlite3.Connection, k: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get key-value pair from meta table.
    
    Args:
        conn: SQLite connection
        k: Key to lookup
        default: Default value if key not found
        
    Returns:
        Value string or default
    """
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def kv_set(conn: sqlite3.Connection, k: str, v: str):
    """
    Set key-value pair in meta table.
    
    Args:
        conn: SQLite connection
        k: Key to set
        v: Value to store
    """
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))


# ---------------------- Edge Operations ----------------------

def norm_pair(a: str, b: str) -> Tuple[str, str]:
    """
    Normalize node pair for edge lookup.
    
    Ensures consistent ordering: (a, b) where a <= b alphabetically.
    This prevents duplicate edges like (A,B) and (B,A).
    
    Args:
        a: First node ID
        b: Second node ID
        
    Returns:
        Tuple of (node_a, node_b) in normalized order
    """
    return (a, b) if a <= b else (b, a)


def ensure_edge_id(conn: sqlite3.Connection, a: str, b: str) -> int:
    """
    Get or create edge ID for node pair.
    
    Creates edge if it doesn't exist, otherwise returns existing edge_id.
    Uses norm_pair to ensure consistent ordering.
    
    Args:
        conn: SQLite connection
        a: First node ID
        b: Second node ID
        
    Returns:
        Edge ID (integer)
    """
    a2, b2 = norm_pair(a, b)
    conn.execute(
        "INSERT OR IGNORE INTO edges(node_a, node_b, created_at) VALUES(?,?,?)",
        (a2, b2, utc_now())
    )
    row = conn.execute(
        "SELECT edge_id FROM edges WHERE node_a=? AND node_b=?",
        (a2, b2)
    ).fetchone()
    return int(row["edge_id"])


# ---------------------- Event Logging ----------------------

def log_event(conn: sqlite3.Connection, actor: str, action: str, detail: str = ""):
    """
    Log an event to dream_log table.
    
    Args:
        conn: SQLite connection
        actor: Actor/component name (e.g., "market", "dream", "think")
        action: Action type (e.g., "tick", "assess_pair", "proposal")
        detail: Optional detail string (truncated to 1600 chars)
    """
    conn.execute(
        "INSERT INTO dream_log(ts, actor, action, detail) VALUES(?,?,?,?)",
        (utc_now(), actor, action, (detail or "")[:1600]),
    )


# ---------------------- Portfolio Operations ----------------------

def get_cash(conn: sqlite3.Connection) -> float:
    """
    Get current cash balance from portfolio.
    
    Args:
        conn: SQLite connection
        
    Returns:
        Cash balance as float
    """
    from src.config import Config
    r = conn.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()
    if not r:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)",
            (str(Config.START_CASH),)
        )
        return Config.START_CASH
    try:
        return float(r["v"])
    except Exception:
        return Config.START_CASH


def set_cash(conn: sqlite3.Connection, cash: float):
    """
    Set cash balance in portfolio.
    
    Args:
        conn: SQLite connection
        cash: New cash balance
    """
    conn.execute(
        "INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)",
        (str(float(cash)),)
    )


def portfolio_state(conn: sqlite3.Connection, prices: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get current portfolio state with mark-to-market values.
    
    Args:
        conn: SQLite connection
        prices: Optional price dictionary to mark-to-market positions
        
    Returns:
        Dict with keys: cash, equity, positions (list of position dicts)
    """
    cash = get_cash(conn)
    pos = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
    positions = []
    equity = cash
    price_map = prices or {}
    
    for r in pos:
        sym = r["symbol"]
        qty = float(r["qty"])
        last = float(r["last_price"])
        
        # Update with latest price if available
        if sym in price_map:
            try:
                last = float(price_map[sym]["current"])
            except Exception:
                pass
        
        avg = float(r["avg_cost"])
        mv = qty * last
        pnl = (last - avg) * qty
        equity += mv
        
        positions.append({
            "symbol": sym,
            "qty": qty,
            "last_price": last,
            "avg_cost": avg,
            "pnl": pnl,
            "mv": mv
        })
    
    return {
        "cash": cash,
        "equity": equity,
        "positions": positions
    }


def positions_as_dict(conn: sqlite3.Connection) -> Dict[str, float]:
    """
    Get positions as a simple dictionary of symbol -> quantity.
    
    Args:
        conn: SQLite connection
        
    Returns:
        Dict mapping symbol to quantity
    """
    rows = conn.execute("SELECT symbol, qty FROM positions").fetchall()
    return {r["symbol"]: float(r["qty"]) for r in rows}


def recent_trade_summary(conn: sqlite3.Connection, limit: int = 12) -> str:
    """
    Get formatted summary of recent trades.
    
    Args:
        conn: SQLite connection
        limit: Maximum number of trades to include
        
    Returns:
        Formatted string with recent trade history
    """
    rows = conn.execute(
        "SELECT ts, symbol, side, notional FROM trades ORDER BY trade_id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    
    if not rows:
        return "No recent trades."
    
    lines = []
    for r in rows[::-1]:  # Reverse to show chronological order
        ts = (r["ts"] or "")[:19]
        lines.append(
            f"{ts}: {r['side']} {r['symbol']} notional={float(r['notional']):.2f}"
        )
    
    return "\n".join(lines)
