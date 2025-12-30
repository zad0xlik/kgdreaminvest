"""LLM budget and rate limiting."""
import threading
import time
from typing import Any, Dict, Optional

from src.config import LLM_CALLS_PER_MIN


class LLMBudget:
    """
    Rate limiter for LLM API calls.
    
    Tracks calls per minute to prevent API rate limit violations.
    Uses a sliding window approach with automatic reset.
    """
    
    def __init__(self, calls_per_min: int):
        """
        Initialize LLM budget tracker.
        
        Args:
            calls_per_min: Maximum allowed API calls per minute
        """
        self.calls_per_min = max(1, int(calls_per_min))
        self.lock = threading.Lock()
        self.window_start = time.time()
        self.calls = 0
        self.last_error: Optional[str] = None

    def _reset_if_needed(self):
        """Reset call counter if minute window has passed."""
        now = time.time()
        if now - self.window_start >= 60.0:
            self.window_start = now
            self.calls = 0

    def acquire(self) -> bool:
        """
        Attempt to acquire permission for one LLM call.
        
        Returns:
            True if call is allowed, False if budget exhausted
        """
        with self.lock:
            self._reset_if_needed()
            if self.calls >= self.calls_per_min:
                return False
            self.calls += 1
            return True

    def stats(self) -> Dict[str, Any]:
        """
        Get current budget statistics.
        
        Returns:
            Dict with calls_used, calls_budget, last_error
        """
        with self.lock:
            self._reset_if_needed()
            return {
                "calls_used": self.calls,
                "calls_budget": self.calls_per_min,
                "last_error": self.last_error
            }


# Global LLM budget instance
LLM_BUDGET = LLMBudget(LLM_CALLS_PER_MIN)
