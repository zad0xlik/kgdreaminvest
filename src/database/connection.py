"""Database connection management."""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from src.config import Config

# Thread-safe database lock
DB_LOCK = threading.RLock()


@contextmanager
def db_conn():
    """
    Context manager for database connections.
    
    Provides thread-safe SQLite connections with:
    - WAL mode for better concurrency
    - Row factory for dict-like access
    - Automatic commit/rollback
    - Connection pooling via context manager
    
    Usage:
        with db_conn() as conn:
            conn.execute("SELECT * FROM nodes")
            # automatic commit on success, rollback on exception
    """
    with DB_LOCK:
        conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=8000;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
