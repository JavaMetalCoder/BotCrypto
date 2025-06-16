import sqlite3
from threading import Lock
from os import getenv

DB_PATH = getenv("DB_PATH", "subs.db")
_lock = Lock()

def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _lock:
        conn = _get_conn()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            threshold REAL NOT NULL
        )""")
        conn.commit()
        conn.close()

def add_subscription(chat_id: int, asset: str, threshold: float):
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO subscriptions(chat_id, asset, threshold) VALUES (?, ?, ?)",
            (chat_id, asset, threshold)
        )
        conn.commit()
        conn.close()

def remove_subscription(chat_id: int, asset: str):
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id=? AND asset=?",
            (chat_id, asset)
        )
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return deleted

def list_subscriptions(chat_id: int):
    conn = _get_conn()
    cur = conn.execute(
        "SELECT asset, threshold FROM subscriptions WHERE chat_id=?",
        (chat_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return [(r["asset"], r["threshold"]) for r in rows]

def get_all_unique_assets():
    conn = _get_conn()
    cur = conn.execute("SELECT DISTINCT asset FROM subscriptions")
    assets = [r["asset"] for r in cur.fetchall()]
    conn.close()
    return assets

def get_subscribers_for(asset: str):
    conn = _get_conn()
    cur = conn.execute(
        "SELECT chat_id, threshold FROM subscriptions WHERE asset=?",
        (asset,)
    )
    subs = [(r["chat_id"], r["threshold"]) for r in cur.fetchall()]
    conn.close()
    return subs
