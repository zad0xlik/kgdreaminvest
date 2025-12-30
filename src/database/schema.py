"""Database schema and bootstrap data."""
import logging
from typing import Dict, List, Optional, Tuple

from src.config import Config
from src.database.connection import db_conn
from src.database.operations import ensure_edge_id
from src.utils import utc_now

logger = logging.getLogger("kginvest")

# ---------------------- Channel Configuration ----------------------

CHANNEL_WEIGHTS = {
    "correlates": 1.0,
    "inverse_correlates": 1.0,
    "drives": 0.9,
    "results_from": 0.8,
    "leads": 0.7,
    "lags": 0.7,
    "hedges": 0.8,
    "policy_exposed": 0.6,
    "supply_chain_linked": 0.6,
    "liquidity_coupled": 0.7,
    "sentiment_coupled": 0.7,
    "narrative_supports": 0.5,
    "narrative_contradicts": 0.7,
}


# ---------------------- Bootstrap Data ----------------------

# Derived nodes (signals, regimes, narratives)
DERIVED = [
    ("SIG_RISK_OFF", "signal", "Risk-Off Pressure", "Higher when volatility rises, equities weaken, USD strengthens."),
    ("SIG_RATES_UP", "signal", "Rates Pressure", "Higher when long yields rise and duration suffers."),
    ("SIG_OIL_SHOCK", "signal", "Oil Shock", "Higher when crude spikes and inflation impulse rises."),
    ("SIG_SEMI_PULSE", "signal", "Semis Pulse", "Higher when semis leadership is strong."),
    ("REG_RISK_OFF", "regime", "Risk-Off Regime", "Volatility/funding dominate; prefer defensives/cash."),
    ("REG_RISK_ON", "regime", "Risk-On Regime", "Breadth improves; cyclicals/tech do better."),
    ("REG_INFLATION", "regime", "Inflation Pressure", "Energy + yields up; rotate exposures carefully."),
    ("NAR_STORY", "narrative", "Market Narrative", "A rolling narrative summary from the agent committee."),
]

# Agent nodes
AGENTS = [
    ("AGENT_MACRO", "agent", "Agent: Macro", "Summarizes bellwethers and regime."),
    ("AGENT_TECH", "agent", "Agent: Technical", "Scans indicators/momentum/mean-reversion."),
    ("AGENT_RISK", "agent", "Agent: Risk", "Controls drawdown/turnover/cash buffer; suggests trims."),
    ("AGENT_ALLOC", "agent", "Agent: Allocator", "Integrates inputs into final BUY/SELL/HOLD decisions."),
]

# Bootstrap edges with initial channel strengths
BOOT_EDGES = [
    ("^VIX", "SIG_RISK_OFF", {"drives:^VIX->SIG_RISK_OFF": 0.80}),
    ("UUP", "SIG_RISK_OFF", {"drives:UUP->SIG_RISK_OFF": 0.55}),
    ("SPY", "SIG_RISK_OFF", {"inverse_correlates": 0.55}),
    ("^TNX", "SIG_RATES_UP", {"drives:^TNX->SIG_RATES_UP": 0.75}),
    ("CL=F", "SIG_OIL_SHOCK", {"drives:CL=F->SIG_OIL_SHOCK": 0.70}),
    ("TSM", "SIG_SEMI_PULSE", {"drives:TSM->SIG_SEMI_PULSE": 0.55}),
    ("SIG_RISK_OFF", "REG_RISK_OFF", {"drives:SIG_RISK_OFF->REG_RISK_OFF": 0.70}),
    ("SIG_RISK_OFF", "REG_RISK_ON", {"inverse_correlates": 0.55}),
    ("SIG_OIL_SHOCK", "REG_INFLATION", {"drives:SIG_OIL_SHOCK->REG_INFLATION": 0.60}),
    ("AGENT_ALLOC", "NAR_STORY", {"narrative_supports": 0.60}),
]


# ---------------------- Helper Functions ----------------------

def edge_weight_top(chs: Dict[str, float]) -> Tuple[float, Optional[str]]:
    """
    Calculate edge weight from channels and find top channel.
    
    Args:
        chs: Dict of channel name -> strength (0-1)
        
    Returns:
        Tuple of (total_weight, top_channel_name)
    """
    total = 0.0
    best = (0.0, None)
    
    for ch, s in chs.items():
        # Extract base channel type (before colon if directional)
        base = ch.split(":", 1)[0]
        w = CHANNEL_WEIGHTS.get(base, 0.5)
        s = float(s)
        total += w * s
        
        if s > best[0]:
            best = (s, ch)
    
    return float(total), best[1]


# ---------------------- Schema Initialization ----------------------

