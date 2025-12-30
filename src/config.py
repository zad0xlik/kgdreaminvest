"""Configuration management for KGDreamInvest."""

import os
from pathlib import Path

import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Centralized configuration for the application."""
    
    # Timezone
    ET = pytz.timezone("America/New_York")
    
    # Data directory
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Database
    DB_PATH = Path(os.environ.get("KGINVEST_DB", str(DATA_DIR / "kginvest_live.db")))
    
    # LLM Provider Configuration
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()  # "ollama" or "openrouter"
    
    # Ollama Configuration
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    DREAM_MODEL = os.environ.get("DREAM_MODEL", "gemma3:4b")
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    # Debug mode
    DEBUG = os.environ.get("KGINVEST_DEBUG", "").lower() in ("1", "true", "yes")
    
    # Load investibles from environment or use default
    _investibles_default = "XLE,XLF,XLV,XME,IYT,AAPL,MSFT,JPM,UNH,CAT,NVDA,AMD,AMZN,GOOGL,META,ARCB,TTMI,TRMK,KWR,ICUI,ACHR,BBAI,ASTS,JOBY,LUNR,OKLO,LAC,INTC,APLD,F,PSNY,PSFE,U,LCID,SMR,WOLF,BYND,AIG"
    _investibles_env = os.environ.get("INVESTIBLES", _investibles_default)
    INVESTIBLES = [ticker.strip().upper() for ticker in _investibles_env.split(",") if ticker.strip()]
   
    # Load bellwethers from environment or use default
    _bellwethers_env = os.environ.get("BELLWETHERS", "^VIX,SPY,QQQ,TLT,UUP,^TNX,CL=F,TSM,VTI")
    BELLWETHERS = [ticker.strip().upper() for ticker in _bellwethers_env.split(",") if ticker.strip()]
    
    ALL_TICKERS = sorted(set(INVESTIBLES + BELLWETHERS))
    
    # Speeds (ticks/min)
    MARKET_SPEED = float(os.environ.get("MARKET_SPEED", "0.35"))   # ~ every 3 minutes
    DREAM_SPEED = float(os.environ.get("DREAM_SPEED", "0.25"))     # ~ every 4 minutes
    THINK_SPEED = float(os.environ.get("THINK_SPEED", "0.20"))     # ~ every 5 minutes
    
    MARKET_INTERVAL = 60.0 / max(0.05, MARKET_SPEED)
    DREAM_INTERVAL = 60.0 / max(0.05, DREAM_SPEED)
    THINK_INTERVAL = 60.0 / max(0.05, THINK_SPEED)
    
    # Unified LLM budget
    LLM_CALLS_PER_MIN = int(os.environ.get("LLM_CALLS_PER_MIN", "8"))
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "45"))
    LLM_TEMP = float(os.environ.get("LLM_TEMP", "0.25"))
    LLM_MAX_REASK = int(os.environ.get("LLM_MAX_REASK", "1"))
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4000"))
    
    # Autonomy toggles
    AUTO_MARKET = os.environ.get("AUTO_MARKET", "1").lower() in ("1", "true", "yes")
    AUTO_DREAM = os.environ.get("AUTO_DREAM", "1").lower() in ("1", "true", "yes")
    AUTO_THINK = os.environ.get("AUTO_THINK", "1").lower() in ("1", "true", "yes")
    AUTO_TRADE = os.environ.get("AUTO_TRADE", "1").lower() in ("1", "true", "yes")
    
    # Trading guard rails (paper)
    START_CASH = float(os.environ.get("START_CASH", "10000.0"))
    MIN_TRADE_NOTIONAL = float(os.environ.get("MIN_TRADE_NOTIONAL", "25.0"))
    MAX_BUY_EQUITY_PCT_PER_CYCLE = float(os.environ.get("MAX_BUY_EQUITY_PCT_PER_CYCLE", "18.0"))
    MAX_SELL_HOLDING_PCT_PER_CYCLE = float(os.environ.get("MAX_SELL_HOLDING_PCT_PER_CYCLE", "35.0"))
    MAX_SYMBOL_WEIGHT_PCT = float(os.environ.get("MAX_SYMBOL_WEIGHT_PCT", "14.0"))
    MIN_CASH_BUFFER_PCT = float(os.environ.get("MIN_CASH_BUFFER_PCT", "12.0"))
    
    # Trading window
    TRADE_ANYTIME = os.environ.get("TRADE_ANYTIME", "0").lower() in ("1", "true", "yes")
    
    # Yahoo fetch
    YAHOO_TIMEOUT = int(os.environ.get("YAHOO_TIMEOUT", "12"))
    YAHOO_RANGE_DAYS = int(os.environ.get("YAHOO_RANGE_DAYS", "90"))
    YAHOO_CACHE_SECONDS = int(os.environ.get("YAHOO_CACHE_SECONDS", "90"))
    
    # Insight starring
    STAR_THRESHOLD = float(os.environ.get("STAR_THRESHOLD", "0.72"))
    EXPLANATION_MIN_LENGTH = int(os.environ.get("EXPLANATION_MIN_LENGTH", "180"))
    
    # Flask server
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5062"))
    SECRET_KEY = os.environ.get("SECRET_KEY", "kginvest-live-secret-change-me")


# Export commonly used config values at module level for convenience
ET = Config.ET
DATA_DIR = Config.DATA_DIR
DB_PATH = Config.DB_PATH

# LLM
LLM_PROVIDER = Config.LLM_PROVIDER
OLLAMA_HOST = Config.OLLAMA_HOST
DREAM_MODEL = Config.DREAM_MODEL
OPENROUTER_API_KEY = Config.OPENROUTER_API_KEY
OPENROUTER_BASE_URL = Config.OPENROUTER_BASE_URL
LLM_CALLS_PER_MIN = Config.LLM_CALLS_PER_MIN
LLM_TIMEOUT = Config.LLM_TIMEOUT
LLM_TEMP = Config.LLM_TEMP
LLM_MAX_REASK = Config.LLM_MAX_REASK
LLM_MAX_TOKENS = Config.LLM_MAX_TOKENS

# Universe
INVESTIBLES = Config.INVESTIBLES
BELLWETHERS = Config.BELLWETHERS
ALL_TICKERS = Config.ALL_TICKERS

# Intervals
MARKET_INTERVAL = Config.MARKET_INTERVAL
DREAM_INTERVAL = Config.DREAM_INTERVAL
THINK_INTERVAL = Config.THINK_INTERVAL

# Autonomy
AUTO_MARKET = Config.AUTO_MARKET
AUTO_DREAM = Config.AUTO_DREAM
AUTO_THINK = Config.AUTO_THINK
AUTO_TRADE = Config.AUTO_TRADE

# Trading
START_CASH = Config.START_CASH
MIN_TRADE_NOTIONAL = Config.MIN_TRADE_NOTIONAL
MAX_BUY_EQUITY_PCT_PER_CYCLE = Config.MAX_BUY_EQUITY_PCT_PER_CYCLE
MAX_SELL_HOLDING_PCT_PER_CYCLE = Config.MAX_SELL_HOLDING_PCT_PER_CYCLE
MAX_SYMBOL_WEIGHT_PCT = Config.MAX_SYMBOL_WEIGHT_PCT
MIN_CASH_BUFFER_PCT = Config.MIN_CASH_BUFFER_PCT
TRADE_ANYTIME = Config.TRADE_ANYTIME

# Yahoo
YAHOO_TIMEOUT = Config.YAHOO_TIMEOUT
YAHOO_RANGE_DAYS = Config.YAHOO_RANGE_DAYS
YAHOO_CACHE_SECONDS = Config.YAHOO_CACHE_SECONDS

# Insights
STAR_THRESHOLD = Config.STAR_THRESHOLD
EXPLANATION_MIN_LENGTH = Config.EXPLANATION_MIN_LENGTH

# Debug
DEBUG = Config.DEBUG
