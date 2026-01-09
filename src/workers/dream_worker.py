"""Dream Worker - Maintains knowledge graph edges with correlations and LLM."""
import json
import logging
import random
import threading
import traceback
from typing import Optional, Dict, List, Tuple

from src.config import Config
from src.database import db_conn, log_event, ensure_edge_id, edge_weight_top
from src.knowledge_graph.correlation import (
    corr, iv_corr, delta_alignment, vega_similarity, spread_score
)
from src.llm import llm_chat_json
from src.llm.prompts import get_prompt, format_prompt
from src.utils import utc_now, jitter_sleep

logger = logging.getLogger("kginvest")


class DreamWorker:
    """
    Light knowledge graph maintenance worker.
    
    Each cycle:
    1. Picks a random (investible, bellwether) pair
    2. Computes correlation from price history
    3. Sets heuristic channels based on correlation
    4. Optionally asks LLM to label relationship channels
    5. Updates edge weights and node metadata
    """
    
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {
            "steps": 0,
            "edges_updated": 0,
            "last_ts": None,
            "last_action": None
        }

    def start(self):
        """Start the worker thread."""
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("DreamWorker started")

    def stop_now(self):
        """Stop the worker thread."""
        self.running = False
        self.stop.set()
        logger.info("DreamWorker stop signaled")

    def _loop(self):
        """Main worker loop."""
        while self.running and not self.stop.is_set():
            try:
                # Randomly choose assessment type (weighted)
                # 60% investible-bellwether, 20% option-bellwether, 20% option-option
                r = random.random()
                
                if r < 0.60:
                    self._assess_pair()
                    action = "assess_pair"
                elif r < 0.80 and Config.OPTIONS_ENABLED:
                    self._assess_option_bellwether_pair()
                    action = "assess_option_bellwether"
                elif Config.OPTIONS_ENABLED:
                    self._assess_option_option_pair()
                    action = "assess_option_option"
                else:
                    self._assess_pair()
                    action = "assess_pair"
                
                self.stats["steps"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_action"] = action
            except Exception as e:
                logger.error(f"DreamWorker error: {e}")
                logger.debug(traceback.format_exc())
            
            jitter_sleep(Config.DREAM_INTERVAL, self.stop)

    def _assess_pair(self):
        """Assess one random (investible, bellwether) pair."""
        inv = random.choice(Config.INVESTIBLES)
        bw = random.choice(Config.BELLWETHERS)

        with db_conn() as conn:
            # Get latest snapshot for price history
            snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
            if not snap:
                return
            
            prices = json.loads(snap["prices_json"] or "{}")
            a = prices.get(inv, {}).get("history") or []
            b = prices.get(bw, {}).get("history") or []
            c = corr(a, b)

            # Heuristic channel set from correlation sign/magnitude
            channels: Dict[str, float] = {}
            mag = abs(c)
            
            if mag >= 0.25:
                if c > 0:
                    channels["correlates"] = float(min(1.0, 0.35 + 0.75 * mag))
                else:
                    channels["inverse_correlates"] = float(min(1.0, 0.35 + 0.75 * mag))
            
            # Add a mild "liquidity_coupled" for equities vs SPY/QQQ
            if bw in ("SPY", "QQQ") and mag >= 0.15:
                channels["liquidity_coupled"] = float(min(1.0, 0.25 + 0.8 * mag))

            # Occasionally let LLM annotate directionality / narrative channel
            use_llm = random.random() < 0.30
            note = f"corr={c:+.2f} (heuristic)"
            
            if use_llm:
                # Load prompts from file
                prompt_config = get_prompt("dream", "edge_relationship", force_reload=False)
                if prompt_config:
                    system = prompt_config["system"]
                    user_prompt = format_prompt(
                        prompt_config["user_template"],
                        node_a=inv,
                        node_b=bw,
                        correlation=c
                    )
                    parsed, _raw = llm_chat_json(system, user_prompt)
                else:
                    logger.warning("Failed to load edge_relationship prompt")
                    parsed = None
                    _raw = None
                if parsed and isinstance(parsed.get("channels"), dict):
                    clean: Dict[str, float] = {}
                    for k, v in parsed["channels"].items():
                        try:
                            s = float(v)
                            if 0.10 <= s <= 1.0:
                                clean[str(k)] = float(s)
                        except Exception:
                            continue
                    if clean:
                        channels = clean
                    note = str(parsed.get("note", note))[:160]

            # Update edge in database
            eid = ensure_edge_id(conn, inv, bw)
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            
            for ch, s in channels.items():
                conn.execute(
                    "INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)",
                    (eid, ch, float(s))
                )
            
            w, top = edge_weight_top(channels)
            conn.execute(
                "UPDATE edges SET weight=?, top_channel=?, last_assessed=?, "
                "assessment_count=assessment_count+1 WHERE edge_id=?",
                (w, top, utc_now(), eid)
            )
            
            # Touch the nodes
            conn.execute(
                "UPDATE nodes SET last_touched=?, score=score+0.005 WHERE node_id IN (?,?)",
                (utc_now(), inv, bw)
            )
            
            # Update node degrees
            conn.execute("""
              UPDATE nodes SET degree = (
                SELECT COUNT(*) FROM edges WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
              ) WHERE node_id IN (?,?)
            """, (inv, bw))

            log_event(conn, "dream", "assess_pair", f"{inv}<->{bw} {note}")
            conn.commit()
            self.stats["edges_updated"] += 1

    def _assess_option_bellwether_pair(self):
        """Assess one random (option, bellwether) pair."""
        with db_conn() as conn:
            # Get a random monitored option
            opt_row = conn.execute("""
                SELECT om.*, n.node_id, n.kind 
                FROM options_monitored om
                JOIN nodes n ON (n.node_id LIKE om.underlying || '%' AND n.kind IN ('option_call', 'option_put'))
                WHERE om.enabled=1
                ORDER BY RANDOM() LIMIT 1
            """).fetchone()
            
            if not opt_row:
                return  # No options to assess
            
            opt_node = opt_row["node_id"]
            opt_type = "option_call" if opt_row["option_type"] == "Call" else "option_put"
            underlying = opt_row["underlying"]
            
            # Pick a random bellwether
            bw = random.choice(Config.BELLWETHERS)
            
            # Get option price/IV history from snapshots
            snapshots = conn.execute("""
                SELECT last, implied_volatility 
                FROM options_snapshots 
                WHERE option_id=?
                ORDER BY snapshot_id DESC LIMIT 30
            """, (opt_row["option_id"],)).fetchall()
            
            if len(snapshots) < 10:
                return  # Insufficient history
            
            opt_prices = [s["last"] for s in snapshots if s["last"]]
            opt_ivs = [s["implied_volatility"] for s in snapshots if s["implied_volatility"]]
            
            # Get bellwether price history
            snap = conn.execute("SELECT prices_json FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
            if not snap:
                return
            
            prices = json.loads(snap["prices_json"] or "{}")
            bw_prices = prices.get(bw, {}).get("history") or []
            
            # Compute correlations
            price_corr = corr(opt_prices, bw_prices) if len(opt_prices) >= 20 else 0.0
            
            # Heuristic channels
            channels: Dict[str, float] = {}
            
            # Special handling for VIX with options
            if bw == "^VIX":
                # Puts should correlate with VIX, calls inverse
                if opt_type == "option_put" and price_corr > 0.20:
                    channels["options_hedges"] = float(min(0.85, 0.50 + abs(price_corr)))
                    channels["vol_regime_coupled"] = float(min(0.80, 0.45 + abs(price_corr)))
                elif opt_type == "option_call" and price_corr < -0.15:
                    channels["inverse_correlates"] = float(min(0.75, 0.40 + abs(price_corr)))
            
            # For SPY/QQQ - sector correlation
            elif bw in ("SPY", "QQQ") and abs(price_corr) > 0.25:
                if price_corr > 0:
                    channels["correlates"] = float(min(0.80, 0.35 + abs(price_corr)))
                else:
                    channels["inverse_correlates"] = float(min(0.75, 0.30 + abs(price_corr)))
                channels["vol_regime_coupled"] = 0.60
            
            if not channels:
                return  # No significant relationship
            
            # Occasionally use LLM (40% for options - higher than normal)
            use_llm = random.random() < 0.40
            note = f"price_corr={price_corr:+.2f}"
            
            if use_llm:
                prompt_config = get_prompt("dream", "option_edge_relationship", force_reload=False)
                if prompt_config:
                    context = f"Price correlation: {price_corr:+.2f}\n"
                    context += f"Option type: {opt_row['option_type']}\n"
                    context += f"Delta: {opt_row['delta']}, Vega: {opt_row['vega']}\n"
                    context += f"Bellwether: {bw}"
                    
                    system = prompt_config["system"]
                    user_prompt = format_prompt(
                        prompt_config["user_template"],
                        node_a=opt_node,
                        node_a_type=opt_type,
                        node_b=bw,
                        node_b_type="bellwether",
                        context=context
                    )
                    parsed, _raw = llm_chat_json(system, user_prompt)
                    
                    if parsed and isinstance(parsed.get("channels"), dict):
                        clean: Dict[str, float] = {}
                        for k, v in parsed["channels"].items():
                            try:
                                s = float(v)
                                if 0.10 <= s <= 1.0:
                                    clean[str(k)] = float(s)
                            except Exception:
                                continue
                        if clean:
                            channels = clean
                        note = str(parsed.get("note", note))[:160]
            
            # Update edge
            eid = ensure_edge_id(conn, opt_node, bw)
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            
            for ch, s in channels.items():
                conn.execute(
                    "INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)",
                    (eid, ch, float(s))
                )
            
            w, top = edge_weight_top(channels)
            conn.execute(
                "UPDATE edges SET weight=?, top_channel=?, last_assessed=?, "
                "assessment_count=assessment_count+1 WHERE edge_id=?",
                (w, top, utc_now(), eid)
            )
            
            conn.execute(
                "UPDATE nodes SET last_touched=?, score=score+0.005 WHERE node_id IN (?,?)",
                (utc_now(), opt_node, bw)
            )
            
            conn.execute("""
              UPDATE nodes SET degree = (
                SELECT COUNT(*) FROM edges WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
              ) WHERE node_id IN (?,?)
            """, (opt_node, bw))
            
            log_event(conn, "dream", "assess_option_bw", f"{opt_node}<->{bw} {note}")
            conn.commit()
            self.stats["edges_updated"] += 1

    def _assess_option_option_pair(self):
        """Assess relationship between two monitored options."""
        with db_conn() as conn:
            # Get two random monitored options
            opts = conn.execute("""
                SELECT om.*, n.node_id 
                FROM options_monitored om
                JOIN nodes n ON (n.node_id LIKE om.underlying || '%')
                WHERE om.enabled=1 AND n.kind IN ('option_call', 'option_put')
                ORDER BY RANDOM() LIMIT 2
            """).fetchall()
            
            if len(opts) < 2:
                return  # Need at least 2 options
            
            opt_a = opts[0]
            opt_b = opts[1]
            node_a = opt_a["node_id"]
            node_b = opt_b["node_id"]
            
            # Don't assess if already connected (check existing edge)
            existing = conn.execute(
                "SELECT edge_id FROM edges WHERE (node_a=? AND node_b=?) OR (node_a=? AND node_b=?)",
                (node_a, node_b, node_b, node_a)
            ).fetchone()
            
            # Skip if recently assessed (avoid over-assessment)
            if existing:
                last_assessed = conn.execute(
                    "SELECT last_assessed FROM edges WHERE edge_id=?", (existing["edge_id"],)
                ).fetchone()["last_assessed"]
                
                if last_assessed:
                    # Skip if assessed in last hour (this is expensive)
                    return
            
            # Get IV histories
            snaps_a = conn.execute("""
                SELECT last, implied_volatility, delta, vega 
                FROM options_snapshots 
                WHERE option_id=?
                ORDER BY snapshot_id DESC LIMIT 30
            """, (opt_a["option_id"],)).fetchall()
            
            snaps_b = conn.execute("""
                SELECT last, implied_volatility, delta, vega
                FROM options_snapshots 
                WHERE option_id=?
                ORDER BY snapshot_id DESC LIMIT 30
            """, (opt_b["option_id"],)).fetchall()
            
            if len(snaps_a) < 10 or len(snaps_b) < 10:
                return
            
            # Extract data
            prices_a = [s["last"] for s in snaps_a if s["last"]]
            prices_b = [s["last"] for s in snaps_b if s["last"]]
            ivs_a = [s["implied_volatility"] for s in snaps_a if s["implied_volatility"]]
            ivs_b = [s["implied_volatility"] for s in snaps_b if s["implied_volatility"]]
            
            # Correlations
            price_corr = corr(prices_a, prices_b) if len(prices_a) >= 20 else 0.0
            iv_correlation = iv_corr(ivs_a, ivs_b)
            
            # Greeks analysis
            delta_align = delta_alignment(opt_a["delta"] or 0, opt_b["delta"] or 0)
            vega_sim = vega_similarity(opt_a["vega"] or 0, opt_b["vega"] or 0)
            
            # Spread detection
            same_underlying = opt_a["underlying"] == opt_b["underlying"]
            strategy, strat_score = spread_score(
                opt_a["option_type"], opt_b["option_type"],
                opt_a["strike"], opt_b["strike"],
                opt_a["expiration"], opt_b["expiration"]
            )
            
            # Build channels
            channels: Dict[str, float] = {}
            
            # Strong IV correlation
            if abs(iv_correlation) > 0.50:
                if iv_correlation > 0:
                    channels["iv_correlates"] = float(min(0.85, 0.40 + abs(iv_correlation) * 0.6))
                else:
                    channels["iv_inverse"] = float(min(0.80, 0.35 + abs(iv_correlation) * 0.6))
                channels["vol_regime_coupled"] = float(min(0.75, 0.30 + abs(iv_correlation) * 0.5))
            
            # Spread strategy detected
            if strategy != "none" and strat_score > 0.60:
                if strategy == "collar":
                    channels["collar_strategy"] = float(strat_score)
                elif strategy in ("vertical", "horizontal", "diagonal"):
                    channels["spread_strategy"] = float(strat_score)
            
            # Delta flow (directional alignment)
            if delta_align > 0.75 and not same_underlying:
                channels["delta_flow"] = float(min(0.75, delta_align))
                
            # Cross-underlying hedge (opposite deltas on different underlyings)
            if delta_align < 0.30 and not same_underlying and abs(price_corr) > 0.20:
                channels["cross_underlying_hedge"] = float(min(0.80, 0.50 + abs(price_corr) * 0.4))
            
            # Vega exposure (shared vol sensitivity)
            if vega_sim > 0.70:
                channels["vega_exposure"] = float(min(0.75, vega_sim))
            
            if not channels:
                return  # No significant relationship
            
            # Use LLM 50% of time for option-option (most complex)
            use_llm = random.random() < 0.50
            note = f"IV_corr={iv_correlation:+.2f} delta_align={delta_align:.2f} {strategy}"
            
            if use_llm:
                prompt_config = get_prompt("dream", "option_edge_relationship", force_reload=False)
                if prompt_config:
                    context = f"Price correlation: {price_corr:+.2f}\n"
                    context += f"IV correlation: {iv_correlation:+.2f}\n"
                    context += f"Delta alignment: {delta_align:.2f}\n"
                    context += f"Vega similarity: {vega_sim:.2f}\n"
                    context += f"Same underlying: {same_underlying}\n"
                    context += f"Strategy fit: {strategy} (score: {strat_score:.2f})\n"
                    context += f"Option A: {opt_a['underlying']} {opt_a['option_type']} ${opt_a['strike']} {opt_a['expiration']}\n"
                    context += f"Option B: {opt_b['underlying']} {opt_b['option_type']} ${opt_b['strike']} {opt_b['expiration']}"
                    
                    system = prompt_config["system"]
                    user_prompt = format_prompt(
                        prompt_config["user_template"],
                        node_a=node_a,
                        node_a_type=opt_a["option_type"].lower(),
                        node_b=node_b,
                        node_b_type=opt_b["option_type"].lower(),
                        context=context
                    )
                    parsed, _raw = llm_chat_json(system, user_prompt)
                    
                    if parsed and isinstance(parsed.get("channels"), dict):
                        clean: Dict[str, float] = {}
                        for k, v in parsed["channels"].items():
                            try:
                                s = float(v)
                                if 0.10 <= s <= 1.0:
                                    clean[str(k)] = float(s)
                            except Exception:
                                continue
                        if clean:
                            channels = clean
                        note = str(parsed.get("note", note))[:160]
            
            # Update edge
            eid = ensure_edge_id(conn, node_a, node_b)
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            
            for ch, s in channels.items():
                conn.execute(
                    "INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)",
                    (eid, ch, float(s))
                )
            
            w, top = edge_weight_top(channels)
            conn.execute(
                "UPDATE edges SET weight=?, top_channel=?, last_assessed=?, "
                "assessment_count=assessment_count+1 WHERE edge_id=?",
                (w, top, utc_now(), eid)
            )
            
            conn.execute(
                "UPDATE nodes SET last_touched=?, score=score+0.010 WHERE node_id IN (?,?)",
                (utc_now(), node_a, node_b)
            )
            
            conn.execute("""
              UPDATE nodes SET degree = (
                SELECT COUNT(*) FROM edges WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
              ) WHERE node_id IN (?,?)
            """, (node_a, node_b))
            
            log_event(conn, "dream", "assess_option_option", f"{node_a}<->{node_b} {note}")
            conn.commit()
            self.stats["edges_updated"] += 1


# Global instance
DREAM = DreamWorker()