def init_db():
    """
    Initialize database schema.
    
    Creates all required tables if they don't exist:
    - meta: Key-value configuration store
    - nodes: Knowledge graph nodes (tickers, signals, agents, etc.)
    - edges: Knowledge graph edges (relationships between nodes)
    - edge_channels: Multi-channel edge annotations
    - snapshots: Market data snapshots
    - portfolio: Portfolio configuration
    - positions: Current holdings
    - trades: Trade history
    - insights: Agent committee insights/plans
    - dream_log: Event log
    - ticker_lookups: Ticker fetch history for diagnostics
    """
    with db_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS nodes (
          node_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          label TEXT NOT NULL,
          description TEXT,
          score REAL DEFAULT 0.0,
          degree INTEGER DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_touched TEXT
        );

        CREATE TABLE IF NOT EXISTS edges (
          edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
          node_a TEXT NOT NULL,
          node_b TEXT NOT NULL,
          weight REAL DEFAULT 0.0,
          top_channel TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_assessed TEXT,
          assessment_count INTEGER DEFAULT 0,
          UNIQUE(node_a, node_b)
        );

        CREATE TABLE IF NOT EXISTS edge_channels (
          edge_id INTEGER NOT NULL,
          channel TEXT NOT NULL,
          strength REAL NOT NULL,
          PRIMARY KEY(edge_id, channel)
        );

        CREATE TABLE IF NOT EXISTS snapshots (
          snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          prices_json TEXT,
          bells_json TEXT,
          indicators_json TEXT,
          signals_json TEXT
        );

        CREATE TABLE IF NOT EXISTS portfolio (k TEXT PRIMARY KEY, v TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS positions (
          symbol TEXT PRIMARY KEY,
          qty REAL NOT NULL,
          avg_cost REAL NOT NULL,
          last_price REAL NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
          trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty REAL NOT NULL,
          price REAL NOT NULL,
          notional REAL NOT NULL,
          reason TEXT,
          insight_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS insights (
          insight_id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          agents_json TEXT,
          decisions_json TEXT,
          confidence REAL NOT NULL,
          critic_score REAL NOT NULL,
          starred INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'new',
          evidence_snapshot_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS dream_log (
          log_id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          detail TEXT
        );

        CREATE TABLE IF NOT EXISTS ticker_lookups (
          lookup_id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          ticker TEXT NOT NULL,
          success INTEGER NOT NULL DEFAULT 1,
          price REAL,
          change_pct REAL,
          volume INTEGER
        );
        """)
        
        # Seed initial cash if not present
        r = conn.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()
        if not r:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)",
                (str(Config.START_CASH),)
            )
        
        conn.commit()


# ---------------------- Bootstrap Functions ----------------------

def bootstrap_if_empty():
    """
    Bootstrap knowledge graph with initial nodes and edges.
    
    Only runs if the nodes table is empty. Creates:
    - Investible ticker nodes
    - Bellwether ticker nodes
    - Derived signal/regime/narrative nodes
    - Agent nodes
    - Initial edges with channel strengths
    - Computes initial node degrees
    """
    with db_conn() as conn:
        c = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        if c:
            return  # Already bootstrapped
        
        logger.info("Bootstrapping KG…")

        # Create investible ticker nodes
        for t in Config.INVESTIBLES:
            conn.execute(
                "INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) "
                "VALUES(?,?,?,?,?)",
                (t, "investible", t, f"Investible ticker {t}.", utc_now())
            )

        # Create bellwether ticker nodes
        for b in Config.BELLWETHERS:
            conn.execute(
                "INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) "
                "VALUES(?,?,?,?,?)",
                (b, "bellwether", b, f"Bellwether ticker {b}.", utc_now())
            )

        # Create derived and agent nodes
        for nid, kind, label, desc in DERIVED + AGENTS:
            conn.execute(
                "INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) "
                "VALUES(?,?,?,?,?)",
                (nid, kind, label, desc, utc_now())
            )

        # Create bootstrap edges with channels
        for a, b, chs in BOOT_EDGES:
            eid = ensure_edge_id(conn, a, b)
            
            # Clear existing channels and insert new ones
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            for ch, s in chs.items():
                conn.execute(
                    "INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) "
                    "VALUES(?,?,?)",
                    (eid, ch, float(s))
                )
            
            # Calculate and store edge weight and top channel
            w, top = edge_weight_top(chs)
            conn.execute(
                "UPDATE edges SET weight=?, top_channel=? WHERE edge_id=?",
                (w, top, eid)
            )

        # Update node degrees based on edge count
        conn.execute("""
          UPDATE nodes SET degree = (
            SELECT COUNT(*) FROM edges 
            WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
          )
        """)

        conn.commit()
        logger.info("Bootstrap complete.")
