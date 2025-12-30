"""LLM provider implementations for Ollama and OpenRouter."""
import logging
from typing import Dict, Any, Optional, Tuple

import requests

from src.config import Config
from src.utils import extract_json

logger = logging.getLogger("kginvest")

# Check if OpenRouter dependencies are available
try:
    from langchain_openai import ChatOpenAI
    LANGCHAIN_OPENAI_AVAILABLE = True
except ImportError:
    LANGCHAIN_OPENAI_AVAILABLE = False


def ollama_chat_json(
    system: str,
    user: str,
    budget
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Call Ollama API with JSON-only outputs.
    
    Includes robust re-ask on invalid JSON using the budget's max_reask setting.
    
    Args:
        system: System prompt
        user: User prompt
        budget: LLMBudget instance for rate limiting
        
    Returns:
        Tuple of (parsed_json_dict, raw_response_string)
        Returns (None, raw) if JSON parsing fails after all attempts
    """
    if not budget.acquire():
        logger.warning("ollama_chat_json: LLM budget exhausted")
        return None, None
    
    url = f"{Config.OLLAMA_HOST}/api/chat"
    logger.info(f"ollama_chat_json: calling Ollama at {url} with model {Config.DREAM_MODEL}")
    
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]
    
    payload = {
        "model": Config.DREAM_MODEL,
        "messages": msgs,
        "stream": False,
        "options": {"temperature": Config.LLM_TEMP}
    }

    def _call(messages):
        """Internal helper to make API call."""
        logger.debug(f"ollama_chat_json: POST to {url} with {len(messages)} messages")
        r = requests.post(
            url,
            json={**payload, "messages": messages},
            timeout=Config.LLM_TIMEOUT
        )
        if r.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        response_data = r.json()
        content = ((response_data.get("message", {}) or {}).get("content", "") or "")
        logger.debug(f"ollama_chat_json: received {len(content)} chars response")
        return content

    try:
        raw = _call(msgs)
        logger.debug(f"ollama_chat_json: raw response preview: {raw[:300]}...")
        
        # Try to parse JSON
        parsed = extract_json(raw)
        if parsed is not None:
            logger.info("ollama_chat_json: successful JSON parse on first attempt")
            budget.last_error = None
            return parsed, raw

        # Re-ask if JSON extraction failed
        logger.warning("ollama_chat_json: initial JSON parse failed, attempting repairs")
        for attempt in range(max(0, Config.LLM_MAX_REASK)):
            repair = "Your prior output was not valid JSON. Respond with ONLY one valid JSON object; no extra text."
            logger.debug(f"ollama_chat_json: repair attempt {attempt + 1}")
            raw2 = _call(msgs + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair}
            ])
            logger.debug(f"ollama_chat_json: repair response preview: {raw2[:300]}...")
            
            parsed2 = extract_json(raw2)
            if parsed2 is not None:
                logger.info(f"ollama_chat_json: successful JSON parse on repair attempt {attempt + 1}")
                budget.last_error = None
                return parsed2, raw2
            raw = raw2

        logger.error(f"ollama_chat_json: all JSON extraction attempts failed. Final raw response: {raw}")
        budget.last_error = "parse_fail"
        return None, raw
        
    except Exception as e:
        logger.error(f"ollama_chat_json: exception during call: {e}")
        budget.last_error = str(e)
        return None, None


def openrouter_chat_json(
    system: str,
    user: str,
    budget
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Call OpenRouter API with JSON-only outputs.
    
    Includes robust re-ask on invalid JSON using the budget's max_reask setting.
    
    Args:
        system: System prompt
        user: User prompt
        budget: LLMBudget instance for rate limiting
        
    Returns:
        Tuple of (parsed_json_dict, raw_response_string)
        Returns (None, raw) if JSON parsing fails after all attempts
    """
    if not budget.acquire():
        logger.warning("openrouter_chat_json: LLM budget exhausted")
        return None, None
    
    if not LANGCHAIN_OPENAI_AVAILABLE:
        logger.error("openrouter_chat_json: langchain-openai not available")
        budget.last_error = "langchain-openai not available"
        return None, None
    
    if not Config.OPENROUTER_API_KEY:
        logger.error("openrouter_chat_json: OPENROUTER_API_KEY not set")
        budget.last_error = "OPENROUTER_API_KEY not set"
        return None, None
    
    logger.info(f"openrouter_chat_json: calling OpenRouter at {Config.OPENROUTER_BASE_URL} with model {Config.DREAM_MODEL}")
    
    try:
        # Initialize OpenRouter client
        client = ChatOpenAI(
            model=Config.DREAM_MODEL,
            openai_api_base=Config.OPENROUTER_BASE_URL,
            openai_api_key=Config.OPENROUTER_API_KEY,
            temperature=Config.LLM_TEMP,
            max_tokens=1000,
            timeout=Config.LLM_TIMEOUT,
            default_headers={
                "HTTP-Referer": "https://github.com/DormantOne/kgdreaminvest",
                "X-Title": "KGDreamInvest"
            }
        )
        
        # Call the model
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        
        logger.debug(f"openrouter_chat_json: invoking model with {len(messages)} messages")
        response = client.invoke(messages)
        raw = response.content if hasattr(response, 'content') else str(response)
        logger.debug(f"openrouter_chat_json: received {len(raw)} chars response")
        logger.debug(f"openrouter_chat_json: raw response preview: {raw[:300]}...")
        
        # Try to extract JSON
        parsed = extract_json(raw)
        if parsed is not None:
            logger.info("openrouter_chat_json: successful JSON parse on first attempt")
            budget.last_error = None
            return parsed, raw

        # Re-ask if JSON extraction failed
        logger.warning("openrouter_chat_json: initial JSON parse failed, attempting repairs")
        for attempt in range(max(0, Config.LLM_MAX_REASK)):
            repair = "Your prior output was not valid JSON. Respond with ONLY one valid JSON object; no extra text."
            messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair}
            ])
            logger.debug(f"openrouter_chat_json: repair attempt {attempt + 1}")
            response = client.invoke(messages)
            raw2 = response.content if hasattr(response, 'content') else str(response)
            logger.debug(f"openrouter_chat_json: repair response preview: {raw2[:300]}...")
            
            parsed2 = extract_json(raw2)
            if parsed2 is not None:
                logger.info(f"openrouter_chat_json: successful JSON parse on repair attempt {attempt + 1}")
                budget.last_error = None
                return parsed2, raw2
            raw = raw2

        logger.error(f"openrouter_chat_json: all JSON extraction attempts failed. Final raw response: {raw}")
        budget.last_error = "parse_fail"
        return None, raw
        
    except Exception as e:
        logger.error(f"openrouter_chat_json: exception during call: {e}")
        budget.last_error = str(e)
        return None, None
