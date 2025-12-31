"""Options Worker - Monitors and analyzes option chains with LLM intelligence."""
import json
import logging
import random
import threading
import traceback
from typing import Optional, List, Dict

from src.config import Config
from src.database import db_conn, log_event, get_active_investibles, ensure_edge_id
from src.database.schema import edge_weight_top
from src.llm import llm_chat_json
from src.llm.prompts import get_prompt, format_prompt
from src.llm.options_budget import OPTIONS_BUDGET
from src.market.options_fetcher import (
    get_options_data, filter_options_by_criteria, prepare_options_for_llm,
    update_monitored_option, store_options_snapshot, get_monitored_options_from_db
)
from src.utils import utc_now, jitter_sleep

logger = logging.getLogger("kginvest.options")


class OptionsWorker:
    """
    Options monitoring and analysis worker.
    
    Each cycle:
    1. Fetches option chains for all active investibles
    2. Filters by DTE range and liquidity (volume/OI)
    3. For selected underlyings, asks LLM to pick best options to monitor
    4. Updates database with monitored options
    5. Creates knowledge graph nodes/edges for options
    6. Stores pricing snapshots
    
    LLM makes intelligent selection based on:
    - Greeks (Delta, Gamma, Theta, Vega)
    - Liquidity (Volume, Open Interest)
    - Implied Volatility
    - Strike prices relative to spot
    - Expiration dates (time value)
    """
    
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {
            "cycles": 0,
            "options_monitored": 0,
            "llm_calls": 0,
            "last_ts": None,
            "last_action": None,
            "last_error": None
        }

    def start(self):
        """Start the worker thread."""
        if not Config.OPTIONS_ENABLED:
            logger.info("OptionsWorker disabled (OPTIONS_ENABLED=false)")
            return
            
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("OptionsWorker started")

    def stop_now(self):
        """Stop the worker thread."""
        self.running = False
        self.stop.set()
        logger.info("OptionsWorker stop signaled")

    def _loop(self):
        """Main worker loop."""
        while self.running and not self.stop.is_set():
            try:
                self.step_once()
                self.stats["cycles"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_action"] = "cycle_complete"
                self.stats["last_error"] = None
            except Exception as e:
                self.stats["last_error"] = str(e)
                logger.error(f"OptionsWorker error: {e}")
                logger.debug(traceback.format_exc())
            
            jitter_sleep(Config.OPTIONS_INTERVAL, self.stop)

    def step_once(self):
        """Execute one options analysis cycle."""
        investibles = get_active_investibles()
        
        if not investibles:
            logger.warning("No active investibles for options monitoring")
            return
        
        # Randomly select subset of investibles to analyze this cycle (avoid rate limits)
        # Analyze 3-5 tickers per cycle, cycling through all over time
        sample_size = min(5, max(3, len(investibles) // 10))
        selected_tickers = random.sample(investibles, sample_size)
        
        logger.info(f"Fetching options for {len(selected_tickers)} tickers: {selected_tickers}")
        
        # Fetch options data
        options_df = get_options_data(selected_tickers)
        
        if options_df.empty:
            logger.warning("No options data fetched")
            return
        
        # Get spot prices for filtering and Greeks calculation
        with db_conn() as conn:
            snap = conn.execute("SELECT prices_json FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
            if not snap:
                logger.warning("No market snapshot available for spot prices")
                return
            
            prices = json.loads(snap["prices_json"] or "{}")
            spot_prices = {sym: float(p.get("current", 0)) for sym, p in prices.items()}
        
        # Filter options by criteria (DTE, volume, OI)
        filtered_df = filter_options_by_criteria(options_df, spot_prices)
        
        if filtered_df.empty:
            logger.info("No options passed liquidity/DTE filters")
            return
        
        logger.info(f"Filtered to {len(filtered_df)} liquid options across {len(selected_tickers)} underlyings")
        
        # For each ticker, ask LLM to select best options to monitor
        with db_conn() as conn:
            for ticker in selected_tickers:
                if not self.running:
                    break
                
                try:
                    self._analyze_and_monitor_ticker(conn, ticker, filtered_df, spot_prices.get(ticker, 0))
                except Exception as e:
                    logger.error(f"Error analyzing options for {ticker}: {e}")
                    continue
            
            conn.commit()

    def _analyze_and_monitor_ticker(self, conn, ticker: str, options_df, spot_price: float):
        """
        Use LLM to select best options for a specific ticker and update monitoring.
        
        Args:
            conn: Database connection
            ticker: Underlying ticker symbol
            options_df: DataFrame with all filtered options
            spot_price: Current spot price of underlying
        """
        if spot_price <= 0:
            logger.warning(f"No spot price for {ticker}, skipping options analysis")
            return
        
        # Prepare options data for LLM
        options_list = prepare_options_for_llm(options_df, ticker)
        
        if not options_list or len(options_list) < 2:
            logger.info(f"Insufficient options for {ticker} to warrant LLM analysis")
            return
        
        # Check LLM budget
        if not OPTIONS_BUDGET.acquire():
            logger.debug(f"Options LLM budget exhausted, skipping {ticker} this cycle")
            return
        
        # Load prompt
        prompt_config = get_prompt("options", "select_chains", force_reload=False)
        if not prompt_config:
            logger.error("Failed to load options selection prompt")
            return
        
        # Prepare options summary for LLM (limit to top 20 by volume to avoid token limits)
        sorted_options = sorted(options_list, key=lambda x: x['volume'] + x['open_interest'], reverse=True)
        top_options = sorted_options[:20]
        
        system = prompt_config["system"]
        user = format_prompt(
            prompt_config["user_template"],
            ticker=ticker,
            spot_price=spot_price,
            options_json=json.dumps(top_options, indent=2),
            max_allocation_pct=Config.OPTIONS_MAX_ALLOCATION_PCT,
            min_volume=Config.OPTIONS_MIN_VOLUME,
            min_open_interest=Config.OPTIONS_MIN_OPEN_INTEREST
        )
        
        # Ask LLM to select options
        logger.debug(f"Options LLM prompt for {ticker}:\nSYSTEM: {system[:200]}...\nUSER: {user[:500]}...")
        parsed, raw = llm_chat_json(system, user)
        self.stats["llm_calls"] += 1
        
        if raw:
            logger.debug(f"Options LLM raw response for {ticker} (length {len(raw)}): {raw[:1000]}...")
        
        if not parsed or "selected_options" not in parsed:
            logger.warning(f"LLM failed to return valid options selection for {ticker}")
            if raw:
                logger.error(f"Failed to parse LLM response: {raw}")
            return
        
        selected = parsed.get("selected_options", [])
        reasoning = parsed.get("overall_strategy", "No strategy provided")
        
        if not selected:
            logger.info(f"LLM selected no options for {ticker}")
            return
        
        logger.info(f"LLM selected {len(selected)} options for {ticker}: {reasoning}")
        
        # Update monitored options in database
        for opt in selected:
            try:
                contract = opt.get("contract", "")
                opt_type = opt.get("type", "")
                strike = float(opt.get("strike", 0))
                expiration = opt.get("expiration", "")
                reason = opt.get("reasoning", "")
                
                # Find full option data
                matching = [o for o in options_list if o["contract"] == contract]
                if not matching:
                    continue
                
                opt_data = matching[0]
                
                greeks = {
                    "delta": opt_data["delta"],
                    "gamma": opt_data["gamma"],
                    "theta": opt_data["theta"],
                    "vega": opt_data["vega"]
                }
                
                option_id = update_monitored_option(
                    conn, ticker, opt_type, strike, expiration, contract,
                    greeks, opt_data["volume"], opt_data["open_interest"],
                    opt_data["iv"], reason
                )
                
                # Store snapshot
                store_options_snapshot(conn, option_id, opt_data)
                
                # Create knowledge graph node and edge
                self._create_option_graph_node(conn, ticker, option_id, opt_type, strike, expiration, greeks)
                
                self.stats["options_monitored"] += 1
                
            except Exception as e:
                logger.error(f"Error updating monitored option {contract}: {e}")
                continue
        
        log_event(conn, "options", "analyzed", f"{ticker} selected={len(selected)} strategy={reasoning[:100]}")

    def _create_option_graph_node(
        self, conn, underlying: str, option_id: int, 
        option_type: str, strike: float, expiration: str, greeks: Dict
    ):
        """
        Create knowledge graph node for option and link to underlying.
        
        Args:
            conn: Database connection
            underlying: Ticker symbol of underlying
            option_id: Database ID of option
            option_type: 'Call' or 'Put'
            strike: Strike price
            expiration: Expiration date
            greeks: Dict with delta, gamma, theta, vega
        """
        # Node ID format: TICKER_C/P_STRIKE_EXP
        # Example: AAPL_C_180_2025-03-21
        exp_short = expiration.split('-')[1] + expiration.split('-')[2]  # MMDD
        node_id = f"{underlying}_{option_type[0]}{int(strike)}_{exp_short}"
        
        kind = "option_call" if option_type == "Call" else "option_put"
        label = f"{underlying} {strike}{option_type[0]} {exp_short}"
        desc = f"{option_type} option on {underlying}, strike ${strike}, exp {expiration}"
        
        # Create or update node
        conn.execute("""
            INSERT OR REPLACE INTO nodes(node_id, kind, label, description, score, last_touched)
            VALUES(?,?,?,?,?,?)
        """, (node_id, kind, label, desc, float(abs(greeks.get('delta', 0))), utc_now()))
        
        # Create edge from option to underlying
        eid = ensure_edge_id(conn, node_id, underlying)
        
        # Determine edge channel based on option type and delta
        delta = float(greeks.get('delta', 0))
        channel = "options_leverages" if option_type == "Call" else "options_hedges"
        strength = min(1.0, abs(delta) + 0.2)  # Boost strength slightly
        
        conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
        conn.execute(
            "INSERT INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)",
            (eid, channel, float(strength))
        )
        
        # Update edge weight
        w, top = edge_weight_top({channel: strength})
        conn.execute(
            "UPDATE edges SET weight=?, top_channel=?, last_assessed=? WHERE edge_id=?",
            (w, top, utc_now(), eid)
        )
        
        # Update degrees
        conn.execute("""
            UPDATE nodes SET degree = (
                SELECT COUNT(*) FROM edges 
                WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
            ) WHERE node_id IN (?,?)
        """, (node_id, underlying))


# Global instance
OPTIONS = OptionsWorker()
