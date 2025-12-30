"""Prompt loader and manager for LLM interactions."""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("kginvest")

# Cache for loaded prompts (hot-reload support)
_PROMPT_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_prompts_dir() -> Path:
    """Get the prompts directory path."""
    return Path(__file__).parent.parent / "prompts"


def load_prompts(category: str, force_reload: bool = False) -> Dict[str, Any]:
    """
    Load prompts from JSON file.
    
    Args:
        category: Prompt category (expansion, dream, think)
        force_reload: If True, bypass cache and reload from disk
        
    Returns:
        Dictionary of prompts for the category
    """
    cache_key = f"{category}_prompts"
    
    # Return cached version unless force reload
    if not force_reload and cache_key in _PROMPT_CACHE:
        return _PROMPT_CACHE[cache_key]
    
    prompts_file = _get_prompts_dir() / f"{category}_prompts.json"
    
    try:
        with open(prompts_file, 'r') as f:
            prompts = json.load(f)
        
        _PROMPT_CACHE[cache_key] = prompts
        logger.info(f"Loaded {len(prompts)} prompts from {category}_prompts.json")
        return prompts
    
    except FileNotFoundError:
        logger.error(f"Prompts file not found: {prompts_file}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {prompts_file}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading prompts from {prompts_file}: {e}")
        return {}


def save_prompts(category: str, prompts: Dict[str, Any]) -> bool:
    """
    Save prompts to JSON file.
    
    Args:
        category: Prompt category (expansion, dream, think)
        prompts: Dictionary of prompts to save
        
    Returns:
        True if successful, False otherwise
    """
    prompts_file = _get_prompts_dir() / f"{category}_prompts.json"
    
    try:
        # Ensure prompts directory exists
        prompts_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(prompts_file, 'w') as f:
            json.dump(prompts, f, indent=2)
        
        # Update cache
        _PROMPT_CACHE[f"{category}_prompts"] = prompts
        logger.info(f"Saved {len(prompts)} prompts to {category}_prompts.json")
        return True
    
    except Exception as e:
        logger.error(f"Error saving prompts to {prompts_file}: {e}")
        return False


def get_prompt(category: str, prompt_name: str, force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get a specific prompt by category and name.
    
    Args:
        category: Prompt category (expansion, dream, think)
        prompt_name: Name of the prompt
        force_reload: If True, reload from disk
        
    Returns:
        Prompt dictionary with 'system', 'user_template', 'description' keys
    """
    prompts = load_prompts(category, force_reload=force_reload)
    return prompts.get(prompt_name)


def format_prompt(template: str, **kwargs) -> str:
    """
    Format a prompt template with provided keyword arguments.
    
    Args:
        template: Prompt template string with {variable} placeholders
        **kwargs: Variables to substitute into template
        
    Returns:
        Formatted prompt string
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.error(f"Missing template variable: {e}")
        return template
    except Exception as e:
        logger.error(f"Error formatting prompt template: {e}")
        return template


def list_all_prompts() -> Dict[str, Dict[str, Any]]:
    """
    List all available prompts across all categories.
    
    Returns:
        Dictionary with category -> prompts mapping
    """
    categories = ["expansion", "dream", "think"]
    all_prompts = {}
    
    for category in categories:
        prompts = load_prompts(category)
        if prompts:
            all_prompts[category] = prompts
    
    return all_prompts


def reload_all_prompts():
    """Force reload all prompts from disk (clears cache)."""
    global _PROMPT_CACHE
    _PROMPT_CACHE.clear()
    logger.info("Cleared prompt cache - next access will reload from disk")
