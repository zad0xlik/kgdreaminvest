"""Database module - Connection, operations, and schema management."""

# Connection management
from src.database.connection import db_conn, DB_LOCK

# CRUD operations
from src.database.operations import (
    kv_get,
    kv_set,
    norm_pair,
    ensure_edge_id,
    log_event,
    get_cash,
    set_cash,
    portfolio_state,
    positions_as_dict,
    recent_trade_summary,
)

# Schema and bootstrap
from src.database.schema import (
    init_db,
    bootstrap_if_empty,
    bootstrap_bellwethers,
    get_active_bellwethers,
    bootstrap_investibles,
    get_active_investibles,
    get_investible_tree,
    edge_weight_top,
    CHANNEL_WEIGHTS,
    DERIVED,
    AGENTS,
    BOOT_EDGES,
)

__all__ = [
    # Connection
    "db_conn",
    "DB_LOCK",
    # Operations
    "kv_get",
    "kv_set",
    "norm_pair",
    "ensure_edge_id",
    "log_event",
    "get_cash",
    "set_cash",
    "portfolio_state",
    "positions_as_dict",
    "recent_trade_summary",
    # Schema
    "init_db",
    "bootstrap_if_empty",
    "bootstrap_bellwethers",
    "get_active_bellwethers",
    "bootstrap_investibles",
    "get_active_investibles",
    "get_investible_tree",
    "edge_weight_top",
    "CHANNEL_WEIGHTS",
    "DERIVED",
    "AGENTS",
    "BOOT_EDGES",
]
