"""Separate LLM budget for options worker."""
import logging
import threading
import time
from collections import deque

from src.config import Config

logger = logging.getLogger("kginvest")


class OptionsBudget:
    """
    Rate limiter for options LLM calls with separate budget from main workers.
    
    Enforces OPTIONS_LLM_CALLS_PER_MIN limit using a sliding window approach.
    This allows options analysis to run independently without consuming
    main worker LLM budget.
    """
    
    def __init__(self):
        self.lock = threading.Lock()
        # Track call timestamps in sliding window
        self.calls = deque()
        self.window = 60.0  # 1 minute window
        self.limit = Config.OPTIONS_LLM_CALLS_PER_MIN
        self.blocked = 0
        self.allowed = 0
        self.last_error = None

    def acquire(self) -> bool:
        """
        Request permission to make an LLM call.
        
        Returns:
            True if call is allowed (within budget), False if rate limited
        """
        with self.lock:
            now = time.time()
            cutoff = now - self.window
            
            # Remove timestamps outside the sliding window
            while self.calls and self.calls[0] < cutoff:
                self.calls.popleft()
            
            # Check if we're within budget
            if len(self.calls) < self.limit:
                self.calls.append(now)
                self.allowed += 1
                self.last_error = None
                return True
            else:
                self.blocked += 1
                self.last_error = "rate_limited"
                if self.blocked % 5 == 1:  # Log every 5th block
                    logger.warning(
                        f"Options LLM budget exhausted: {len(self.calls)}/{self.limit} "
                        f"calls in last {self.window}s"
                    )
                return False

    def stats(self) -> dict:
        """
        Get current budget statistics.
        
        Returns:
            Dict with allowed, blocked, available, limit, last_error
        """
        with self.lock:
            now = time.time()
            cutoff = now - self.window
            
            # Clean up old timestamps
            while self.calls and self.calls[0] < cutoff:
                self.calls.popleft()
            
            used = len(self.calls)
            available = max(0, self.limit - used)
            
            return {
                "allowed": self.allowed,
                "blocked": self.blocked,
                "available": available,
                "used": used,
                "limit": self.limit,
                "window_seconds": self.window,
                "last_error": self.last_error
            }

    def reset(self):
        """Reset all counters (useful for testing)."""
        with self.lock:
            self.calls.clear()
            self.blocked = 0
            self.allowed = 0
            self.last_error = None


# Global singleton instance
OPTIONS_BUDGET = OptionsBudget()
