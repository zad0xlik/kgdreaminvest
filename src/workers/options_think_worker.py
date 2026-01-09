"""
Options Think Worker: Makes trading decisions on monitored options.

Implements options trading decision-making system that:
- Reviews monitored options from database
- Analyzes current prices, Greeks, and portfolio state
- Uses LLM to generate BUY/SELL/HOLD decisions
- Executes trades with guard rails
- Runs independently from equity Think Worker

The worker runs continuously in a background thread when started.
"""

import json
import logging
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

from src.config import Config
from src.database import db_conn, log_event, portfolio_state
from src.llm import llm_chat_json
from src.llm.prompts import get_prompt, format_prompt
from src.llm.options_budget import OPTIONS_BUDGET
from src.market.options_fetcher import get_monitored_options_from_db
from src.portfolio.yahoo_options_trading import (
    get_options_positions, execute_option_buy, execute_option_sell,
    calculate_options_allocation, update_options_positions_mtm
)
from src.portfolio.alpaca_options_trading import (
    execute_option_buy_alpaca, execute_option_sell_alpaca
)
from src.utils import fmt_money, utc_now, jitter_sleep

logger = logging.getLogger("kginvest.options_think")


class OptionsThinkWorker:
    """
    Options trading decision-making worker.
    
    Each cycle:
    1. Fetches monitored options from database
    2. Gets latest pricing and Greeks
    3. Analyzes portfolio state and options allocation
    4. Asks LLM for trading decisions
    5. Executes approved trades with guard rails
    """
    
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {
            "cycles": 0,
            "decisions_made": 0,
            "trades_executed": 0,
            "trades_skipped": 0,
            "last_ts": None,
            "last_action": None,
            "last_error": None
        }
    
    def start(self):
        """Start the worker thread."""
        if not Config.OPTIONS_ENABLED:
            logger.info("OptionsThinkWorker disabled (OPTIONS_ENABLED=false)")
            return
        
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("OptionsThinkWorker started")
    
    def stop_now(self):
        """Stop the worker thread."""
        self.running = False
        self.stop.set()
        logger.info("OptionsThinkWorker stop signaled")
    
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
                logger.error(f"OptionsThinkWorker error: {e}")
                logger.debug(traceback.format_exc())
            
            # Run slightly slower than regular options worker
            interval = Config.OPTIONS_INTERVAL * 1.3  # ~8 minutes if options worker is ~6 min
            jitter_sleep(interval, self.stop)
    
    def step_once(self):
        """Execute one options trading decision cycle."""
        with db_conn() as conn:
            # Update mark-to-market on existing positions
            update_options_positions_mtm(conn)
            
            # Get monitored options
            monitored = get_monitored_options_from_db(conn)
            
            if not monitored:
                logger.info("No monitored options - skipping cycle")
                return
            
            # Get current positions
            positions = get_options_positions(conn)
            
            # Get portfolio state
            pf = portfolio_state(conn, prices={})
            
            # Calculate current options allocation
            options_alloc = calculate_options_allocation(conn, pf["equity"])
            
            logger.info(f"Options trading cycle: {len(monitored)} monitored, "
                       f"{len(positions)} positions, {options_alloc:.1f}% allocated")
            
            # Check if we should trade (budget check)
            if not OPTIONS_BUDGET.acquire():
                logger.debug("Options LLM budget exhausted - skipping cycle")
                return
            
            # Get LLM trading decisions
            decisions = self._llm_options_decisions(conn, monitored, positions, pf, options_alloc)
            
            if not decisions:
                logger.info("No options trading decisions from LLM")
                return
            
            # Execute decisions
            self._execute_options_decisions(conn, decisions, monitored, positions)
            
            conn.commit()
    
    def _llm_options_decisions(
        self,
        conn,
        monitored: List[Dict],
        positions: List[Dict],
        pf: Dict[str, Any],
        current_alloc: float
    ) -> List[Dict[str, Any]]:
        """
        Ask LLM for options trading decisions.
        
        Args:
            conn: Database connection
            monitored: List of monitored options with latest data
            positions: Current options positions
            pf: Portfolio state
            current_alloc: Current options allocation percentage
        
        Returns:
            List of decision dicts with action, option_id, contracts, reasoning
        """
        # Format monitored options for LLM
        options_summary = []
        for opt in monitored[:20]:  # Limit to top 20 to avoid token limits
            options_summary.append({
                "option_id": opt["option_id"],
                "underlying": opt["underlying"],
                "type": opt["option_type"],
                "strike": opt["strike"],
                "expiration": opt["expiration"],
                "contract": opt["contract_symbol"],
                "last_price": opt.get("last_price", 0.0),
                "delta": opt.get("delta", 0.0),
                "gamma": opt.get("gamma", 0.0),
                "theta": opt.get("theta", 0.0),
                "vega": opt.get("vega", 0.0),
                "iv": opt.get("implied_volatility", 0.0),
                "volume": opt.get("volume", 0),
                "open_interest": opt.get("open_interest", 0),
                "selection_reason": opt.get("selection_reason", "")
            })
        
        # Format current positions
        positions_summary = []
        for pos in positions:
            notional = pos["qty"] * pos["last_price"] * 100
            pl = (pos["last_price"] - pos["avg_cost"]) * pos["qty"] * 100
            positions_summary.append({
                "option_id": pos["option_id"],
                "underlying": pos["underlying"],
                "type": pos["option_type"],
                "strike": pos["strike"],
                "expiration": pos["expiration"],
                "qty": pos["qty"],
                "avg_cost": pos["avg_cost"],
                "last_price": pos["last_price"],
                "notional": notional,
                "unrealized_pl": pl,
                "delta": pos.get("delta", 0.0)
            })
        
        # Load prompt
        prompt_config = get_prompt("options", "trading_decisions", force_reload=False)
        if not prompt_config:
            logger.error("Failed to load options trading decisions prompt")
            return []
        
        system = prompt_config["system"]
        user = format_prompt(
            prompt_config["user_template"],
            monitored_options_json=json.dumps(options_summary, indent=2),
            positions_json=json.dumps(positions_summary, indent=2),
            cash=fmt_money(pf["cash"]),
            equity=fmt_money(pf["equity"]),
            current_options_alloc=f"{current_alloc:.1f}",
            max_options_alloc=Config.OPTIONS_MAX_ALLOCATION_PCT,
            max_single_option=Config.OPTIONS_MAX_SINGLE_OPTION_PCT,
            min_trade_notional=Config.OPTIONS_MIN_TRADE_NOTIONAL
        )
        
        logger.debug(f"Options Think LLM prompt:\nSYSTEM: {system[:200]}...\nUSER: {user[:500]}...")
        
        parsed, raw = llm_chat_json(system, user)
        self.stats["decisions_made"] += 1
        
        if raw:
            logger.debug(f"Options Think LLM response (length {len(raw)}): {raw[:1000]}...")
        
        if not parsed or "decisions" not in parsed:
            logger.warning("LLM failed to return valid options trading decisions")
            if raw:
                logger.error(f"Failed to parse LLM response: {raw}")
            return []
        
        decisions = parsed.get("decisions", [])
        strategy = parsed.get("overall_strategy", "No strategy provided")
        
        logger.info(f"LLM options strategy: {strategy}")
        logger.info(f"LLM returned {len(decisions)} options trading decisions")
        
        return decisions
    
    def _execute_options_decisions(
        self,
        conn,
        decisions: List[Dict[str, Any]],
        monitored: List[Dict],
        positions: List[Dict]
    ):
        """
        Execute options trading decisions with guard rails.
        
        Args:
            conn: Database connection
            decisions: List of LLM decisions
            monitored: All monitored options
            positions: Current positions
        """
        executed = 0
        skipped = 0
        
        # Create lookup dicts
        monitored_by_id = {opt["option_id"]: opt for opt in monitored}
        positions_by_id = {pos["option_id"]: pos for pos in positions}
        
        for decision in decisions:
            try:
                action = decision.get("action", "HOLD").upper()
                option_id = int(decision.get("option_id", 0))
                contracts = float(decision.get("contracts", 0))
                reasoning = decision.get("reasoning", "")
                
                if action == "HOLD" or contracts <= 0:
                    continue
                
                if option_id not in monitored_by_id:
                    logger.warning(f"Option {option_id} not in monitored list - skipping")
                    skipped += 1
                    continue
                
                opt = monitored_by_id[option_id]
                price = float(opt.get("last_price", 0.0))
                
                if price <= 0:
                    logger.warning(f"No price for option {option_id} - skipping")
                    skipped += 1
                    continue
                
                # Route to appropriate execution function
                if Config.BROKER_PROVIDER == "alpaca":
                    if action == "BUY":
                        success, msg = execute_option_buy_alpaca(
                            conn, option_id, contracts, price, reasoning
                        )
                    elif action == "SELL":
                        success, msg = execute_option_sell_alpaca(
                            conn, option_id, contracts, price, reasoning
                        )
                    else:
                        continue
                else:
                    # Paper trading
                    if action == "BUY":
                        success, msg = execute_option_buy(
                            conn, option_id, contracts, price, reasoning
                        )
                    elif action == "SELL":
                        success, msg = execute_option_sell(
                            conn, option_id, contracts, price, reasoning
                        )
                    else:
                        continue
                
                if success:
                    executed += 1
                    symbol = f"{opt['underlying']} {opt['strike']}{opt['option_type'][0]} {opt['expiration']}"
                    logger.info(f"✅ Options {action}: {contracts}x {symbol} - {msg}")
                else:
                    skipped += 1
                    logger.info(f"⏭️  Options {action} skipped: {msg}")
                
            except Exception as e:
                logger.error(f"Error executing options decision: {e}")
                skipped += 1
                continue
        
        self.stats["trades_executed"] += executed
        self.stats["trades_skipped"] += skipped
        
        logger.info(f"Options trading cycle complete: {executed} executed, {skipped} skipped")
        
        log_event(
            conn, "options_think", "decisions",
            f"executed={executed} skipped={skipped} total={len(decisions)}"
        )


# Global instance
OPTIONS_THINK = OptionsThinkWorker()
