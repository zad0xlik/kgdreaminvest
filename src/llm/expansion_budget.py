"""Budget management for LLM-powered portfolio expansion.

This module provides a separate budget tracker for stock expansion LLM calls,
independent from the worker LLM budget. This ensures expansion doesn't interfere
with the regular worker operations.
"""
import threading
import time
from typing import Any, Dict, Optional


class ExpansionBudget:
    """
    Rate limiter for LLM API calls during portfolio expansion.
    
    Separate from worker LLM budget to ensure expansion operations
    don't consume the worker's API call quota.
    
    Uses a sliding window approach with automatic reset.
    """
    
    def __init__(self, calls_per_min: int):
        """
        Initialize expansion budget tracker.
        
        Args:
            calls_per_min: Maximum allowed API calls per minute for expansion
        """
        self.calls_per_min = max(1, int(calls_per_min))
        self.lock = threading.Lock()
        self.window_start = time.time()
        self.calls = 0
        self.last_error: Optional[str] = None
        self.total_calls = 0  # Track total calls across all windows

    def _reset_if_needed(self):
        """Reset call counter if minute window has passed."""
        now = time.time()
        if now - self.window_start >= 60.0:
            self.window_start = now
            self.calls = 0

    def acquire(self) -> bool:
        """
        Attempt to acquire permission for one expansion LLM call.
        
        Returns:
            True if call is allowed, False if budget exhausted
        """
        with self.lock:
            self._reset_if_needed()
            if self.calls >= self.calls_per_min:
                return False
            self.calls += 1
            self.total_calls += 1
            return True

    def wait_and_acquire(self, timeout: float = 60.0) -> bool:
        """
        Wait for budget availability and acquire permission.
        
        Args:
            timeout: Maximum seconds to wait for budget
            
        Returns:
            True if acquired, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire():
                return True
            time.sleep(1.0)
        return False

    def stats(self) -> Dict[str, Any]:
        """
        Get current budget statistics.
        
        Returns:
            Dict with calls_used, calls_budget, total_calls, last_error
        """
        with self.lock:
            self._reset_if_needed()
            return {
                "calls_used": self.calls,
                "calls_budget": self.calls_per_min,
                "total_calls": self.total_calls,
                "last_error": self.last_error
            }

    def set_error(self, error: str):
        """Record the last error encountered."""
        with self.lock:
            self.last_error = error
