#!/usr/bin/env python3
"""
KGDreamInvest (Live/Paper) — continuously thinking multi-agent allocator + investing KG + pretty GUI

What this is
- Real-ish tickers (Yahoo Finance chart API; no yfinance)
- Paper portfolio + trades + mark-to-market
- A knowledge graph (nodes/edges) stored in SQLite
- 3 background loops:
    1) MARKET: fetch prices + indicators + bellwether signals into snapshots
    2) DREAM: refine KG edges + spawn small narrative/regime nodes (lightweight)
    3) THINK/TRADE: multi-agent committee proposes BUY/SELL/HOLD (JSON), writes plain-English explanation,
                   and (optionally) auto-executes paper trades (including SELLs to redeploy)

Design goals
- Keep the KGDreamInvest GUI aesthetic (vis-network graph + action board)
- Continuous autonomous operation (safe, paper-only), but with guard rails
- Explain decisions in plain English

Install:
  pip install flask requests numpy pytz

Run:
  export OLLAMA_HOST="http://localhost:11434"
  export DREAM_MODEL="gpt-oss:20b"
  export PORT=5062
  python3 kgdream_invest_live.py

Open:
  http://127.0.0.1:5062

Important
- Educational / experimental. Not financial advice. Paper trading only.
- Yahoo endpoints can rate-limit; defaults are conservative. Tune MARKET_SPEED.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
import random
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as urlquote

import numpy as np
import pytz
import requests
from flask import Flask, jsonify, render_template_string, request

# ---------------------- CONFIG ----------------------

ET = pytz.timezone("America/New_York")

DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("KGINVEST_DB", str(DATA_DIR / "kginvest_live.db")))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# DREAM_MODEL = os.environ.get("DREAM_MODEL", "gpt-oss:20b")
DREAM_MODEL = os.environ.get("DREAM_MODEL", "gemma3:4b")


DEBUG = os.environ.get("KGINVEST_DEBUG", "").lower() in ("1", "true", "yes")

# --- Universe ---
INVESTIBLES: List[str] = [
    "XLE", "XLF", "XLV", "XME", "IYT",
    "AAPL", "MSFT", "JPM", "UNH", "CAT",
    "NVDA", "AMD", "AMZN", "GOOGL", "META",
    "ARCB", "TTMI", "TRMK", "KWR", "ICUI",
]
BELLWETHERS: List[str] = [
    "SPY", "QQQ", "TLT", "^VIX", "UUP", "CL=F", "^TNX", "TSM",
]
ALL_TICKERS: List[str] = sorted(set(INVESTIBLES + BELLWETHERS))

# --- Speeds (ticks/min) ---
MARKET_SPEED = float(os.environ.get("MARKET_SPEED", "0.35"))   # ~ every 3 minutes
DREAM_SPEED = float(os.environ.get("DREAM_SPEED", "0.25"))     # ~ every 4 minutes
THINK_SPEED = float(os.environ.get("THINK_SPEED", "0.20"))     # ~ every 5 minutes

MARKET_INTERVAL = 60.0 / max(0.05, MARKET_SPEED)
DREAM_INTERVAL = 60.0 / max(0.05, DREAM_SPEED)
THINK_INTERVAL = 60.0 / max(0.05, THINK_SPEED)

# --- Unified LLM budget ---
LLM_CALLS_PER_MIN = int(os.environ.get("LLM_CALLS_PER_MIN", "8"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "45"))
LLM_TEMP = float(os.environ.get("LLM_TEMP", "0.25"))
LLM_MAX_REASK = int(os.environ.get("LLM_MAX_REASK", "1"))

# --- Autonomy toggles ---
AUTO_MARKET = os.environ.get("AUTO_MARKET", "1").lower() in ("1", "true", "yes")
AUTO_DREAM = os.environ.get("AUTO_DREAM", "1").lower() in ("1", "true", "yes")
AUTO_THINK = os.environ.get("AUTO_THINK", "1").lower() in ("1", "true", "yes")
AUTO_TRADE = os.environ.get("AUTO_TRADE", "1").lower() in ("1", "true", "yes")

# --- Trading guard rails (paper) ---
START_CASH = float(os.environ.get("START_CASH", "10000.0"))

MIN_TRADE_NOTIONAL = float(os.environ.get("MIN_TRADE_NOTIONAL", "25.0"))
MAX_BUY_EQUITY_PCT_PER_CYCLE = float(os.environ.get("MAX_BUY_EQUITY_PCT_PER_CYCLE", "18.0"))
MAX_SELL_HOLDING_PCT_PER_CYCLE = float(os.environ.get("MAX_SELL_HOLDING_PCT_PER_CYCLE", "35.0"))
MAX_SYMBOL_WEIGHT_PCT = float(os.environ.get("MAX_SYMBOL_WEIGHT_PCT", "14.0"))
MIN_CASH_BUFFER_PCT = float(os.environ.get("MIN_CASH_BUFFER_PCT", "12.0"))

# Daily-bar realism by default: trade outside market hours (override to trade anytime)
TRADE_ANYTIME = os.environ.get("TRADE_ANYTIME", "0").lower() in ("1", "true", "yes")

# --- Yahoo fetch ---
YAHOO_TIMEOUT = int(os.environ.get("YAHOO_TIMEOUT", "12"))
YAHOO_RANGE_DAYS = int(os.environ.get("YAHOO_RANGE_DAYS", "90"))
YAHOO_CACHE_SECONDS = int(os.environ.get("YAHOO_CACHE_SECONDS", "90"))  # avoid hammering

# --- Insight starring ---
STAR_THRESHOLD = float(os.environ.get("STAR_THRESHOLD", "0.72"))

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(str(DATA_DIR / "kginvest_live.log"))],
)
logger = logging.getLogger("kginvest")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kginvest-live-secret-change-me")

DB_LOCK = threading.RLock()

# ---------------------- UTIL ----------------------

def now_et() -> dt.datetime:
    return dt.datetime.now(ET)

def utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()

def today_et_str() -> str:
    return now_et().date().isoformat()

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)

def jitter_sleep(total: float, stop: threading.Event, step: float = 0.25):
    elapsed = 0.0
    while elapsed < total and not stop.is_set():
        time.sleep(min(step, total - elapsed))
        elapsed += step

def find_outermost_json(s: str) -> Optional[str]:
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s or ""):
        if ch == "\\" and in_str and not esc:
            esc = True
            continue
        if ch == '"' and not esc:
            in_str = not in_str
        esc = False
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return (s or "")[start:i + 1]
    return None

def extract_json(raw: str) -> Optional[Dict[str, Any]]:
    blob = find_outermost_json(raw or "")
    if not blob:
        return None
    try:
        return json.loads(blob)
    except Exception:
        return None

def fmt_money(x: float) -> str:
    return f"${x:,.2f}"

def market_is_open_et(ts: Optional[dt.datetime] = None) -> bool:
    t = ts or now_et()
    # NYSE regular hours: 9:30-16:00 ET, Mon-Fri (toy check; ignores holidays)
    if t.weekday() >= 5:
        return False
    h = t.hour + t.minute / 60.0
    return (h >= 9.5) and (h < 16.0)

# ---------------------- DB ----------------------

@contextmanager
def db_conn():
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=8000;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_db():
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
        """)
        # seed cash
        r = conn.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()
        if not r:
            conn.execute("INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)", (str(START_CASH),))
        conn.commit()

def kv_get(conn: sqlite3.Connection, k: str, default: Optional[str] = None) -> Optional[str]:
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default

def kv_set(conn: sqlite3.Connection, k: str, v: str):
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))

def norm_pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)

def ensure_edge_id(conn: sqlite3.Connection, a: str, b: str) -> int:
    a2, b2 = norm_pair(a, b)
    conn.execute("INSERT OR IGNORE INTO edges(node_a, node_b, created_at) VALUES(?,?,?)", (a2, b2, utc_now()))
    row = conn.execute("SELECT edge_id FROM edges WHERE node_a=? AND node_b=?", (a2, b2)).fetchone()
    return int(row["edge_id"])

