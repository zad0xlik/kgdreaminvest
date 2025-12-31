"""Unified LLM interface."""
from typing import Dict, Any, Optional, Tuple

from src.config import Config
from src.llm.budget import LLMBudget
from src.llm.providers import ollama_chat_json, openrouter_chat_json

# Global budget instance
LLM_BUDGET = LLMBudget(Config.LLM_CALLS_PER_MIN)


def llm_chat_json(system: str, user: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Unified LLM interface that supports both Ollama and OpenRouter.
    
    Routes to the appropriate provider based on Config.LLM_PROVIDER setting.
    Uses the global LLM_BUDGET for rate limiting.
    
    Args:
        system: System prompt
        user: User prompt
        
    Returns:
        Tuple of (parsed_json_dict, raw_response_string)
        Returns (None, None) or (None, raw) on failure
        
    Example:
        >>> parsed, raw = llm_chat_json(
        ...     "You are a helpful assistant.",
        ...     "List 3 colors in JSON: {\"colors\": [...]}"
        ... )
        >>> if parsed:
        ...     print(parsed["colors"])
    """
    if Config.LLM_PROVIDER == "openrouter":
        return openrouter_chat_json(system, user, LLM_BUDGET)
    else:
        # Default to Ollama
        return ollama_chat_json(system, user, LLM_BUDGET)
