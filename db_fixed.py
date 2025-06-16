import sqlite3
import logging
import os
from threading import Lock
from contextlib import contextmanager
from os import getenv

DB_PATH = getenv("DB_PATH", "subs.db")
_lock = Lock()
logger = logging.getLogger(__name__)

@contextmanager
def get_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            threshold REAL NOT NULL,
            UNIQUE(chat_id, asset)
        )""")
        conn.commit()

def add_subscription(chat_id: int, asset: str, threshold: float):
    with _lock, get_db() as conn:
        try:
            conn.execute("INSERT INTO subscriptions(chat_id, asset, threshold) VALUES (?, ?, ?)", (chat_id, asset, threshold))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.execute("UPDATE subscriptions SET threshold = ? WHERE chat_id = ? AND asset = ?", (threshold, chat_id, asset))
            conn.commit()
            return True

def remove_subscription(chat_id: int, asset: str):
    with _lock, get_db() as conn:
        cursor = conn.execute("DELETE FROM subscriptions WHERE chat_id = ? AND asset = ?", (chat_id, asset))
        conn.commit()
        return cursor.rowcount > 0

def list_subscriptions(chat_id: int):
    with get_db() as conn:
        cursor = conn.execute("SELECT asset, threshold FROM subscriptions WHERE chat_id = ?", (chat_id,))
        return [(row["asset"], row["threshold"]) for row in cursor.fetchall()]

def get_all_unique_assets():
    with get_db() as conn:
        cursor = conn.execute("SELECT DISTINCT asset FROM subscriptions")
        return [row["asset"] for row in cursor.fetchall()]

def get_subscribers_for(asset: str):
    with get_db() as conn:
        cursor = conn.execute("SELECT chat_id, threshold FROM subscriptions WHERE asset = ?", (asset,))
        return [(row["chat_id"], row["threshold"]) for row in cursor.fetchall()]
