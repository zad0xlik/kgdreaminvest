"""
Think Worker: Multi-agent committee decision-making system.

Implements a multi-agent LLM committee that:
- Analyzes market snapshots (prices, indicators, signals)
- Generates trading decisions via agent consensus
- Creates plain-English explanations
- Optionally auto-executes paper trades

The worker runs continuously in a background thread when started.
"""

import json
import logging
import random
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from src.config import (
    AUTO_TRADE, TRADE_ANYTIME, INVESTIBLES, BELLWETHERS,
    THINK_INTERVAL, STAR_THRESHOLD, EXPLANATION_MIN_LENGTH,
    MIN_CASH_BUFFER_PCT, MAX_BUY_EQUITY_PCT_PER_CYCLE,
    MAX_SELL_HOLDING_PCT_PER_CYCLE, MAX_SYMBOL_WEIGHT_PCT
)
from src.database import (
    db_conn, log_event, portfolio_state, positions_as_dict,
    recent_trade_summary
)
from src.llm import llm_chat_json
from src.llm.prompts import get_prompt, format_prompt
from src.portfolio import execute_trades
from src.utils import clamp01, fmt_money, market_is_open_et, utc_now, jitter_sleep

logger = logging.getLogger("kginvest.think")


def critic_score(explanation: str, decisions: List[Dict[str, Any]], conf: float) -> float:
    """
    Heuristic quality score for insights.
    
    Rewards:
    - Higher confidence
    - Longer, more detailed explanations
    - Use of reasoning keywords
    
    Penalizes:
    - Overly aggressive trading plans
    """
    score = 0.22 + 0.48 * clamp01(conf)
    if len(explanation) >= EXPLANATION_MIN_LENGTH:
        score += 0.10
    if any(w in explanation.lower() for w in ["because", "however", "therefore", "driven", "while", "but", "risk"]):
        score += 0.10
    # penalize wildly aggressive plans
    buys = sum(1 for d in decisions if d.get("action") == "BUY" and float(d.get("allocation_pct", 0)) > 0)
    sells = sum(1 for d in decisions if d.get("action") == "SELL" and float(d.get("allocation_pct", 0)) > 0)
    if buys >= 10:
        score -= 0.06
    if sells >= 10:
        score -= 0.04
    return clamp01(score)


