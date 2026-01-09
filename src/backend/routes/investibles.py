"""Investible configuration API routes with LLM-powered portfolio expansion."""

import json
import logging
import threading
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from src.config import Config
from src.database import db_conn, bootstrap_investibles, get_investible_tree
from src.llm.expansion_budget import ExpansionBudget
from src.llm.interface import llm_chat_json
from src.llm.prompts import get_prompt, format_prompt
from src.utils import utc_now

logger = logging.getLogger("kginvest")

bp = Blueprint("investibles", __name__, url_prefix="/api/investibles")

# Global expansion budget (separate from worker LLM budget)
EXPANSION_BUDGET = ExpansionBudget(
    int(Config.__dict__.get("EXPANSION_LLM_CALLS_PER_MIN", 10))
)

# Global expansion state tracker
EXPANSION_STATE = {
    "is_running": False,
    "current_ticker": None,
    "progress": 0,
    "total": 0,
    "error": None,
}
EXPANSION_LOCK = threading.Lock()


# ---------------------- LLM Helper Functions ----------------------

def llm_detect_sector(ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Use LLM to detect sector and subsector for a ticker.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        Tuple of (sector, subsector) or (None, None) on failure
    """
    if not EXPANSION_BUDGET.acquire():
        logger.warning(f"Expansion budget exhausted, cannot detect sector for {ticker}")
        return None, None
    
    # Load prompts from file
    prompt_config = get_prompt("expansion", "sector_detection", force_reload=False)
    if not prompt_config:
        logger.error("Failed to load sector_detection prompt")
        return None, None
    
    system_prompt = prompt_config["system"]
    user_prompt = format_prompt(prompt_config["user_template"], ticker=ticker)
    
    try:
        parsed, raw = llm_chat_json(system_prompt, user_prompt)
        if parsed and "sector" in parsed:
            sector = parsed.get("sector", "Unknown")
            subsector = parsed.get("subsector", "")
            logger.info(f"LLM detected sector for {ticker}: {sector} / {subsector}")
            return sector, subsector
        else:
            logger.warning(f"LLM sector detection failed for {ticker}: {raw}")
            return None, None
    except Exception as e:
        logger.error(f"Error in LLM sector detection for {ticker}: {e}")
        EXPANSION_BUDGET.set_error(str(e))
        return None, None


def llm_find_similar(ticker: str, count: int = 3) -> List[Dict]:
    """
    Use LLM to find similar stocks in the same industry.
    
    Args:
        ticker: Stock ticker symbol
        count: Number of similar stocks to find
        
    Returns:
        List of dicts with keys: ticker, name, reason
    """
    if not EXPANSION_BUDGET.wait_and_acquire(timeout=30.0):
        logger.warning(f"Expansion budget timeout, cannot find similar stocks for {ticker}")
        return []
    
    # Load prompts from file
    prompt_config = get_prompt("expansion", "find_similar", force_reload=False)
    if not prompt_config:
        logger.error("Failed to load find_similar prompt")
        return []
    
    system_prompt = prompt_config["system"]
    user_prompt = format_prompt(prompt_config["user_template"], ticker=ticker, count=count)
    
    try:
        parsed, raw = llm_chat_json(system_prompt, user_prompt)
        if parsed and "similar_stocks" in parsed:
            stocks = parsed["similar_stocks"][:count]
            logger.info(f"LLM found {len(stocks)} similar stocks for {ticker}")
            return stocks
        else:
            logger.warning(f"LLM similar stocks failed for {ticker}: {raw}")
            return []
    except Exception as e:
        logger.error(f"Error finding similar stocks for {ticker}: {e}")
        EXPANSION_BUDGET.set_error(str(e))
        return []


def llm_find_dependents(ticker: str, count: int = 3) -> List[Dict]:
    """
    Use LLM to find dependent/influencer stocks (suppliers, customers, etc.).
    
    Args:
        ticker: Stock ticker symbol
        count: Number of dependent stocks to find
        
    Returns:
        List of dicts with keys: ticker, name, relationship
    """
    if not EXPANSION_BUDGET.wait_and_acquire(timeout=30.0):
        logger.warning(f"Expansion budget timeout, cannot find dependents for {ticker}")
        return []
    
    # Load prompts from file
    prompt_config = get_prompt("expansion", "find_dependents", force_reload=False)
    if not prompt_config:
        logger.error("Failed to load find_dependents prompt")
        return []
    
    system_prompt = prompt_config["system"]
    user_prompt = format_prompt(prompt_config["user_template"], ticker=ticker, count=count)
    
    try:
        parsed, raw = llm_chat_json(system_prompt, user_prompt)
        if parsed and "dependents" in parsed:
            stocks = parsed["dependents"][:count]
            logger.info(f"LLM found {len(stocks)} dependent stocks for {ticker}")
            return stocks
        else:
            logger.warning(f"LLM dependents failed for {ticker}: {raw}")
            return []
    except Exception as e:
        logger.error(f"Error finding dependent stocks for {ticker}: {e}")
        EXPANSION_BUDGET.set_error(str(e))
        return []


def expand_all_investibles_background(max_stocks: int = 27):
    """
    Background task to expand ALL existing investibles iteratively.
    
    This enables compound expansion where:
    - First run: Level 0 stocks → Level 1
    - Second run: Level 1 stocks → Level 2
    - Third run: Level 2 stocks → Level 3, etc.
    
    Args:
        max_stocks: Maximum total stocks to reach (default 27)
    """
    global EXPANSION_STATE
    
    try:
        with EXPANSION_LOCK:
            EXPANSION_STATE["is_running"] = True
            EXPANSION_STATE["error"] = None
        
        logger.info("Starting expand-all for all investibles")
        
        # Get all enabled investibles
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT ticker FROM investibles WHERE enabled=1 ORDER BY expansion_level, ticker"
            ).fetchall()
            tickers_to_expand = [row["ticker"] for row in rows]
        
        if not tickers_to_expand:
            logger.info("No investibles to expand")
            return
        
        total_tickers = len(tickers_to_expand)
        with EXPANSION_LOCK:
            EXPANSION_STATE["total"] = total_tickers
            EXPANSION_STATE["progress"] = 0
        
        # Expand each ticker sequentially
        for idx, ticker in enumerate(tickers_to_expand, 1):
            with EXPANSION_LOCK:
                EXPANSION_STATE["current_ticker"] = ticker
                EXPANSION_STATE["progress"] = idx
            
            logger.info(f"Expanding {ticker} ({idx}/{total_tickers})")
            
            # Run expansion for this ticker
            expand_portfolio_tree_background(ticker, max_stocks)
            
            # Check if we've hit max stocks
            with db_conn() as conn:
                current_count = conn.execute("SELECT COUNT(*) as cnt FROM investibles").fetchone()["cnt"]
                if current_count >= max_stocks:
                    logger.info(f"Reached max stocks limit ({max_stocks}), stopping expand-all")
                    break
        
        logger.info("Expand-all complete")
        
    except Exception as e:
        logger.error(f"Error in expand-all: {e}")
        with EXPANSION_LOCK:
            EXPANSION_STATE["error"] = str(e)
    finally:
        with EXPANSION_LOCK:
            EXPANSION_STATE["is_running"] = False
            EXPANSION_STATE["current_ticker"] = None


def expand_portfolio_tree_background(start_ticker: str, max_stocks: int = 27):
    """
    Background task to expand portfolio using 1→3→9→27 pattern.
    
    Algorithm:
    1. Level 0: User's ticker (already inserted)
    2. Level 1: Find 3 similar industry stocks
    3. Level 2: For each level 1, find 3 dependents (up to 9)
    4. Continue until reaching max_stocks
    
    Args:
        start_ticker: The ticker to start expansion from
        max_stocks: Maximum total stocks to reach (default 27)
    """
    global EXPANSION_STATE
    
    try:
        with EXPANSION_LOCK:
            EXPANSION_STATE["is_running"] = True
            EXPANSION_STATE["current_ticker"] = start_ticker
            EXPANSION_STATE["progress"] = 0
            EXPANSION_STATE["error"] = None
        
        logger.info(f"Starting portfolio expansion from {start_ticker}")
        
        # Track all tickers to avoid duplicates
        existing_tickers = set()
        with db_conn() as conn:
            rows = conn.execute("SELECT ticker FROM investibles").fetchall()
            existing_tickers = {row["ticker"] for row in rows}
        
        # Count current stocks
        current_count = len(existing_tickers)
        if current_count >= max_stocks:
            logger.info(f"Already at {current_count} stocks, no expansion needed")
            return
        
        with EXPANSION_LOCK:
            EXPANSION_STATE["total"] = max_stocks - current_count
        
        # Level 1: Find 3 similar stocks
        level1_count = min(3, max_stocks - current_count)
        level1_stocks = llm_find_similar(start_ticker, count=level1_count)
        
        level1_added = []
        for stock in level1_stocks:
            ticker = stock.get("ticker", "").upper()
            if not ticker or ticker in existing_tickers:
                continue
            
            name = stock.get("name", ticker)
            reason = stock.get("reason", "")
            
            # Detect sector
            sector, _ = llm_detect_sector(ticker)
            
            # Insert into database
            with db_conn() as conn:
                try:
                    conn.execute(
                        "INSERT INTO investibles(ticker, name, sector, enabled, added_at, "
                        "added_by, parent_ticker, expansion_level, notes) "
                        "VALUES(?,?,?,1,?,?,?,?,?)",
                        (ticker, name, sector, utc_now(), 'llm_expansion', 
                         start_ticker, 1, reason)
                    )
                    conn.commit()
                    existing_tickers.add(ticker)
                    level1_added.append(ticker)
                    current_count += 1
                    
                    with EXPANSION_LOCK:
                        EXPANSION_STATE["progress"] += 1
                    
                    logger.info(f"Added level 1 stock: {ticker} (similar to {start_ticker})")
                    
                    if current_count >= max_stocks:
                        break
                except Exception as e:
                    logger.error(f"Failed to insert {ticker}: {e}")
        
        # Level 2: For each level 1 stock, find dependents
        if current_count < max_stocks and level1_added:
            for parent in level1_added:
                if current_count >= max_stocks:
                    break
                
                level2_count = min(3, max_stocks - current_count)
                level2_stocks = llm_find_dependents(parent, count=level2_count)
                
                for stock in level2_stocks:
                    ticker = stock.get("ticker", "").upper()
                    if not ticker or ticker in existing_tickers:
                        continue
                    
                    name = stock.get("name", ticker)
                    relationship = stock.get("relationship", "")
                    
                    # Detect sector
                    sector, _ = llm_detect_sector(ticker)
                    
                    # Insert into database
                    with db_conn() as conn:
                        try:
                            conn.execute(
                                "INSERT INTO investibles(ticker, name, sector, enabled, added_at, "
                                "added_by, parent_ticker, expansion_level, notes) "
                                "VALUES(?,?,?,1,?,?,?,?,?)",
                                (ticker, name, sector, utc_now(), 'llm_expansion', 
                                 parent, 2, relationship)
                            )
                            conn.commit()
                            existing_tickers.add(ticker)
                            current_count += 1
                            
                            with EXPANSION_LOCK:
                                EXPANSION_STATE["progress"] += 1
                            
                            logger.info(f"Added level 2 stock: {ticker} ({relationship} of {parent})")
                            
                            if current_count >= max_stocks:
                                break
                        except Exception as e:
                            logger.error(f"Failed to insert {ticker}: {e}")
        
        logger.info(f"Portfolio expansion complete: {current_count} total stocks")
        
    except Exception as e:
        logger.error(f"Error in portfolio expansion: {e}")
        with EXPANSION_LOCK:
            EXPANSION_STATE["error"] = str(e)
    finally:
        with EXPANSION_LOCK:
            EXPANSION_STATE["is_running"] = False
            EXPANSION_STATE["current_ticker"] = None


# ---------------------- API Routes ----------------------

@bp.route("", methods=["GET"])
def list_investibles():
    """List all investibles with tree structure."""
    bootstrap_investibles()  # Ensure table is populated
    
    tree = get_investible_tree()
    budget_stats = EXPANSION_BUDGET.stats()
    
    # Convert None key to "null" for JSON serialization
    json_safe_tree = {}
    for parent_ticker, children in tree.items():
        key = "null" if parent_ticker is None else parent_ticker
        json_safe_tree[key] = children
    
    # Flatten for simple list view
    all_investibles = []
    for children in tree.values():
        all_investibles.extend(children)
    
    # Sort by expansion level, then ticker
    all_investibles.sort(key=lambda x: (x["expansion_level"], x["ticker"]))
    
    return jsonify({
        "investibles": all_investibles,
        "tree": json_safe_tree,
        "expansion_budget": budget_stats,
    })


@bp.route("", methods=["POST"])
def add_investible():
    """Add a new investible ticker and optionally trigger expansion."""
    data = request.get_json()
    
    if not data or "ticker" not in data:
        return jsonify({"error": "Missing ticker field"}), 400
    
    ticker = data["ticker"].strip().upper()
    if not ticker:
        return jsonify({"error": "Ticker cannot be empty"}), 400
    
    name = data.get("name", ticker)
    notes = data.get("notes", "")
    auto_expand = data.get("auto_expand", False)
    
    # Detect sector using LLM
    sector = data.get("sector")
    if not sector:
        sector, _ = llm_detect_sector(ticker)
    
    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO investibles(ticker, name, sector, enabled, added_at, "
                "added_by, parent_ticker, expansion_level, notes) "
                "VALUES(?,?,?,1,?,?,NULL,0,?)",
                (ticker, name, sector, utc_now(), 'user', notes)
            )
            conn.commit()
            
            response = {
                "success": True,
                "ticker": ticker,
                "sector": sector,
                "message": f"Added investible {ticker}"
            }
            
            # Trigger expansion in background if requested
            if auto_expand:
                max_stocks = int(Config.__dict__.get("EXPANSION_MAX_STOCKS", 27))
                threading.Thread(
                    target=expand_portfolio_tree_background,
                    args=(ticker, max_stocks),
                    daemon=True
                ).start()
                response["expansion_started"] = True
            
            return jsonify(response)
            
        except Exception as e:
            return jsonify({"error": f"Failed to add investible: {str(e)}"}), 500


@bp.route("/<ticker>", methods=["PUT"])
def update_investible(ticker):
    """Update investible configuration (enable/disable, sector, notes, etc.)."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    ticker = ticker.upper()
    
    with db_conn() as conn:
        # Check if exists
        exists = conn.execute(
            "SELECT 1 FROM investibles WHERE ticker=?", (ticker,)
        ).fetchone()
        
        if not exists:
            return jsonify({"error": f"Investible {ticker} not found"}), 404
        
        # Build update query dynamically
        updates = []
        params = []
        
        if "enabled" in data:
            updates.append("enabled=?")
            params.append(1 if data["enabled"] else 0)
        
        if "name" in data:
            updates.append("name=?")
            params.append(data["name"])
        
        if "sector" in data:
            updates.append("sector=?")
            params.append(data["sector"])
        
        if "notes" in data:
            updates.append("notes=?")
            params.append(data["notes"])
        
        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400
        
        params.append(ticker)
        query = f"UPDATE investibles SET {', '.join(updates)} WHERE ticker=?"
        
        conn.execute(query, params)
        conn.commit()
        
    return jsonify({
        "success": True,
        "ticker": ticker,
        "message": f"Updated investible {ticker}"
    })


@bp.route("/<ticker>", methods=["DELETE"])
def delete_investible(ticker):
    """Remove an investible ticker."""
    ticker = ticker.upper()
    
    with db_conn() as conn:
        result = conn.execute(
            "DELETE FROM investibles WHERE ticker=?", (ticker,)
        )
        conn.commit()
        
        if result.rowcount == 0:
            return jsonify({"error": f"Investible {ticker} not found"}), 404
        
    return jsonify({
        "success": True,
        "ticker": ticker,
        "message": f"Removed investible {ticker}"
    })


@bp.route("/expand/<ticker>", methods=["POST"])
def expand_investible(ticker):
    """Manually trigger portfolio expansion from a ticker."""
    ticker = ticker.upper()
    
    # Check if ticker exists
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM investibles WHERE ticker=?", (ticker,)
        ).fetchone()
        
        if not exists:
            return jsonify({"error": f"Investible {ticker} not found"}), 404
    
    # Check if expansion already running
    with EXPANSION_LOCK:
        if EXPANSION_STATE["is_running"]:
            return jsonify({
                "error": "Expansion already in progress",
                "current_ticker": EXPANSION_STATE["current_ticker"]
            }), 409
    
    # Start expansion in background
    max_stocks = int(Config.__dict__.get("EXPANSION_MAX_STOCKS", 27))
    threading.Thread(
        target=expand_portfolio_tree_background,
        args=(ticker, max_stocks),
        daemon=True
    ).start()
    
    return jsonify({
        "success": True,
        "ticker": ticker,
        "message": f"Started expansion from {ticker}",
        "max_stocks": max_stocks
    })