def log_event(conn: sqlite3.Connection, actor: str, action: str, detail: str = ""):
    conn.execute(
        "INSERT INTO dream_log(ts, actor, action, detail) VALUES(?,?,?,?)",
        (utc_now(), actor, action, (detail or "")[:1600]),
    )

# ---------------------- KG Bootstrap ----------------------

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
AGENTS = [
    ("AGENT_MACRO", "agent", "Agent: Macro", "Summarizes bellwethers and regime."),
    ("AGENT_TECH", "agent", "Agent: Technical", "Scans indicators/momentum/mean-reversion."),
    ("AGENT_RISK", "agent", "Agent: Risk", "Controls drawdown/turnover/cash buffer; suggests trims."),
    ("AGENT_ALLOC", "agent", "Agent: Allocator", "Integrates inputs into final BUY/SELL/HOLD decisions."),
]

# Some starter edges (very lightweight; will be refined)
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

def edge_weight_top(chs: Dict[str, float]) -> Tuple[float, Optional[str]]:
    total = 0.0
    best = (0.0, None)
    for ch, s in chs.items():
        base = ch.split(":", 1)[0]
        w = CHANNEL_WEIGHTS.get(base, 0.5)
        s = float(s)
        total += w * s
        if s > best[0]:
            best = (s, ch)
    return float(total), best[1]

def bootstrap_if_empty():
    with db_conn() as conn:
        c = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        if c:
            return
        logger.info("Bootstrapping KG…")

        # nodes
        for t in INVESTIBLES:
            conn.execute("INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) VALUES(?,?,?,?,?)",
                         (t, "investible", t, f"Investible ticker {t}.", utc_now()))
        for b in BELLWETHERS:
            conn.execute("INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) VALUES(?,?,?,?,?)",
                         (b, "bellwether", b, f"Bellwether ticker {b}.", utc_now()))
        for nid, kind, label, desc in DERIVED + AGENTS:
            conn.execute("INSERT OR IGNORE INTO nodes(node_id, kind, label, description, last_touched) VALUES(?,?,?,?,?)",
                         (nid, kind, label, desc, utc_now()))

        # edges
        for a, b, chs in BOOT_EDGES:
            eid = ensure_edge_id(conn, a, b)
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            for ch, s in chs.items():
                conn.execute("INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)", (eid, ch, float(s)))
            w, top = edge_weight_top(chs)
            conn.execute("UPDATE edges SET weight=?, top_channel=? WHERE edge_id=?", (w, top, eid))

        # degrees
        conn.execute("""
          UPDATE nodes SET degree = (
            SELECT COUNT(*) FROM edges WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
          )
        """)

        conn.commit()
        logger.info("Bootstrap complete.")

# ---------------------- Portfolio helpers ----------------------

def get_cash(conn: sqlite3.Connection) -> float:
    r = conn.execute("SELECT v FROM portfolio WHERE k='cash'").fetchone()
    if not r:
        conn.execute("INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)", (str(START_CASH),))
        return START_CASH
    try:
        return float(r["v"])
    except Exception:
        return START_CASH

def set_cash(conn: sqlite3.Connection, cash: float):
    conn.execute("INSERT OR REPLACE INTO portfolio(k,v) VALUES('cash', ?)", (str(float(cash)),))

def portfolio_state(conn: sqlite3.Connection, prices: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cash = get_cash(conn)
    pos = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
    positions = []
    equity = cash
    price_map = prices or {}
    for r in pos:
        sym = r["symbol"]
        qty = float(r["qty"])
        last = float(r["last_price"])
        if sym in price_map:
            try:
                last = float(price_map[sym]["current"])
            except Exception:
                pass
        avg = float(r["avg_cost"])
        mv = qty * last
        pnl = (last - avg) * qty
        equity += mv
        positions.append({"symbol": sym, "qty": qty, "last_price": last, "avg_cost": avg, "pnl": pnl, "mv": mv})
    return {"cash": cash, "equity": equity, "positions": positions}

def positions_as_dict(conn: sqlite3.Connection) -> Dict[str, float]:
    rows = conn.execute("SELECT symbol, qty FROM positions").fetchall()
    return {r["symbol"]: float(r["qty"]) for r in rows}

def recent_trade_summary(conn: sqlite3.Connection, limit: int = 12) -> str:
    rows = conn.execute("SELECT ts, symbol, side, notional FROM trades ORDER BY trade_id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return "No recent trades."
    lines = []
    for r in rows[::-1]:
        ts = (r["ts"] or "")[:19]
        lines.append(f"{ts}: {r['side']} {r['symbol']} notional={float(r['notional']):.2f}")
    return "\n".join(lines)

# ---------------------- Yahoo Finance (no yfinance) ----------------------

UA_LIST = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
]

def _headers() -> Dict[str, str]:
    return {"User-Agent": random.choice(UA_LIST), "Accept": "application/json", "Connection": "keep-alive"}

_PRICE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_PRICE_CACHE_LOCK = threading.Lock()

def fetch_yahoo_chart(symbol: str, range_days: int = 60) -> Dict[str, Any]:
    """
    Direct call to Yahoo's chart API.
    Returns dict with closes + timestamps or {} on failure.
    """
    sym = urlquote(symbol, safe="")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"interval": "1d", "range": f"{range_days}d"}
    try:
        resp = requests.get(url, params=params, headers=_headers(), timeout=YAHOO_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"{symbol}: Yahoo HTTP {resp.status_code}")
            return {}
        data = resp.json()
        result = (data.get("chart", {}).get("result") or [])
        if not result:
            return {}
        result = result[0]
        ts = result.get("timestamp", []) or []
        quotes = result.get("indicators", {}).get("quote", []) or []
        if not quotes:
            return {}
        q = quotes[0]
        closes = q.get("close", []) or []
        volumes = q.get("volume", []) or []
        valid = [(t, c, v) for t, c, v in zip(ts, closes, volumes) if c is not None]
        if not valid:
            return {}
        ts, closes, volumes = zip(*valid)
        return {"symbol": symbol, "timestamps": list(ts), "closes": list(map(float, closes)), "volumes": list(volumes)}
    except Exception:
        return {}

