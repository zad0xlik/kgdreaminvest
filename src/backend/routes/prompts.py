"""API routes for LLM prompt management."""

import logging
from flask import Blueprint, jsonify, request

from src.llm.prompts import (
    list_all_prompts,
    get_prompt,
    save_prompts,
    load_prompts,
    reload_all_prompts
)

logger = logging.getLogger("kginvest")

bp = Blueprint("prompts", __name__, url_prefix="/api/prompts")


@bp.route("", methods=["GET"])
def get_all_prompts():
    """Get all prompts across all categories."""
    try:
        prompts = list_all_prompts()
        return jsonify({
            "success": True,
            "prompts": prompts
        })
    except Exception as e:
        logger.error(f"Error getting prompts: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/<category>", methods=["GET"])
def get_category_prompts(category):
    """Get all prompts for a specific category."""
    try:
        prompts = load_prompts(category, force_reload=True)
        if not prompts:
            return jsonify({"error": f"No prompts found for category: {category}"}), 404
        
        return jsonify({
            "success": True,
            "category": category,
            "prompts": prompts
        })
    except Exception as e:
        logger.error(f"Error getting prompts for {category}: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/<category>/<prompt_name>", methods=["GET"])
def get_single_prompt(category, prompt_name):
    """Get a specific prompt by category and name."""
    try:
        prompt = get_prompt(category, prompt_name, force_reload=True)
        if not prompt:
            return jsonify({
                "error": f"Prompt not found: {category}/{prompt_name}"
            }), 404
        
        return jsonify({
            "success": True,
            "category": category,
            "name": prompt_name,
            "prompt": prompt
        })
    except Exception as e:
        logger.error(f"Error getting prompt {category}/{prompt_name}: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/<category>/<prompt_name>", methods=["PUT"])
def update_prompt(category, prompt_name):
    """Update a specific prompt."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    try:
        # Load current prompts
        prompts = load_prompts(category, force_reload=True)
        
        if prompt_name not in prompts:
            return jsonify({
                "error": f"Prompt not found: {category}/{prompt_name}"
            }), 404
        
        # Update the prompt
        updated_prompt = {}
        
        if "description" in data:
            updated_prompt["description"] = str(data["description"])
        else:
            updated_prompt["description"] = prompts[prompt_name].get("description", "")
        
        if "system" in data:
            updated_prompt["system"] = str(data["system"])
        else:
            updated_prompt["system"] = prompts[prompt_name].get("system", "")
        
        if "user_template" in data:
            updated_prompt["user_template"] = str(data["user_template"])
        else:
            updated_prompt["user_template"] = prompts[prompt_name].get("user_template", "")
        
        # Update the prompts dict
        prompts[prompt_name] = updated_prompt
        
        # Save to file
        if not save_prompts(category, prompts):
            return jsonify({"error": "Failed to save prompts"}), 500
        
        logger.info(f"Updated prompt: {category}/{prompt_name}")
        
        return jsonify({
            "success": True,
            "category": category,
            "name": prompt_name,
            "prompt": updated_prompt,
            "message": f"Prompt {prompt_name} updated successfully"
        })
        
    except Exception as e:
        logger.error(f"Error updating prompt {category}/{prompt_name}: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/reload", methods=["POST"])
def reload_prompts():
    """Force reload all prompts from disk."""
    try:
        reload_all_prompts()
        return jsonify({
            "success": True,
            "message": "All prompts reloaded from disk"
        })
    except Exception as e:
        logger.error(f"Error reloading prompts: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/categories", methods=["GET"])
def get_categories():
    """Get list of available prompt categories."""
    return jsonify({
        "success": True,
        "categories": [
            {
                "id": "expansion",
                "name": "Portfolio Expansion",
                "description": "Prompts for LLM-powered portfolio expansion (sector detection, similar stocks, dependents)"
            },
            {
                "id": "dream",
                "name": "Dream Worker",
                "description": "Prompts for knowledge graph edge relationship labeling"
            },
            {
                "id": "think",
                "name": "Think Worker",
                "description": "Prompts for multi-agent committee decision-making"
            },
            {
                "id": "options",
                "name": "Options Workers",
                "description": "Prompts for options monitoring and trading (chain selection, buy/sell decisions)"
            }
        ]
    })
