"""Dream Worker - Maintains knowledge graph edges with correlations and LLM."""
import json
import logging
import random
import threading
import traceback
from typing import Optional, Dict

from src.config import Config
from src.database import db_conn, log_event, ensure_edge_id, edge_weight_top
from src.knowledge_graph import corr
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
                self._assess_pair()
                self.stats["steps"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_action"] = "assess_pair"
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


# Global instance
DREAM = DreamWorker()