def fetch_single_ticker(symbol: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Cached: get last two closes + history.
    """
    now = time.time()
    with _PRICE_CACHE_LOCK:
        if symbol in _PRICE_CACHE:
            ts, payload = _PRICE_CACHE[symbol]
            if now - ts <= YAHOO_CACHE_SECONDS:
                return symbol, payload

    chart = fetch_yahoo_chart(symbol, range_days=YAHOO_RANGE_DAYS)
    closes = chart.get("closes", [])
    if len(closes) < 2:
        return symbol, None
    current = float(closes[-1])
    previous = float(closes[-2])
    change_pct = ((current - previous) / max(previous, 1e-9)) * 100.0
    payload = {"current": current, "previous": previous, "change_pct": float(change_pct), "history": closes}
    with _PRICE_CACHE_LOCK:
        _PRICE_CACHE[symbol] = (now, payload)
    return symbol, payload

def last_close_many(symbols: List[str], max_workers: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Thread pool fetch. Keeps this file dependency-light.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_single_ticker, s): s for s in symbols}
        for fut in as_completed(futs):
            try:
                sym, data = fut.result()
                if data:
                    results[sym] = data
            except Exception:
                continue
    return results

# ---------------------- Indicators & Signals ----------------------

def compute_indicators(closes: List[float]) -> Dict[str, float]:
    if len(closes) < 21:
        return {"mom5": 0.0, "mom20": 0.0, "volatility": 0.0, "zscore": 0.0, "rsi": 50.0}
    arr = np.array(closes, dtype=float)
    mom5 = (arr[-1] / arr[-6] - 1.0) if len(arr) >= 6 else 0.0
    mom20 = (arr[-1] / arr[-21] - 1.0) if len(arr) >= 21 else 0.0

    returns = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
    volatility = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.0

    ma20 = float(np.mean(arr[-20:]))
    sd20 = float(np.std(arr[-20:]))
    zscore = (arr[-1] - ma20) / (sd20 + 1e-9) if sd20 > 0 else 0.0

    gains = np.maximum(returns[-14:], 0)
    losses = np.abs(np.minimum(returns[-14:], 0))
    avg_gain = float(np.mean(gains)) if len(gains) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    return {
        "mom5": round(float(mom5), 4),
        "mom20": round(float(mom20), 4),
        "volatility": round(float(volatility), 4),
        "zscore": round(float(zscore), 2),
        "rsi": round(float(rsi), 1),
    }

def compute_signals_from_bells(prices: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """
    Simple, explainable signals derived from bellwethers.
    """
    def ch(sym: str) -> float:
        return float(prices.get(sym, {}).get("change_pct", 0.0) or 0.0)

    vix = ch("^VIX")
    spy = ch("SPY")
    qqq = ch("QQQ")
    tlt = ch("TLT")
    uup = ch("UUP")
    tnx = ch("^TNX")
    oil = ch("CL=F")
    tsm = ch("TSM")

    # Normalize and combine (heuristic)
    risk_off = clamp01(0.50 + 0.06 * vix + 0.05 * uup - 0.05 * spy - 0.03 * qqq + 0.03 * tlt)
    rates_up = clamp01(0.50 + 0.10 * tnx - 0.03 * tlt)
    oil_shock = clamp01(0.50 + 0.06 * oil)
    semi_pulse = clamp01(0.50 + 0.06 * tsm + 0.03 * qqq)

    return {
        "risk_off": round(float(risk_off), 3),
        "rates_up": round(float(rates_up), 3),
        "oil_shock": round(float(oil_shock), 3),
        "semi_pulse": round(float(semi_pulse), 3),
    }

# ---------------------- Unified LLM Budget ----------------------

class LLMBudget:
    def __init__(self, calls_per_min: int):
        self.calls_per_min = max(1, int(calls_per_min))
        self.lock = threading.Lock()
        self.window_start = time.time()
        self.calls = 0
        self.last_error: Optional[str] = None

    def _reset_if_needed(self):
        now = time.time()
        if now - self.window_start >= 60.0:
            self.window_start = now
            self.calls = 0

    def acquire(self) -> bool:
        with self.lock:
            self._reset_if_needed()
            if self.calls >= self.calls_per_min:
                return False
            self.calls += 1
            return True

    def stats(self) -> Dict[str, Any]:
        with self.lock:
            self._reset_if_needed()
            return {"calls_used": self.calls, "calls_budget": self.calls_per_min, "last_error": self.last_error}

LLM_BUDGET = LLMBudget(LLM_CALLS_PER_MIN)

def ollama_chat_json(system: str, user: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Uses /api/chat with JSON-only outputs. Robust re-ask on invalid JSON.
    """
    if not LLM_BUDGET.acquire():
        return None, None
    url = f"{OLLAMA_HOST}/api/chat"
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    payload = {"model": DREAM_MODEL, "messages": msgs, "stream": False, "options": {"temperature": LLM_TEMP}}

    def _call(messages):
        r = requests.post(url, json={**payload, "messages": messages}, timeout=LLM_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        return ((r.json().get("message", {}) or {}).get("content", "") or "")

    try:
        raw = _call(msgs)
        parsed = extract_json(raw)
        if parsed is not None:
            LLM_BUDGET.last_error = None
            return parsed, raw

        for _ in range(max(0, LLM_MAX_REASK)):
            repair = "Your prior output was not valid JSON. Respond with ONLY one valid JSON object; no extra text."
            raw2 = _call(msgs + [{"role": "assistant", "content": raw}, {"role": "user", "content": repair}])
            parsed2 = extract_json(raw2)
            if parsed2 is not None:
                LLM_BUDGET.last_error = None
                return parsed2, raw2
            raw = raw2

        LLM_BUDGET.last_error = "parse_fail"
        return None, raw
    except Exception as e:
        LLM_BUDGET.last_error = str(e)
        return None, None

# ---------------------- Market Worker ----------------------

class MarketWorker:
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {"ticks": 0, "last_ts": None, "last_ok": None, "last_error": None}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("MarketWorker started")

    def stop_now(self):
        self.running = False
        self.stop.set()
        logger.info("MarketWorker stop signaled")

    def _loop(self):
        while self.running and not self.stop.is_set():
            try:
                self.step_once()
                self.stats["ticks"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_ok"] = True
                self.stats["last_error"] = None
            except Exception as e:
                self.stats["last_ok"] = False
                self.stats["last_error"] = str(e)
                logger.error(f"MarketWorker error: {e}")
                logger.debug(traceback.format_exc())
            jitter_sleep(MARKET_INTERVAL, self.stop)

    def step_once(self):
        prices = last_close_many(ALL_TICKERS, max_workers=min(10, len(ALL_TICKERS)))
        if not prices:
            raise RuntimeError("Yahoo fetch returned no prices")

        indicators: Dict[str, Dict[str, float]] = {}
        for t in INVESTIBLES:
            p = prices.get(t)
            if not p:
                continue
            closes = p.get("history") or []
            indicators[t] = compute_indicators(closes)

        bells = {b: prices[b] for b in BELLWETHERS if b in prices}
        signals = compute_signals_from_bells(prices)

        with db_conn() as conn:
            # mark-to-market positions with current prices
            for sym, pdata in prices.items():
                if "current" in pdata:
                    conn.execute("UPDATE positions SET last_price=?, updated_at=? WHERE symbol=?", (float(pdata["current"]), utc_now(), sym))

            conn.execute(
                "INSERT INTO snapshots(ts, prices_json, bells_json, indicators_json, signals_json) VALUES(?,?,?,?,?)",
                (utc_now(), json.dumps(prices), json.dumps(bells), json.dumps(indicators), json.dumps(signals)),
            )
            snap_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
            log_event(conn, "market", "tick", f"snapshot_id={snap_id} have={len(prices)}/{len(ALL_TICKERS)}")
            # keep last N snapshots
            conn.execute("DELETE FROM snapshots WHERE snapshot_id < (SELECT MAX(snapshot_id) - 1500 FROM snapshots)")
            conn.commit()

MARKET = MarketWorker()

# ---------------------- Dream Worker (KG edges) ----------------------

def corr(a: List[float], b: List[float]) -> float:
    if len(a) < 20 or len(b) < 20:
        return 0.0
    x = np.array(a[-60:], dtype=float)
    y = np.array(b[-60:], dtype=float)
    rx = np.diff(x) / np.maximum(x[:-1], 1e-9)
    ry = np.diff(y) / np.maximum(y[:-1], 1e-9)
    if len(rx) < 10 or len(ry) < 10:
        return 0.0
    c = float(np.corrcoef(rx, ry)[0, 1])
    if math.isnan(c) or math.isinf(c):
        return 0.0
    return max(-1.0, min(1.0, c))

class DreamWorker:
    """
    Light KG maintenance:
    - Update correlations between a random investible and a random bellwether
    - Occasionally ask the LLM to label the relationship channels
    """
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {"steps": 0, "edges_updated": 0, "last_ts": None, "last_action": None}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("DreamWorker started")

    def stop_now(self):
        self.running = False
        self.stop.set()
        logger.info("DreamWorker stop signaled")

    def _loop(self):
        while self.running and not self.stop.is_set():
            try:
                self._assess_pair()
                self.stats["steps"] += 1
                self.stats["last_ts"] = utc_now()
                self.stats["last_action"] = "assess_pair"
            except Exception as e:
                logger.error(f"DreamWorker error: {e}")
                logger.debug(traceback.format_exc())
            jitter_sleep(DREAM_INTERVAL, self.stop)

    def _assess_pair(self):
        inv = random.choice(INVESTIBLES)
        bw = random.choice(BELLWETHERS)

        with db_conn() as conn:
            snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
            if not snap:
                return
            prices = json.loads(snap["prices_json"] or "{}")
            a = prices.get(inv, {}).get("history") or []
            b = prices.get(bw, {}).get("history") or []
            c = corr(a, b)

            # heuristic channel set from correlation sign/magnitude
            channels: Dict[str, float] = {}
            mag = abs(c)
            if mag >= 0.25:
                if c > 0:
                    channels["correlates"] = float(min(1.0, 0.35 + 0.75 * mag))
                else:
                    channels["inverse_correlates"] = float(min(1.0, 0.35 + 0.75 * mag))
            # add a mild "liquidity_coupled" for equities vs SPY/QQQ
            if bw in ("SPY", "QQQ") and mag >= 0.15:
                channels["liquidity_coupled"] = float(min(1.0, 0.25 + 0.8 * mag))

            # occasionally let LLM annotate directionality / narrative channel
            use_llm = random.random() < 0.30
            note = f"corr={c:+.2f} (heuristic)"
            if use_llm:
                prompt = f"""
You are labeling a relationship in an investing knowledge graph.

NODE A: {inv} (investible)
NODE B: {bw} (bellwether)

Observed return-correlation over recent days: {c:+.2f}

Choose 0-3 channels and strengths (>=0.10). Allowed channels:
correlates, inverse_correlates, drives, results_from, leads, lags, hedges, policy_exposed,
supply_chain_linked, liquidity_coupled, sentiment_coupled, narrative_supports, narrative_contradicts.

Directional channels must be encoded as "<base>:A->B" or "<base>:B->A" where A and B are node IDs.

Return ONLY JSON:
{{
  "channels": {{ "correlates": 0.0-1.0, "drives:{inv}->{bw}": 0.0-1.0 }},
  "note": "one sentence"
}}
""".strip()
                system = "You are a careful KG edge adjudicator. Output valid JSON only."
                parsed, _raw = ollama_chat_json(system, prompt)
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

            eid = ensure_edge_id(conn, inv, bw)
            conn.execute("DELETE FROM edge_channels WHERE edge_id=?", (eid,))
            for ch, s in channels.items():
                conn.execute("INSERT OR REPLACE INTO edge_channels(edge_id, channel, strength) VALUES(?,?,?)", (eid, ch, float(s)))
            w, top = edge_weight_top(channels)
            conn.execute("UPDATE edges SET weight=?, top_channel=?, last_assessed=?, assessment_count=assessment_count+1 WHERE edge_id=?",
                         (w, top, utc_now(), eid))
            conn.execute("UPDATE nodes SET last_touched=?, score=score+0.005 WHERE node_id IN (?,?)", (utc_now(), inv, bw))
            conn.execute("""
              UPDATE nodes SET degree = (
                SELECT COUNT(*) FROM edges WHERE edges.node_a = nodes.node_id OR edges.node_b = nodes.node_id
              ) WHERE node_id IN (?,?)
            """, (inv, bw))

            log_event(conn, "dream", "assess_pair", f"{inv}<->{bw} {note}")
            conn.commit()
            self.stats["edges_updated"] += 1

DREAM = DreamWorker()

# ---------------------- Think/Trade Worker (multi-agent committee) ----------------------

def critic_score(explanation: str, decisions: List[Dict[str, Any]], conf: float) -> float:
    score = 0.22 + 0.48 * clamp01(conf)
    if len(explanation) >= 220:
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

def rule_based_fallback(prices: Dict[str, Any], indicators: Dict[str, Any], signals: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, float]:
    """
    No-LLM fallback: simple score = mom20 - 2*volatility; risk_off trims.
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

def execute_paper_trades(conn: sqlite3.Connection, decisions: List[Dict[str, Any]], prices: Dict[str, Any], reason: str, insight_id: int) -> Dict[str, Any]:
    """
    Execute SELLs first (free cash), then BUYs. Guard rails enforced.
    """
    cash = get_cash(conn)
    pf = portfolio_state(conn, prices=prices)
    equity = float(pf["equity"])

    # current per-symbol MV
    mv_by_sym: Dict[str, float] = {p["symbol"]: float(p["mv"]) for p in pf["positions"]}
    qty_by_sym: Dict[str, float] = {p["symbol"]: float(p["qty"]) for p in pf["positions"]}

    # constrain totals
    buy_budget = equity * (MAX_BUY_EQUITY_PCT_PER_CYCLE / 100.0)
    cash_buffer = equity * (MIN_CASH_BUFFER_PCT / 100.0)

    executed: List[Dict[str, Any]] = []
    skipped: List[str] = []

    # helper: get price
    def px(sym: str) -> float:
        try:
            return float(prices.get(sym, {}).get("current", 0.0) or 0.0)
        except Exception:
            return 0.0

    # SELL pass
    for d in decisions:
        if d.get("action") != "SELL":
            continue
        sym = d.get("ticker")
        if sym not in prices:
            continue
        have = float(qty_by_sym.get(sym, 0.0))
        if have <= 0:
            continue
        pct = min(float(d.get("allocation_pct", 0.0) or 0.0), MAX_SELL_HOLDING_PCT_PER_CYCLE)
        if pct <= 0:
            continue
        sell_sh = have * (pct / 100.0)
        p = px(sym)
        notional = sell_sh * p
        if notional < MIN_TRADE_NOTIONAL:
            skipped.append(f"SELL {sym} notional too small")
            continue

        new_have = have - sell_sh
        cash += notional
        qty_by_sym[sym] = new_have
        mv_by_sym[sym] = new_have * p

        if new_have <= 1e-8:
            conn.execute("DELETE FROM positions WHERE symbol=?", (sym,))
        else:
            conn.execute("UPDATE positions SET qty=?, last_price=?, updated_at=? WHERE symbol=?", (new_have, p, utc_now(), sym))

        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) VALUES(?,?,?,?,?,?,?,?)",
            (utc_now(), sym, "SELL", float(sell_sh), float(p), float(notional), reason[:400], int(insight_id)),
        )
        executed.append({"ticker": sym, "side": "SELL", "shares": sell_sh, "price": p, "notional": notional})

    # BUY pass
    for d in decisions:
        if d.get("action") != "BUY":
            continue
        sym = d.get("ticker")
        if sym not in prices:
            continue
        pct = float(d.get("allocation_pct", 0.0) or 0.0)
        if pct <= 0:
            continue

        p = px(sym)
        if p <= 0:
            continue

        # enforce cash buffer
        spendable = max(0.0, cash - cash_buffer)
        if spendable < MIN_TRADE_NOTIONAL:
            skipped.append("BUY: cash buffer prevents spending")
            break

        # requested notional is pct of equity but bounded by buy_budget and spendable
        requested = equity * (pct / 100.0)
        notional = min(requested, buy_budget, spendable)
        if notional < MIN_TRADE_NOTIONAL:
            skipped.append(f"BUY {sym} notional too small")
            continue

        # enforce per-symbol cap
        current_mv = float(mv_by_sym.get(sym, 0.0))
        cap = equity * (MAX_SYMBOL_WEIGHT_PCT / 100.0)
        if current_mv >= cap:
            skipped.append(f"BUY {sym} cap reached")
            continue
        notional = min(notional, max(0.0, cap - current_mv))
        if notional < MIN_TRADE_NOTIONAL:
            skipped.append(f"BUY {sym} cap residual too small")
            continue

        shares = notional / p
        cash -= notional
        buy_budget -= notional

        have = float(qty_by_sym.get(sym, 0.0))
        row = conn.execute("SELECT * FROM positions WHERE symbol=?", (sym,)).fetchone()
        avg = float(row["avg_cost"]) if row else p
        new_qty = have + shares
        new_avg = (avg * have + p * shares) / max(1e-9, new_qty)

        qty_by_sym[sym] = new_qty
        mv_by_sym[sym] = new_qty * p

        conn.execute(
            "INSERT OR REPLACE INTO positions(symbol,qty,avg_cost,last_price,updated_at) VALUES(?,?,?,?,?)",
            (sym, float(new_qty), float(new_avg), float(p), utc_now()),
        )
        conn.execute(
            "INSERT INTO trades(ts,symbol,side,qty,price,notional,reason,insight_id) VALUES(?,?,?,?,?,?,?,?)",
            (utc_now(), sym, "BUY", float(shares), float(p), float(notional), reason[:400], int(insight_id)),
        )
        executed.append({"ticker": sym, "side": "BUY", "shares": shares, "price": p, "notional": notional})

        if buy_budget < MIN_TRADE_NOTIONAL:
            break

    set_cash(conn, cash)
    return {"executed": executed, "skipped": skipped, "cash": cash}

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
        self.stats = {"steps": 0, "insights_created": 0, "insights_starred": 0, "trades_applied": 0, "last_ts": None, "last_action": None}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("ThinkWorker started")

    def stop_now(self):
        self.running = False
        self.stop.set()
        logger.info("ThinkWorker stop signaled")

    def _loop(self):
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
        agents, decisions, explanation, conf = self._llm_committee(prices, indicators, signals, pf, positions, trade_hist)

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
                res = execute_paper_trades(
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

    def _llm_committee(self, prices: Dict[str, Any], indicators: Dict[str, Any], signals: Dict[str, Any],
                       pf: Dict[str, Any], positions: Dict[str, float], trade_hist: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, float]:
        """
        One LLM call that returns multi-agent structured output.
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

        system = (
            "You are a cautious, data-driven paper-trading allocator. "
            "You are a committee of agents (Macro, Technical, Risk, Allocator). "
            "You must output ONLY one valid JSON object.\n\n"
            "Rules:\n"
            "- No leverage. No shorting.\n"
            "- Keep total BUY allocation modest; prefer incremental changes.\n"
            "- Suggest SELLs when reallocating (free cash), and explain why.\n"
            "- Be diversified; avoid concentrating into one theme.\n"
            "- Output decisions for the investible universe only.\n"
        )

        user = f"""
LATEST BELLWETHERS (1d):
{chr(10).join(bell_lines) if bell_lines else "(missing)"}

DERIVED SIGNALS (0-1):
{json.dumps(signals)}

INVESTIBLES SNAPSHOT:
{chr(10).join(inv_lines) if inv_lines else "(missing)"}

PORTFOLIO:
- Cash: {fmt_money(float(pf.get('cash',0)))}
- Equity est: {fmt_money(float(pf.get('equity',0)))}
- Positions:
{chr(10).join(pos_lines) if pos_lines else "- None"}

RECENT TRADES:
{trade_hist}

GUARDRAILS:
- MIN_CASH_BUFFER_PCT={MIN_CASH_BUFFER_PCT}
- MAX_BUY_EQUITY_PCT_PER_CYCLE={MAX_BUY_EQUITY_PCT_PER_CYCLE}
- MAX_SELL_HOLDING_PCT_PER_CYCLE={MAX_SELL_HOLDING_PCT_PER_CYCLE}
- MAX_SYMBOL_WEIGHT_PCT={MAX_SYMBOL_WEIGHT_PCT}

TASK:
Return ONLY JSON:
{{
  "agents": {{
    "macro": {{"regime":"...", "bullets":["..."], "risk_off":0-1}},
    "technical": {{"top":["TICK","..."], "bottom":["TICK","..."], "bullets":["..."]}},
    "risk": {{"cash_buffer_pct": number, "trim":["TICK","..."], "bullets":["..."]}},
    "allocator": {{"bullets":["..."]}}
  }},
  "decisions": [
    {{"ticker":"AAPL","action":"BUY|SELL|HOLD","allocation_pct":0-80,"note":"short reason"}}
  ],
  "explanation": "4-8 sentences plain English, explicitly mention what to SELL (if any) and what you redeploy into.",
  "confidence": 0-1
}}

Notes:
- allocation_pct means: for BUY = % of equity to spend; for SELL = % of that holding to sell.
- Keep BUY sizes small unless confidence is high and risk_off is low.
- Include an entry for every investible ticker (use HOLD for most).
""".strip()

        parsed, _raw = ollama_chat_json(system, user)
        if not parsed:
            return rule_based_fallback(prices, indicators, signals)

        agents = parsed.get("agents") if isinstance(parsed.get("agents"), dict) else {}
        decisions = sanitize_decisions(parsed.get("decisions", []))
        explanation = str(parsed.get("explanation", "")).strip()
        if not explanation:
            explanation = "No explanation provided."
        try:
            conf = clamp01(float(parsed.get("confidence", 0.5) or 0.5))
        except Exception:
            conf = 0.5

        # If decisions are empty, fallback
        if not decisions:
            return rule_based_fallback(prices, indicators, signals)

        return agents, decisions, explanation, conf

THINK = ThinkWorker()

# ---------------------- Web UI ----------------------

def kind_color(kind: str) -> str:
    return {
        "investible": "#34d399",
        "bellwether": "#60a5fa",
        "signal": "#a78bfa",
        "regime": "#fbbf24",
        "narrative": "#f472b6",
        "agent": "#22c55e",
    }.get(kind, "#9ca3af")

def edge_color(top: str) -> str:
    if not top:
        return "#475569"
    if top.startswith("drives"):
        return "#60a5fa"
    if top.startswith("inverse"):
        return "#f87171"
    if top.startswith("correlates"):
        return "#34d399"
    if top.startswith("sentiment"):
        return "#a78bfa"
    if top.startswith("policy"):
        return "#fbbf24"
    if top.startswith("liquidity"):
        return "#38bdf8"
    return "#94a3b8"

INDEX_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>KGDreamInvest — Live/Paper</title>
<script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
<style>
*{box-sizing:border-box} body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:linear-gradient(135deg,#0b1220,#111827);color:#e5e7eb}
.container{display:grid;grid-template-columns:340px 1fr 420px;gap:12px;padding:12px;height:100vh}
.panel{background:rgba(17,24,39,.92);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:14px;overflow:auto}
h2{margin:0 0 12px 0;font-size:16px;color:#a78bfa;display:flex;gap:8px;align-items:center}
.row{display:flex;justify-content:space-between;align-items:center;padding:10px;margin:8px 0;background:rgba(255,255,255,.05);border-radius:10px}
.label{color:#9ca3af;font-size:12px}.value{color:#e5e7eb;font-weight:700;font-size:14px}
.btn{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-weight:800;cursor:pointer;margin:6px 0}
.btn.red{background:linear-gradient(135deg,#ef4444,#dc2626)} .btn.gray{background:rgba(255,255,255,.08)}
#graph{width:100%;height:100%;background:rgba(0,0,0,.18);border-radius:14px;border:1px solid rgba(255,255,255,.06);overflow:hidden}
.pill{display:inline-block;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:800;border:1px solid rgba(255,255,255,.14)}
.pill.on{background:rgba(34,197,94,.18);color:#86efac} .pill.off{background:rgba(239,68,68,.18);color:#fca5a5}
.small{font-size:12px;color:#9ca3af}
.log{padding:10px;border-left:3px solid #6366f1;background:rgba(255,255,255,.03);border-radius:10px;margin:8px 0;font-size:12px}
.insight{padding:12px;border-radius:12px;border:1px solid rgba(255,255,255,.10);background:linear-gradient(135deg,rgba(167,139,250,.10),rgba(59,130,246,.06));margin:10px 0}
.insight .title{font-weight:900;color:#ddd6fe;margin-bottom:6px}
.insight .meta{color:#fbbf24;font-size:11px;margin-top:8px;font-weight:800;display:flex;justify-content:space-between;gap:8px;align-items:center}
.insight .action{margin-top:8px;font-size:12px;color:#bfdbfe}
.table{width:100%;border-collapse:collapse;font-size:12px} .table th,.table td{padding:8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:right}
.table th:first-child,.table td:first-child{text-align:left}
.kpi{display:grid;grid-template-columns:1fr 1fr;gap:8px} .kpi .row{margin:0}
.divider{height:1px;background:rgba(255,255,255,.08);margin:12px 0}
.mono{font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;}
</style>
</head>
<body>
<div class="container">
  <div class="panel">
    <h2>🌀 KGDreamInvest (Live/Paper)</h2>
    <div class="kpi">
      <div class="row"><div class="label">Nodes</div><div class="value" id="k_nodes">{{node_count}}</div></div>
      <div class="row"><div class="label">Edges</div><div class="value" id="k_edges">{{edge_count}}</div></div>

      <div class="row"><div class="label">Market</div><div class="value"><span id="market_badge" class="pill {{'on' if market_running else 'off'}}">{{'ON' if market_running else 'OFF'}}</span></div></div>
      <div class="row"><div class="label">Dream</div><div class="value"><span id="dream_badge" class="pill {{'on' if dream_running else 'off'}}">{{'ON' if dream_running else 'OFF'}}</span></div></div>
      <div class="row"><div class="label">Think</div><div class="value"><span id="think_badge" class="pill {{'on' if think_running else 'off'}}">{{'ON' if think_running else 'OFF'}}</span></div></div>
      <div class="row"><div class="label">AutoTrade</div><div class="value"><span id="trade_badge" class="pill {{'on' if auto_trade else 'off'}}">{{'ON' if auto_trade else 'OFF'}}</span></div></div>
    </div>

    <div class="divider"></div>
    <h2>📡 Latest Snapshot</h2>
    <div class="row"><div class="label">SPY</div><div class="value" id="bw_spy">{{latest.spy}}</div></div>
    <div class="row"><div class="label">QQQ</div><div class="value" id="bw_qqq">{{latest.qqq}}</div></div>
    <div class="row"><div class="label">VIX</div><div class="value" id="bw_vix">{{latest.vix}}</div></div>
    <div class="row"><div class="label">UUP</div><div class="value" id="bw_uup">{{latest.uup}}</div></div>
    <div class="row"><div class="label">Signals</div><div class="value"><span class="small mono" id="sig_line">{{latest.signals}}</span></div></div>

    <div class="divider"></div>
    <h2>💼 Paper Portfolio</h2>
    <div class="row"><div class="label">Cash</div><div class="value" id="pf_cash">{{portfolio.cash}}</div></div>
    <div class="row"><div class="label">Equity</div><div class="value" id="pf_equity">{{portfolio.equity}}</div></div>
    <table class="table" id="pos_table">
      <thead><tr><th>Symbol</th><th>Qty</th><th>Last</th><th>P&L</th></tr></thead>
      <tbody>
        {% for p in portfolio.positions %}
          <tr><td>{{p.symbol}}</td><td>{{"%.3f"|format(p.qty)}}</td><td>{{"%.2f"|format(p.last_price)}}</td><td>{{"%.2f"|format(p.pnl)}}</td></tr>
        {% endfor %}
      </tbody>
    </table>

    <div class="divider"></div>
    <h2>🎛 Controls</h2>
    <button class="btn" onclick="marketStart()">▶ Start Market</button>
    <button class="btn red" onclick="marketStop()">⏸ Stop Market</button>
    <button class="btn" onclick="dreamStart()">🌙 Start Dream</button>
    <button class="btn red" onclick="dreamStop()">🛑 Stop Dream</button>
    <button class="btn" onclick="thinkStart()">🧠 Start Think</button>
    <button class="btn red" onclick="thinkStop()">🧯 Stop Think</button>
    <button class="btn gray" onclick="stepMarket()">⏭ Market Step</button>
    <button class="btn gray" onclick="stepThink()">⏭ Think Step</button>
    <button class="btn gray" onclick="refreshAll()">🔄 Refresh</button>

    <div class="divider"></div>
    <h2>🧠 LLM Budget</h2>
    <div class="row"><div class="label">Calls/min</div><div class="value" id="llm_calls">{{llm.calls_used}} / {{llm.calls_budget}}</div></div>
    <div class="row"><div class="label">Last error</div><div class="value"><span class="small" id="llm_err">{{llm.last_error}}</span></div></div>

    <div class="divider"></div>
    <h2>🧾 Recent Activity</h2>
    <div id="log_box">
      {% for l in logs %}
        <div class="log"><b>{{l.actor}}</b> · <span style="color:#a78bfa">{{l.action}}</span><br/><span class="small">{{l.ts}}</span><br/>{{l.detail}}</div>
      {% endfor %}
    </div>
  </div>

  <div id="graph"></div>

  <div class="panel">
    <h2>⭐ Starred Plans</h2>
    <div id="insight_box">
      {% for ins in insights %}
        <div class="insight">
          <div class="title">{{ins.title}}</div>
          <div class="small">{{ins.ts}} · status={{ins.status}}</div>
          <div style="margin-top:8px; white-space:pre-wrap;">{{ins.body}}</div>
          <div class="action"><b>Decisions:</b> <span class="small mono">{{ins.decisions}}</span></div>
          <div class="meta">
            <span>★ {{ "%.2f"|format(ins.critic_score) }} · conf {{ "%.2f"|format(ins.confidence) }}</span>
            <span>
              <button class="btn gray" style="width:auto;padding:6px 10px;margin:0" onclick="approveInsight({{ins.insight_id}})">Approve</button>
            </span>
          </div>
        </div>
      {% endfor %}
    </div>

    <div class="divider"></div>
    <h2>🔎 Details</h2>
    <div class="small">Click a node/edge in the graph to inspect.</div>
    <div class="divider"></div>
    <div id="detail_box" class="small">(none)</div>
  </div>
</div>

<script>
let network=null, nodes=null, edges=null;
async function fetchJSON(url, opts){ const r = await fetch(url, opts||{}); return await r.json(); }

function channelColor(ch){
  if(!ch) return "#6b7280";
  if(ch.startsWith("drives")) return "#60a5fa";
  if(ch.startsWith("inverse")) return "#f87171";
  if(ch.startsWith("correlates")) return "#34d399";
  if(ch.startsWith("sentiment")) return "#a78bfa";
  if(ch.startsWith("policy")) return "#fbbf24";
  if(ch.startsWith("liquidity")) return "#38bdf8";
  return "#9ca3af";
}

async function initGraph(){
  const data = await fetchJSON("/graph-data");
  nodes = new vis.DataSet(data.nodes);
  edges = new vis.DataSet(data.edges);

  const container = document.getElementById("graph");
  const options = {
    interaction:{ hover:true, zoomView:true, dragView:true },
    nodes:{ shape:"dot", font:{size:10, color:"#e5e7eb"}, borderWidth:2 },
    edges:{ smooth:{type:"continuous"}, color:{ color:"#475569" } },
    physics:{ enabled:true, stabilization:{iterations:140, fit:true},
      barnesHut:{ gravitationalConstant:-2400, springLength:120, springConstant:0.004, avoidOverlap:0.35 } }
  };
  network = new vis.Network(container, {nodes, edges}, options);

  network.on("click", async (params)=>{
    if(params.nodes && params.nodes.length){
      const id = params.nodes[0];
      const d = await fetchJSON(`/node/${encodeURIComponent(id)}`);
      document.getElementById("detail_box").innerHTML =
        `<b>Node</b> ${d.node_id} · <span style="color:#a78bfa">${d.kind}</span><br/><b>${d.label}</b><br/>${d.description||""}<br/><br/>Degree: ${d.degree} · Score: ${d.score.toFixed(2)}`
        + `<div style="margin-top:10px;"><b>Top connections</b><br/>` + d.edges.map(e=>`• ${e.neighbor_label} — ${e.top_channel} (${e.weight.toFixed(2)})`).join("<br/>") + `</div>`;
    } else if(params.edges && params.edges.length){
      const eid = params.edges[0];
      const d = await fetchJSON(`/edge/${eid}`);
      document.getElementById("detail_box").innerHTML =
        `<b>Edge</b> #${d.edge_id}<br/>${d.a_label} ⟷ ${d.b_label}<br/>weight=${d.weight.toFixed(2)} · top=${d.top_channel||""}<br/><br/>`
        + `<b>Channels</b><br/>` + d.channels.map(c=>`• <span style="color:${channelColor(c.channel)}">${c.channel}</span>: ${c.strength.toFixed(2)}`).join("<br/>");
    }
  });
}

async function refreshGraph(){
  const data = await fetchJSON("/graph-data");
  nodes.clear(); edges.clear();
  nodes.add(data.nodes); edges.add(data.edges);
  if(network){ network.stabilize(60); }
}

async function refreshAll(){
  const st = await fetchJSON("/api/state");
  document.getElementById("k_nodes").textContent = st.nodes;
  document.getElementById("k_edges").textContent = st.edges;

  document.getElementById("bw_spy").textContent = st.latest.spy;
  document.getElementById("bw_qqq").textContent = st.latest.qqq;
  document.getElementById("bw_vix").textContent = st.latest.vix;
  document.getElementById("bw_uup").textContent = st.latest.uup;
  document.getElementById("sig_line").textContent = st.latest.signals;

  document.getElementById("pf_cash").textContent = st.portfolio.cash;
  document.getElementById("pf_equity").textContent = st.portfolio.equity;

  document.getElementById("llm_calls").textContent = `${st.llm.calls_used} / ${st.llm.calls_budget}`;
  document.getElementById("llm_err").textContent = st.llm.last_error || "";

  const mk = document.getElementById("market_badge");
  mk.className = "pill " + (st.market_running ? "on" : "off");
  mk.textContent = st.market_running ? "ON" : "OFF";
  const dr = document.getElementById("dream_badge");
  dr.className = "pill " + (st.dream_running ? "on" : "off");
  dr.textContent = st.dream_running ? "ON" : "OFF";
  const th = document.getElementById("think_badge");
  th.className = "pill " + (st.think_running ? "on" : "off");
  th.textContent = st.think_running ? "ON" : "OFF";
  const tr = document.getElementById("trade_badge");
  tr.className = "pill " + (st.auto_trade ? "on" : "off");
  tr.textContent = st.auto_trade ? "ON" : "OFF";

  document.querySelector("#pos_table tbody").innerHTML = st.portfolio.positions.map(p=>{
    return `<tr><td>${p.symbol}</td><td>${p.qty.toFixed(3)}</td><td>${p.last_price.toFixed(2)}</td><td>${p.pnl.toFixed(2)}</td></tr>`;
  }).join("");

  document.getElementById("log_box").innerHTML = st.logs.map(l=>{
    return `<div class="log"><b>${l.actor}</b> · <span style="color:#a78bfa">${l.action}</span><br/><span class="small">${l.ts}</span><br/>${l.detail||""}</div>`;
  }).join("");

  document.getElementById("insight_box").innerHTML = st.insights.map(ins=>{
    return `<div class="insight">
      <div class="title">${ins.title}</div>
      <div class="small">${ins.ts} · status=${ins.status}</div>
      <div style="margin-top:8px; white-space:pre-wrap;">${ins.body}</div>
      <div class="action"><b>Decisions:</b> <span class="small mono">${ins.decisions}</span></div>
      <div class="meta">
        <span>★ ${ins.critic_score.toFixed(2)} · conf ${ins.confidence.toFixed(2)}</span>
        <span><button class="btn gray" style="width:auto;padding:6px 10px;margin:0" onclick="approveInsight(${ins.insight_id})">Approve</button></span>
      </div>
    </div>`;
  }).join("");

  await refreshGraph();
}

async function marketStart(){ await fetchJSON("/api/market/start", {method:"POST"}); await refreshAll(); }
async function marketStop(){ await fetchJSON("/api/market/stop", {method:"POST"}); await refreshAll(); }
async function dreamStart(){ await fetchJSON("/api/dream/start", {method:"POST"}); await refreshAll(); }
async function dreamStop(){ await fetchJSON("/api/dream/stop", {method:"POST"}); await refreshAll(); }
async function thinkStart(){ await fetchJSON("/api/think/start", {method:"POST"}); await refreshAll(); }
async function thinkStop(){ await fetchJSON("/api/think/stop", {method:"POST"}); await refreshAll(); }
async function stepMarket(){ await fetchJSON("/api/market/step", {method:"POST"}); await refreshAll(); }
async function stepThink(){ await fetchJSON("/api/think/step", {method:"POST"}); await refreshAll(); }

async function approveInsight(id){
  await fetchJSON(`/api/insight/${id}/approve`, {method:"POST"});
  await refreshAll();
}

initGraph().then(()=>refreshAll());
setInterval(refreshAll, 7000);
</script>
</body></html>
"""

@app.route("/")
def index():
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()

        latest = {"spy": "—", "qqq": "—", "vix": "—", "uup": "—", "signals": "—"}
        prices = {}
        if snap:
            prices = json.loads(snap["prices_json"] or "{}")
            sig = json.loads(snap["signals_json"] or "{}")
            def fmt_sym(sym):
                if sym in prices:
                    return f"{prices[sym]['change_pct']:+.2f}%"
                return "—"
            latest = {
                "spy": fmt_sym("SPY"),
                "qqq": fmt_sym("QQQ"),
                "vix": fmt_sym("^VIX"),
                "uup": fmt_sym("UUP"),
                "signals": json.dumps(sig),
            }

        pf = portfolio_state(conn, prices=prices)
        logs = conn.execute("SELECT * FROM dream_log ORDER BY log_id DESC LIMIT 12").fetchall()
        insights = conn.execute("SELECT * FROM insights WHERE starred=1 ORDER BY insight_id DESC LIMIT 6").fetchall()
        llm = LLM_BUDGET.stats()

    def _ins_row(r):
        try:
            dec = json.loads(r["decisions_json"] or "[]")
        except Exception:
            dec = []
        return {
            "insight_id": int(r["insight_id"]),
            "ts": r["ts"],
            "title": r["title"],
            "body": r["body"],
            "decisions": json.dumps(dec)[:900],
            "critic_score": float(r["critic_score"]),
            "confidence": float(r["confidence"]),
            "status": r["status"],
        }

    return render_template_string(
        INDEX_HTML,
        node_count=node_count,
        edge_count=edge_count,
        market_running=MARKET.running,
        dream_running=DREAM.running,
        think_running=THINK.running,
        auto_trade=AUTO_TRADE,
        latest=latest,
        logs=[{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": r["detail"] or ""} for r in logs],
        insights=[_ins_row(r) for r in insights],
        portfolio={"cash": fmt_money(pf["cash"]), "equity": fmt_money(pf["equity"]), "positions": pf["positions"]},
        llm=llm,
    )

@app.route("/api/state")
def api_state():
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()

        latest = {"spy": "—", "qqq": "—", "vix": "—", "uup": "—", "signals": "{}"}
        prices = {}
        if snap:
            prices = json.loads(snap["prices_json"] or "{}")
            sig = json.loads(snap["signals_json"] or "{}")
            def fmt_sym(sym):
                if sym in prices:
                    return f"{prices[sym]['change_pct']:+.2f}%"
                return "—"
            latest = {
                "spy": fmt_sym("SPY"),
                "qqq": fmt_sym("QQQ"),
                "vix": fmt_sym("^VIX"),
                "uup": fmt_sym("UUP"),
                "signals": json.dumps(sig),
            }

        pf = portfolio_state(conn, prices=prices)
        logs = conn.execute("SELECT * FROM dream_log ORDER BY log_id DESC LIMIT 12").fetchall()
        insights = conn.execute("SELECT * FROM insights WHERE starred=1 ORDER BY insight_id DESC LIMIT 8").fetchall()
        llm = LLM_BUDGET.stats()

    def _ins_row(r):
        try:
            dec = json.loads(r["decisions_json"] or "[]")
        except Exception:
            dec = []
        return {
            "insight_id": int(r["insight_id"]),
            "ts": r["ts"],
            "title": r["title"],
            "body": r["body"],
            "decisions": json.dumps(dec)[:900],
            "critic_score": float(r["critic_score"]),
            "confidence": float(r["confidence"]),
            "status": r["status"],
        }

    return jsonify({
        "nodes": node_count,
        "edges": edge_count,
        "market_running": MARKET.running,
        "dream_running": DREAM.running,
        "think_running": THINK.running,
        "auto_trade": AUTO_TRADE,
        "latest": latest,
        "portfolio": {"cash": fmt_money(pf["cash"]), "equity": fmt_money(pf["equity"]), "positions": pf["positions"]},
        "llm": llm,
        "logs": [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": r["detail"] or ""} for r in logs],
        "insights": [_ins_row(r) for r in insights],
    })

@app.route("/graph-data")
def graph_data():
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        node_rows = conn.execute("""
          SELECT node_id, kind, label, score, degree
          FROM nodes
          ORDER BY (degree*1.0 + score*5.0) DESC
          LIMIT 160
        """).fetchall()
        node_ids = {r["node_id"] for r in node_rows}
        nodes = [{
            "id": r["node_id"],
            "label": r["label"],
            "value": int(r["degree"]) + 7,
            "title": f"{r['kind']} | deg={r['degree']} score={float(r['score']):.2f}",
            "color": {"border": kind_color(r["kind"]), "background": "#0b1220"},
        } for r in node_rows]

        edge_rows = conn.execute("SELECT edge_id, node_a, node_b, weight, top_channel FROM edges ORDER BY weight DESC LIMIT 520").fetchall()
        edges = []
        for e in edge_rows:
            if e["node_a"] in node_ids and e["node_b"] in node_ids:
                edges.append({
                    "id": int(e["edge_id"]),
                    "from": e["node_a"],
                    "to": e["node_b"],
                    "value": max(1, min(8, int(float(e["weight"]) * 3))),
                    "title": f"w={float(e['weight']):.2f} top={e['top_channel'] or ''}",
                    "color": {"color": edge_color(e["top_channel"] or "")},
                })
    return jsonify({"nodes": nodes, "edges": edges})

@app.route("/node/<path:node_id>")
def node_detail(node_id: str):
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        n = conn.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if not n:
            return jsonify({"error": "node not found"}), 404
        edges = conn.execute("""
          SELECT edge_id, node_a, node_b, weight, top_channel
          FROM edges
          WHERE node_a=? OR node_b=?
          ORDER BY weight DESC
          LIMIT 20
        """, (node_id, node_id)).fetchall()
        out_edges = []
        for e in edges:
            other = e["node_b"] if e["node_a"] == node_id else e["node_a"]
            on = conn.execute("SELECT label FROM nodes WHERE node_id=?", (other,)).fetchone()
            out_edges.append({
                "edge_id": int(e["edge_id"]),
                "neighbor": other,
                "neighbor_label": (on["label"] if on else other),
                "weight": float(e["weight"]),
                "top_channel": e["top_channel"] or ""
            })
        return jsonify({
            "node_id": n["node_id"],
            "kind": n["kind"],
            "label": n["label"],
            "description": n["description"] or "",
            "score": float(n["score"]),
            "degree": int(n["degree"]),
            "edges": out_edges
        })

@app.route("/edge/<int:edge_id>")
def edge_detail(edge_id: int):
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        e = conn.execute("SELECT * FROM edges WHERE edge_id=?", (edge_id,)).fetchone()
        if not e:
            return jsonify({"error": "edge not found"}), 404
        a = e["node_a"]; b = e["node_b"]
        la = conn.execute("SELECT label FROM nodes WHERE node_id=?", (a,)).fetchone()
        lb = conn.execute("SELECT label FROM nodes WHERE node_id=?", (b,)).fetchone()
        ch = conn.execute("SELECT channel, strength FROM edge_channels WHERE edge_id=? ORDER BY strength DESC", (edge_id,)).fetchall()
        return jsonify({
            "edge_id": int(edge_id),
            "a": a, "b": b,
            "a_label": (la["label"] if la else a),
            "b_label": (lb["label"] if lb else b),
            "weight": float(e["weight"]),
            "top_channel": e["top_channel"] or "",
            "channels": [{"channel": r["channel"], "strength": float(r["strength"])} for r in ch],
        })

# ---------------------- Control endpoints ----------------------

@app.post("/api/market/start")
def api_market_start():
    if not MARKET.running:
        MARKET.start()
    return jsonify({"ok": True, "running": MARKET.running})

@app.post("/api/market/stop")
def api_market_stop():
    MARKET.stop_now()
    return jsonify({"ok": True, "running": MARKET.running})

@app.post("/api/market/step")
def api_market_step():
    MARKET.step_once()
    return jsonify({"ok": True})

@app.post("/api/dream/start")
def api_dream_start():
    if not DREAM.running:
        DREAM.start()
    return jsonify({"ok": True, "running": DREAM.running})

@app.post("/api/dream/stop")
def api_dream_stop():
    DREAM.stop_now()
    return jsonify({"ok": True, "running": DREAM.running})

@app.post("/api/think/start")
def api_think_start():
    if not THINK.running:
        THINK.start()
    return jsonify({"ok": True, "running": THINK.running})

@app.post("/api/think/stop")
def api_think_stop():
    THINK.stop_now()
    return jsonify({"ok": True, "running": THINK.running})

@app.post("/api/think/step")
def api_think_step():
    THINK.step_once()
    return jsonify({"ok": True})

@app.post("/api/insight/<int:insight_id>/approve")
def api_insight_approve(insight_id: int):
    init_db()
    bootstrap_if_empty()
    with db_conn() as conn:
        ins = conn.execute("SELECT * FROM insights WHERE insight_id=?", (insight_id,)).fetchone()
        if not ins:
            return jsonify({"ok": False, "error": "insight not found"}), 404
        if ins["status"] == "applied":
            return jsonify({"ok": True, "message": "already applied"})

        snap = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (int(ins["evidence_snapshot_id"]),)).fetchone()
        if not snap:
            snap = conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        prices = json.loads((snap["prices_json"] if snap else "{}") or "{}")

        try:
            decisions = json.loads(ins["decisions_json"] or "[]")
        except Exception:
            decisions = []

        can_trade_now = TRADE_ANYTIME or (not market_is_open_et())
        if not can_trade_now:
            conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("queued", insight_id))
            log_event(conn, "trade", "approve_queued", f"id={insight_id} market_open=True")
            conn.commit()
            return jsonify({"ok": True, "status": "queued", "message": "market open; queued"})

        res = execute_paper_trades(conn, decisions, prices, reason=f"manual approve insight {insight_id}", insight_id=insight_id)
        conn.execute("UPDATE insights SET status=? WHERE insight_id=?", ("applied", insight_id))
        log_event(conn, "trade", "approve_applied", f"id={insight_id} executed={len(res['executed'])}")
        conn.commit()
        return jsonify({"ok": True, "status": "applied", "result": res})

# ---------------------- Main ----------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5062")))
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    init_db()
    bootstrap_if_empty()

    if AUTO_MARKET and not MARKET.running:
        MARKET.start()
    if AUTO_DREAM and not DREAM.running:
        DREAM.start()
    if AUTO_THINK and not THINK.running:
        THINK.start()

    logger.info(f"DB: {DB_PATH}")
    logger.info(f"Ollama: {OLLAMA_HOST} model={DREAM_MODEL}")
    logger.info(f"Universe: investibles={len(INVESTIBLES)} bells={len(BELLWETHERS)}")
    logger.info(f"Auto: MARKET={AUTO_MARKET} DREAM={AUTO_DREAM} THINK={AUTO_THINK} TRADE={AUTO_TRADE} TRADE_ANYTIME={TRADE_ANYTIME}")
    logger.info(f"UI: http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, debug=(args.debug or DEBUG), use_reloader=False, threaded=True)

if __name__ == "__main__":
    main()
