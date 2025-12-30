#!/usr/bin/env python3
"""Main entry point for KGDreamInvest."""

import argparse
import logging
import sys

from src.config import Config
from src.database import init_db, bootstrap_if_empty
from src.workers import MARKET, DREAM, THINK
from src.backend import create_app

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if Config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(Config.DATA_DIR / "kginvest_live.log"))
    ],
)
logger = logging.getLogger("kginvest")


def main():
    """Main application entry point."""
    ap = argparse.ArgumentParser(description="KGDreamInvest - Multi-agent investing system")
    ap.add_argument("--host", default=Config.HOST, help="Host to bind the server to")
    ap.add_argument("--port", type=int, default=Config.PORT, help="Port to run the server on")
    ap.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = ap.parse_args()

    # Initialize database
    logger.info("Initializing database...")
    init_db()
    bootstrap_if_empty()

    # Start workers if auto-enabled
    if Config.AUTO_MARKET and not MARKET.running:
        logger.info("Auto-starting Market worker...")
        MARKET.start()
    if Config.AUTO_DREAM and not DREAM.running:
        logger.info("Auto-starting Dream worker...")
        DREAM.start()
    if Config.AUTO_THINK and not THINK.running:
        logger.info("Auto-starting Think worker...")
        THINK.start()

    # Log configuration
    logger.info("=" * 60)
    logger.info("KGDreamInvest (Live/Paper)")
    logger.info("=" * 60)
    logger.info(f"DB: {Config.DB_PATH}")
    logger.info(f"LLM Provider: {Config.LLM_PROVIDER}")
    logger.info(f"Model: {Config.DREAM_MODEL}")
    logger.info(f"Universe: investibles={len(Config.INVESTIBLES)} bells={len(Config.BELLWETHERS)}")
    logger.info(f"Auto: MARKET={Config.AUTO_MARKET} DREAM={Config.AUTO_DREAM} THINK={Config.AUTO_THINK} TRADE={Config.AUTO_TRADE}")
    logger.info(f"Trade Window: ANYTIME={Config.TRADE_ANYTIME}")
    logger.info(f"UI: http://{args.host}:{args.port}")
    logger.info("=" * 60)

    # Create and run Flask app
    app = create_app()
    app.run(
        host=args.host,
        port=args.port,
        debug=(args.debug or Config.DEBUG),
        use_reloader=False,  # Disable reloader to prevent worker thread issues
        threaded=True
    )


if __name__ == "__main__":
    main()
