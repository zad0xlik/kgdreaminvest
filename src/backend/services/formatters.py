"""Formatting helpers for the web UI."""

from typing import Dict, Any


def kind_color(kind: str) -> str:
    """Return color for a given node kind."""
    return {
        "investible": "#34d399",
        "bellwether": "#60a5fa",
        "signal": "#a78bfa",
        "regime": "#fbbf24",
        "narrative": "#f472b6",
        "agent": "#22c55e",
    }.get(kind, "#9ca3af")


def edge_color(top: str) -> str:
    """Return color for a given edge channel."""
    if not top:
        return "#475569"
    if top.startswith("drives"):
        return "#60a5fa"
    if top.startswith("inverse"):
        return "#f87171"
    if top.startswith("correlates"):
        return "#34d399"
    if top.startswith("sentiment"):
        return "#a78bfa"
    if top.startswith("policy"):
        return "#fbbf24"
    if top.startswith("liquidity"):
        return "#38bdf8"
    return "#94a3b8"


def fmt_money(x: float) -> str:
    """Format money with comma separators."""
    return f"${x:,.2f}"