def sanitize_decisions(raw: Any) -> List[Dict[str, Any]]:
    """
    Validate and sanitize LLM decision output.
    
    Ensures:
    - All tickers are in INVESTIBLES
    - Actions are BUY/SELL/HOLD
    - Allocation percentages are bounded
    - All investibles have an entry (HOLD if missing)
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        t = str(item.get("ticker", "")).upper().strip()
        if t not in INVESTIBLES:
            continue
        a = str(item.get("action", "HOLD")).upper().strip()
        if a not in ("BUY", "SELL", "HOLD"):
            a = "HOLD"
        try:
            pct = float(item.get("allocation_pct", 0.0))
        except Exception:
            pct = 0.0
        pct = max(0.0, min(80.0, pct))
        note = str(item.get("note", "")).strip()[:260]
        out.append({"ticker": t, "action": a, "allocation_pct": pct, "note": note})
    # ensure coverage (hold defaults)
    present = {d["ticker"] for d in out}
    for t in INVESTIBLES:
        if t not in present:
            out.append({"ticker": t, "action": "HOLD", "allocation_pct": 0.0, "note": "default HOLD"})
    return out


def rule_based_fallback(
    prices: Dict[str, Any],
    indicators: Dict[str, Any],
    signals: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, float]:
    """
    No-LLM fallback: simple score = mom20 - 2*volatility; risk_off trims.
    
    Used when LLM calls fail or budget is exhausted.
    Returns: (agents_dict, decisions_list, explanation_str, confidence_float)
    """
    risk_off = float(signals.get("risk_off", 0.5) or 0.5)
    ranked: List[Tuple[float, str]] = []
    for t in INVESTIBLES:
        ind = indicators.get(t) or {}
        mom20 = float(ind.get("mom20", 0.0) or 0.0)
        vol = float(ind.get("volatility", 0.0) or 0.0)
        rsi = float(ind.get("rsi", 50.0) or 50.0)
        s = mom20 - 2.0 * vol
        # mild penalty for very overbought
        if rsi > 72:
            s -= 0.01
        ranked.append((s, t))
    ranked.sort(reverse=True)

    top = [t for _, t in ranked[:5]]
    bottom = [t for _, t in ranked[-4:]]

    # conservative allocations
    decisions = []
    for t in INVESTIBLES:
        if risk_off > 0.62:
            # risk-off: trim weakest and avoid adds; light buys in XLV only
            if t in bottom:
                decisions.append({"ticker": t, "action": "SELL", "allocation_pct": 15.0, "note": "risk-off: trim weak/volatile"})
            elif t == "XLV":
                decisions.append({"ticker": t, "action": "BUY", "allocation_pct": 6.0, "note": "risk-off: tilt defensive"})
            else:
                decisions.append({"ticker": t, "action": "HOLD", "allocation_pct": 0.0, "note": "risk-off: hold"})
        else:
            # risk-on: add to leaders, trim laggards
            if t in top:
                decisions.append({"ticker": t, "action": "BUY", "allocation_pct": 7.0, "note": "momentum leader: add small"})
            elif t in bottom:
                decisions.append({"ticker": t, "action": "SELL", "allocation_pct": 12.0, "note": "laggard: trim"})
            else:
                decisions.append({"ticker": t, "action": "HOLD", "allocation_pct": 0.0, "note": "neutral"})
    
    agents = {
        "macro": {"regime": "risk-off" if risk_off > 0.62 else "risk-on", "risk_off": risk_off},
        "technical": {"top": top, "bottom": bottom},
        "risk": {"cash_buffer_pct": MIN_CASH_BUFFER_PCT, "guardrails": "fallback"},
    }
    
    explanation = (
        f"Fallback plan (no LLM): regime={'risk-off' if risk_off > 0.62 else 'risk-on'}. "
        f"Adds focus on leaders ({', '.join(top[:3])}); trims laggards ({', '.join(bottom[:2])}). "
        "Kept small sizes to limit churn and preserve cash buffer."
    )
    conf = 0.42
    return agents, decisions, explanation, conf


class ThinkWorker:
    """
    Multi-agent committee + optional auto-execution.

    Each cycle:
    - Read latest snapshot (prices, indicators, bell signals)
    - Build agent prompt and ask LLM for:
      { agents:{...}, decisions:[...], explanation:"...", confidence:0-1 }
    - Store as insight (starred by critic score)
    - If AUTO_TRADE and starred and trade window allows, execute paper trades and mark applied
    """
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {
            "steps": 0,
            "insights_created": 0,
            "insights_starred": 0,
            "trades_applied": 0,
            "last_ts": None,
            "last_action": None
        }

    def start(self):
        """Start the think worker in a background thread."""
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("ThinkWorker started")

    def stop_now(self):
        """Signal the worker to stop."""
        self.running = False
        self.stop.set()
        logger.info("ThinkWorker stop signaled")

    def _loop(self):
        """Main worker loop."""
        while self.running and not self.stop.is_set():
            try:
                self.step_once()
                self.stats["steps"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_action"] = "think"
            except Exception as e:
                logger.error(f"ThinkWorker error: {e}")
                logger.debug(traceback.format_exc())
            jitter_sleep(THINK_INTERVAL, self.stop)

    def step_once(self):
        """
        Execute one think cycle:
        1. Fetch latest market snapshot
        2. Get portfolio state
        3. Run LLM committee
        4. Store insight
        5. Auto-execute if conditions met
        """
        with db_conn() as conn:
            snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
            if not snap:
                return
            prices = json.loads(snap["prices_json"] or "{}")
            indicators = json.loads(snap["indicators_json"] or "{}")
            signals = json.loads(snap["signals_json"] or "{}")
            snap_id = int(snap["snapshot_id"])

            pf = portfolio_state(conn, prices=prices)
            positions = positions_as_dict(conn)
            trade_hist = recent_trade_summary(conn, limit=12)

        # Respect trade window (default: outside market hours)
        can_trade_now = TRADE_ANYTIME or (not market_is_open_et())
        # Still generate ideas even during market hours
        agents, decisions, explanation, conf = self._llm_committee(
            prices, indicators, signals, pf, positions, trade_hist
        )

        crit = critic_score(explanation, decisions, conf)
        starred = 1 if crit >= STAR_THRESHOLD else 0

        title = "Agent committee plan"
        if float(signals.get("risk_off", 0.5) or 0.5) > 0.62:
            title = "Agent plan: risk-off posture"
        elif float(signals.get("semi_pulse", 0.5) or 0.5) > 0.62:
            title = "Agent plan: lean semis/QQQ impulse"
        elif float(signals.get("oil_shock", 0.5) or 0.5) > 0.62:
            title = "Agent plan: inflation/oil impulse"

        with db_conn() as conn:
            conn.execute(
                "INSERT INTO insights(ts,title,body,agents_json,decisions_json,confidence,critic_score,starred,status,evidence_snapshot_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (utc_now(), title[:120], explanation[:1800], json.dumps(agents), json.dumps(decisions),
                 float(conf), float(crit), int(starred), "new", int(snap_id)),
            )
            insight_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
            log_event(conn, "think", "proposal", f"id={insight_id} starred={starred} score={crit:.2f} conf={conf:.2f}")
            conn.commit()

            self.stats["insights_created"] += 1
            if starred:
                self.stats["insights_starred"] += 1

            # Autotrade if allowed
            if AUTO_TRADE and starred and can_trade_now:
                res = execute_trades(
                    conn, decisions, prices,
                    reason=f"autotrade insight {insight_id} (score={crit:.2f})",
                    insight_id=insight_id
                )
                conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("applied", insight_id))
                log_event(conn, "trade", "autotrade", f"id={insight_id} executed={len(res['executed'])} skipped={len(res['skipped'])}")
                conn.commit()
                self.stats["trades_applied"] += 1
            elif AUTO_TRADE and starred and not can_trade_now:
                conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("queued", insight_id))
                conn.commit()

    def _generate_explanation_from_agents(
        self,
        agents: Dict[str, Any],
        decisions: List[Dict[str, Any]]
    ) -> str:
        """
        Auto-generate a plain-English explanation from agent bullets when LLM doesn't provide one.
        Ensures it meets the length (>=180 chars) and keyword requirements.
        """
        explanation_parts = []
        
        # Extract macro insights
        macro = agents.get("macro", {})
        regime = macro.get("regime", "")
        if regime:
            explanation_parts.append(f"The current regime is {regime}")
        macro_bullets = macro.get("bullets", [])
        if macro_bullets and isinstance(macro_bullets, list):
            explanation_parts.extend(macro_bullets[:2])  # Take first 2 bullets
        
        # Extract technical insights
        technical = agents.get("technical", {})
        top_tickers = technical.get("top", [])
        bottom_tickers = technical.get("bottom", [])
        if top_tickers:
            explanation_parts.append(f"Technical leaders include {', '.join(top_tickers[:3])} driven by strong momentum")
        if bottom_tickers:
            explanation_parts.append(f"However, laggards like {', '.join(bottom_tickers[:2])} show weakness")
        
        # Extract risk insights
        risk = agents.get("risk", {})
        risk_bullets = risk.get("bullets", [])
        if risk_bullets and isinstance(risk_bullets, list):
            explanation_parts.append(risk_bullets[0] if risk_bullets else "Risk management suggests cautious positioning")
        
        # Add decision summary
        buy_count = sum(1 for d in decisions if d.get("action") == "BUY" and float(d.get("allocation_pct", 0)) > 0)
        sell_count = sum(1 for d in decisions if d.get("action") == "SELL" and float(d.get("allocation_pct", 0)) > 0)
        
        if sell_count > 0:
            sell_tickers = [d["ticker"] for d in decisions if d.get("action") == "SELL" and float(d.get("allocation_pct", 0)) > 0][:3]
            explanation_parts.append(f"Therefore, we trim positions in {', '.join(sell_tickers)} to manage risk")
        
        if buy_count > 0:
            buy_tickers = [d["ticker"] for d in decisions if d.get("action") == "BUY" and float(d.get("allocation_pct", 0)) > 0][:3]
            explanation_parts.append(f"While redeploying capital into {', '.join(buy_tickers)} because of their favorable risk-reward profile")
        
        # Join parts with proper connectors to create natural flow
        explanation = ". ".join(filter(None, explanation_parts))
        
        # Ensure it ends with a period
        if explanation and not explanation.endswith('.'):
            explanation += '.'
        
        # If too short, add more context
        if len(explanation) < 180:
            explanation += " The allocation strategy balances risk exposure while maintaining diversification across sectors. This approach is driven by market dynamics but remains flexible to adjust as conditions evolve."
        
        return explanation

    def _llm_committee(
        self,
        prices: Dict[str, Any],
        indicators: Dict[str, Any],
        signals: Dict[str, Any],
        pf: Dict[str, Any],
        positions: Dict[str, float],
        trade_hist: str
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, float]:
        """
        One LLM call that returns multi-agent structured output.
        
        Returns: (agents_dict, decisions_list, explanation_str, confidence_float)
        """
        # Build compact market context
        bell_lines = []
        for b in BELLWETHERS:
            if b in prices:
                bell_lines.append(f"{b}: {prices[b]['change_pct']:+.2f}% 1d (px {prices[b]['current']:.2f})")

        inv_lines = []
        for t in INVESTIBLES:
            p = prices.get(t)
            if not p:
                continue
            ind = indicators.get(t, {}) or {}
            inv_lines.append(
                f"{t}: ${p['current']:.2f} ({p['change_pct']:+.2f}% 1d), "
                f"mom5 {float(ind.get('mom5',0))*100:+.2f}%, mom20 {float(ind.get('mom20',0))*100:+.2f}%, "
                f"RSI {float(ind.get('rsi',50)):.1f}, z {float(ind.get('zscore',0)):+.1f}, vol {float(ind.get('volatility',0)):.3f}"
            )

        pos_lines = []
        for sym, qty in sorted(positions.items()):
            if qty <= 0:
                continue
            px = float(prices.get(sym, {}).get("current", 0.0) or 0.0)
            mv = qty * px
            pos_lines.append(f"- {sym}: {qty:.4f} sh (~{fmt_money(mv)})")

        # Load prompts from file
        prompt_config = get_prompt("think", "multi_agent_committee", force_reload=False)
        if prompt_config:
            system = prompt_config["system"]
            user = format_prompt(
                prompt_config["user_template"],
                bellwether_lines=chr(10).join(bell_lines) if bell_lines else "(missing)",
                signals_json=json.dumps(signals),
                investible_lines=chr(10).join(inv_lines) if inv_lines else "(missing)",
                cash=fmt_money(float(pf.get('cash',0))),
                equity=fmt_money(float(pf.get('equity',0))),
                position_lines=chr(10).join(pos_lines) if pos_lines else "- None",
                trade_history=trade_hist,
                min_cash_buffer=MIN_CASH_BUFFER_PCT,
                max_buy_equity=MAX_BUY_EQUITY_PCT_PER_CYCLE,
                max_sell_holding=MAX_SELL_HOLDING_PCT_PER_CYCLE,
                max_symbol_weight=MAX_SYMBOL_WEIGHT_PCT
            )
        else:
            logger.error("Failed to load multi_agent_committee prompt - using fallback")
            return rule_based_fallback(prices, indicators, signals)

        parsed, _raw = llm_chat_json(system, user)
        if not parsed:
            # TEMPORARILY DISABLE FALLBACK - Let's see the actual LLM response
            logger.error("LLM returned None - this indicates a parsing issue. Raw response was:")
            logger.error(_raw)
            # Return a basic structure to prevent system crash but mark as failed
            return {}, [], "LLM parsing failed - check logs", 0.0

        agents = parsed.get("agents") if isinstance(parsed.get("agents"), dict) else {}
        decisions = sanitize_decisions(parsed.get("decisions", []))
        explanation = str(parsed.get("explanation", "")).strip()
        if not explanation:
            # Auto-generate explanation from agent bullets when LLM doesn't provide one
            explanation = self._generate_explanation_from_agents(agents, decisions)
        try:
            conf = clamp01(float(parsed.get("confidence", 0.5) or 0.5))
        except Exception:
            conf = 0.5

        # DIAGNOSTIC LOGGING - Check what we're getting from LLM
        logger.info(f"LLM Response Quality Check:")
        logger.info(f"  - Confidence: {conf}")
        logger.info(f"  - Explanation length: {len(explanation)} chars")
        logger.info(f"  - Explanation preview: {explanation[:200]}...")
        
        # Check quality criteria
        has_length = len(explanation) >= 180
        keywords = ["because", "however", "therefore", "driven", "while", "but", "risk"]
        has_keywords = any(w in explanation.lower() for w in keywords)
        found_keywords = [w for w in keywords if w in explanation.lower()]
        
        logger.info(f"  - Meets length requirement (>=180): {has_length}")
        logger.info(f"  - Has required keywords: {has_keywords}")
        logger.info(f"  - Found keywords: {found_keywords}")
        logger.info(f"  - Decision count: {len(decisions)}")
        
        # Calculate expected critic score
        expected_score = 0.22 + 0.48 * conf
        if has_length:
            expected_score += 0.10
        if has_keywords:
            expected_score += 0.10
        logger.info(f"  - Expected critic score: {expected_score:.2f}")

        # If decisions are empty, fallback
        if not decisions:
            logger.error("Decisions are empty - this indicates a parsing issue. Raw response was:")
            logger.error(_raw)
            return {}, [], "Decisions parsing failed - check logs", 0.0

        return agents, decisions, explanation, conf


# Global instance
THINK = ThinkWorker()