@bp.route("/expansion-status", methods=["GET"])
def expansion_status():
    """Get current expansion progress."""
    with EXPANSION_LOCK:
        state = dict(EXPANSION_STATE)
    
    budget_stats = EXPANSION_BUDGET.stats()
    
    return jsonify({
        "expansion": state,
        "budget": budget_stats
    })


@bp.route("/expand-all", methods=["POST"])
def expand_all():
    """
    Expand ALL existing investibles iteratively.
    
    This allows compound expansion where stocks can be expanded multiple times,
    creating deeper levels: Level 0 → 1 → 2 → 3, etc.
    """
    # Check if expansion already running
    with EXPANSION_LOCK:
        if EXPANSION_STATE["is_running"]:
            return jsonify({
                "error": "Expansion already in progress",
                "current_ticker": EXPANSION_STATE["current_ticker"]
            }), 409
    
    # Start expansion in background
    max_stocks = int(Config.__dict__.get("EXPANSION_MAX_STOCKS", 27))
    threading.Thread(
        target=expand_all_investibles_background,
        args=(max_stocks,),
        daemon=True
    ).start()
    
    return jsonify({
        "success": True,
        "message": "Started expanding all investibles",
        "max_stocks": max_stocks
    })


@bp.route("/remove-children/<ticker>", methods=["DELETE"])
def remove_children(ticker):
    """Remove all children (similar/dependent stocks) for a ticker."""
    ticker = ticker.upper()
    
    # Check if ticker exists
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM investibles WHERE ticker=?", (ticker,)
        ).fetchone()
        
        if not exists:
            return jsonify({"error": f"Investible {ticker} not found"}), 404
        
        # Delete all children recursively (children and grandchildren)
        # First get all children
        children = conn.execute(
            "SELECT ticker FROM investibles WHERE parent_ticker=?", (ticker,)
        ).fetchall()
        
        child_tickers = [row["ticker"] for row in children]
        
        # Delete grandchildren (children of children)
        for child_ticker in child_tickers:
            conn.execute(
                "DELETE FROM investibles WHERE parent_ticker=?", (child_ticker,)
            )
        
        # Delete direct children
        result = conn.execute(
            "DELETE FROM investibles WHERE parent_ticker=?", (ticker,)
        )
        conn.commit()
        
        total_deleted = result.rowcount
        
    return jsonify({
        "success": True,
        "ticker": ticker,
        "deleted_count": total_deleted,
        "message": f"Removed {total_deleted} children for {ticker}"
    })


@bp.route("/detect-sector/<ticker>", methods=["POST"])
def detect_sector(ticker):
    """Manually trigger sector detection for a ticker."""
    ticker = ticker.upper()
    
    sector, subsector = llm_detect_sector(ticker)
    
    if sector:
        # Update in database if ticker exists
        with db_conn() as conn:
            conn.execute(
                "UPDATE investibles SET sector=? WHERE ticker=?",
                (sector, ticker)
            )
            conn.commit()
        
        return jsonify({
            "success": True,
            "ticker": ticker,
            "sector": sector,
            "subsector": subsector
        })
    else:
        return jsonify({
            "error": "Failed to detect sector",
            "ticker": ticker
        }), 500
