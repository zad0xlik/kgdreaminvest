"""Worker control routes."""

from flask import Blueprint, jsonify

from src.workers import MARKET, DREAM, THINK
from src.workers.options_worker import OPTIONS
from src.workers.options_think_worker import OPTIONS_THINK

bp = Blueprint("workers", __name__, url_prefix="/api")


@bp.post("/market/start")
def market_start():
    """Start the market worker."""
    if not MARKET.running:
        MARKET.start()
    return jsonify({"ok": True, "running": MARKET.running})


@bp.post("/market/stop")
def market_stop():
    """Stop the market worker."""
    MARKET.stop_now()
    return jsonify({"ok": True, "running": MARKET.running})


@bp.post("/market/step")
def market_step():
    """Execute a single market worker step."""
    MARKET.step_once()
    return jsonify({"ok": True})


@bp.post("/dream/start")
def dream_start():
    """Start the dream worker."""
    if not DREAM.running:
        DREAM.start()
    return jsonify({"ok": True, "running": DREAM.running})


@bp.post("/dream/stop")
def dream_stop():
    """Stop the dream worker."""
    DREAM.stop_now()
    return jsonify({"ok": True, "running": DREAM.running})


@bp.post("/think/start")
def think_start():
    """Start the think worker."""
    if not THINK.running:
        THINK.start()
    return jsonify({"ok": True, "running": THINK.running})


@bp.post("/think/stop")
def think_stop():
    """Stop the think worker."""
    THINK.stop_now()
    return jsonify({"ok": True, "running": THINK.running})


@bp.post("/think/step")
def think_step():
    """Execute a single think worker step."""
    THINK.step_once()
    return jsonify({"ok": True})


@bp.post("/options/start")
def options_start():
    """Start the options worker."""
    if not OPTIONS.running:
        OPTIONS.start()
    return jsonify({"ok": True, "running": OPTIONS.running})


@bp.post("/options/stop")
def options_stop():
    """Stop the options worker."""
    OPTIONS.stop_now()
    return jsonify({"ok": True, "running": OPTIONS.running})


@bp.post("/options/step")
def options_step():
    """Execute a single options worker step."""
    OPTIONS.step_once()
    return jsonify({"ok": True})


@bp.post("/options_think/start")
def options_think_start():
    """Start the options think worker."""
    if not OPTIONS_THINK.running:
        OPTIONS_THINK.start()
    return jsonify({"ok": True, "running": OPTIONS_THINK.running})


@bp.post("/options_think/stop")
def options_think_stop():
    """Stop the options think worker."""
    OPTIONS_THINK.stop_now()
    return jsonify({"ok": True, "running": OPTIONS_THINK.running})


@bp.post("/options_think/step")
def options_think_step():
    """Execute a single options think worker step."""
    OPTIONS_THINK.step_once()
    return jsonify({"ok": True})
