"""Utility functions for KGDreamInvest."""

import datetime as dt
import json
import logging
import math
import re
import time
import threading
from typing import Any, Dict, Optional

from src.config import Config

logger = logging.getLogger("kginvest")


def now_et() -> dt.datetime:
    """Get current time in ET timezone."""
    return dt.datetime.now(Config.ET)


def utc_now() -> str:
    """Get current UTC time as ISO string."""
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def today_et_str() -> str:
    """Get today's date in ET as ISO string."""
    return now_et().date().isoformat()


def clamp01(x: float) -> float:
    """Clamp value to [0, 1] range."""
    return max(0.0, min(1.0, float(x)))


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def jitter_sleep(total: float, stop: threading.Event, step: float = 0.25):
    """Sleep for a total duration in small steps, checking stop event."""
    elapsed = 0.0
    while elapsed < total and not stop.is_set():
        time.sleep(min(step, total - elapsed))
        elapsed += step


def find_outermost_json(s: str) -> Optional[str]:
    """Find the outermost JSON object in a string."""
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


def extract_json_from_markdown(s: str) -> Optional[str]:
    """Extract JSON from markdown code blocks like ```json {...} ```"""
    # Look for ```json ... ``` blocks
    json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    match = re.search(json_pattern, s or "", re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Look for ``` ... ``` blocks that might contain JSON
    general_pattern = r'```\s*(\{.*?\})\s*```'
    match = re.search(general_pattern, s or "", re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return None


def extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """Enhanced JSON extraction with multiple fallback methods."""
    if not raw:
        logger.warning("extract_json: empty input")
        return None
    
    logger.debug(f"extract_json: input length {len(raw)}, first 200 chars: {raw[:200]}")
    
    # Method 1: Find outermost JSON object directly
    blob = find_outermost_json(raw)
    if blob:
        try:
            result = json.loads(blob)
            logger.debug(f"extract_json: success with find_outermost_json, keys: {list(result.keys()) if isinstance(result, dict) else 'not_dict'}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"extract_json: JSON parse error with find_outermost: {e}")
    
    # Method 2: Extract from markdown code blocks
    markdown_json = extract_json_from_markdown(raw)
    if markdown_json:
        try:
            result = json.loads(markdown_json)
            logger.debug(f"extract_json: success with markdown extraction, keys: {list(result.keys()) if isinstance(result, dict) else 'not_dict'}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"extract_json: JSON parse error with markdown: {e}")
    
    # Method 3: Try to find any JSON-like structure with regex
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, raw, re.DOTALL)
    for match in matches:
        try:
            result = json.loads(match)
            logger.debug(f"extract_json: success with regex fallback, keys: {list(result.keys()) if isinstance(result, dict) else 'not_dict'}")
            return result
        except json.JSONDecodeError:
            continue
    
    logger.error(f"extract_json: failed all methods. Raw response: {raw}")
    return None


def fmt_money(x: float) -> str:
    """Format a number as money."""
    return f"${x:,.2f}"


def market_is_open_et(ts: Optional[dt.datetime] = None) -> bool:
    """
    Check if market is open (NYSE regular hours: 9:30-16:00 ET, Mon-Fri).
    This is a toy check that ignores holidays.
    """
    t = ts or now_et()
    # Weekend check
    if t.weekday() >= 5:
        return False
    # Market hours check
    h = t.hour + t.minute / 60.0
    return (h >= 9.5) and (h < 16.0)
