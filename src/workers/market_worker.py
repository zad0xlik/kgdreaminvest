"""Market Worker - Fetches prices, computes indicators, and creates snapshots."""
import json
import logging
import threading
import traceback
from typing import Optional

from src.config import Config
from src.database import db_conn, log_event, get_active_investibles, get_active_bellwethers
from src.market import last_close_many, compute_indicators, compute_signals_from_bells
from src.utils import utc_now, jitter_sleep

logger = logging.getLogger("kginvest")


class MarketWorker:
    """
    Background worker that fetches market data and creates snapshots.
    
    Runs in a loop at configured interval (MARKET_INTERVAL).
    Each cycle:
    1. Fetches prices for all tickers from Yahoo Finance
    2. Computes technical indicators for investibles
    3. Computes regime signals from bellwethers
    4. Stores snapshot in database
    5. Marks-to-market existing positions
    """
    
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = {
            "ticks": 0,
            "last_ts": None,
            "last_ok": None,
            "last_error": None
        }

    def start(self):
        """Start the worker thread."""
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("MarketWorker started")

    def stop_now(self):
        """Stop the worker thread."""
        self.running = False
        self.stop.set()
        logger.info("MarketWorker stop signaled")

    def _loop(self):
        """Main worker loop."""
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
            
            jitter_sleep(Config.MARKET_INTERVAL, self.stop)

    def step_once(self):
        """Execute one market data fetch cycle with hybrid data sources."""
        # Get enabled tickers from database (fallback to config)
        investibles = get_active_investibles()
        bellwethers = get_active_bellwethers()
        
        # Primary tickers (investibles + universal bellwethers) via configured DATA_PROVIDER
        primary_tickers = list(set(investibles + Config.BELLWETHERS))
        
        # Fetch primary tickers via configured DATA_PROVIDER (Alpaca or Yahoo)
        prices = last_close_many(primary_tickers, max_workers=min(10, len(primary_tickers)))
        
        # ALWAYS fetch Yahoo-specific bellwethers via Yahoo Finance (regardless of DATA_PROVIDER)
        # These are indices, futures, forex that Alpaca doesn't support
        if Config.BELLWETHERS_YF:
            from src.market import last_close_many_yahoo
            yahoo_prices = last_close_many_yahoo(
                Config.BELLWETHERS_YF, 
                max_workers=min(5, len(Config.BELLWETHERS_YF))
            )
            # Merge Yahoo-specific data into main prices dict
            prices.update(yahoo_prices)
            logger.debug(
                f"Fetched {len(yahoo_prices)} Yahoo-specific bellwethers: "
                f"{', '.join(yahoo_prices.keys())}"
            )
        
        if not prices:
            raise RuntimeError("Fetch returned no prices")

        # Compute indicators for enabled investibles only
        indicators = {}
        for t in investibles:
            p = prices.get(t)
            if not p:
                continue
            closes = p.get("history") or []
            indicators[t] = compute_indicators(closes)

        # Extract bellwether prices
        bells = {b: prices[b] for b in bellwethers if b in prices}
        
        # Compute regime signals (function handles missing tickers gracefully)
        signals = compute_signals_from_bells(prices)

        # Store snapshot and log ticker lookups
        with db_conn() as conn:
            # Mark-to-market positions with current prices
            for sym, pdata in prices.items():
                if "current" in pdata:
                    conn.execute(
                        "UPDATE positions SET last_price=?, updated_at=? WHERE symbol=?",
                        (float(pdata["current"]), utc_now(), sym)
                    )
            
            # Log ticker lookups for diagnostics
            for sym, pdata in prices.items():
                conn.execute(
                    "INSERT INTO ticker_lookups(ts, ticker, success, price, change_pct, volume) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        utc_now(),
                        sym,
                        1,  # success
                        float(pdata.get("current", 0.0)),
                        float(pdata.get("change_pct", 0.0)),
                        int(pdata.get("volume", 0))
                    )
                )

            # Create snapshot
            conn.execute(
                "INSERT INTO snapshots(ts, prices_json, bells_json, indicators_json, signals_json) "
                "VALUES(?,?,?,?,?)",
                (
                    utc_now(),
                    json.dumps(prices),
                    json.dumps(bells),
                    json.dumps(indicators),
                    json.dumps(signals)
                )
            )
            snap_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
            
            log_event(
                conn,
                "market",
                "tick",
                f"snapshot_id={snap_id} have={len(prices)}/{len(Config.ALL_TICKERS)}"
            )
            
            # Keep last N snapshots (prevent database bloat)
            conn.execute(
                "DELETE FROM snapshots WHERE snapshot_id < "
                "(SELECT MAX(snapshot_id) - 1500 FROM snapshots)"
            )
            
            conn.commit()


# Global instance
MARKET = MarketWorker()
