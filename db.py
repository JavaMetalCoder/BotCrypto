import sqlite3
import logging
from threading import Lock
from contextlib import contextmanager
from os import getenv
from datetime import datetime

DB_PATH = getenv("DB_PATH", "subs.db")
_lock = Lock()
logger = logging.getLogger(__name__)

@contextmanager
def get_db():
    """Context manager per connessioni DB sicure"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Ottimizzazioni SQLite
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=1000")
        conn.execute("PRAGMA temp_store=memory")
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
    """Inizializza database con schema completo"""
    with _lock, get_db() as conn:
        # Tabella sottoscrizioni
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            threshold REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, asset)
        )""")
        
        # Tabella notifiche inviate (evita spam)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            price REAL NOT NULL,
            threshold REAL NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Indici per performance
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_asset 
        ON subscriptions(asset)
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_chat_id 
        ON subscriptions(chat_id)
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_lookup 
        ON notifications(chat_id, asset, sent_at)
        """)
        
        conn.commit()
        logger.info("Database schema initialized successfully")

def add_subscription(chat_id: int, asset: str, threshold: float):
    """Aggiungi sottoscrizione con gestione duplicati"""
    with _lock, get_db() as conn:
        try:
            conn.execute("""
                INSERT INTO subscriptions(chat_id, asset, threshold) 
                VALUES (?, ?, ?)
            """, (chat_id, asset, threshold))
            conn.commit()
            logger.info(f"Added subscription: user={chat_id}, asset={asset}, threshold={threshold}")
            return True
        except sqlite3.IntegrityError:
            # Duplicato - aggiorna soglia esistente
            conn.execute("""
                UPDATE subscriptions 
                SET threshold = ?, created_at = CURRENT_TIMESTAMP
                WHERE chat_id = ? AND asset = ?
            """, (threshold, chat_id, asset))
            conn.commit()
            logger.info(f"Updated subscription: user={chat_id}, asset={asset}, new_threshold={threshold}")
            return True

def remove_subscription(chat_id: int, asset: str):
    """Rimuovi sottoscrizione specifica"""
    with _lock, get_db() as conn:
        cursor = conn.execute("""
            DELETE FROM subscriptions 
            WHERE chat_id = ? AND asset = ?
        """, (chat_id, asset))
        
        # Rimuovi anche notifiche associate
        conn.execute("""
            DELETE FROM notifications 
            WHERE chat_id = ? AND asset = ?
        """, (chat_id, asset))
        
        conn.commit()
        deleted = cursor.rowcount
        
        if deleted:
            logger.info(f"Removed subscription: user={chat_id}, asset={asset}")
        
        return deleted > 0

def list_subscriptions(chat_id: int):
    """Lista sottoscrizioni utente"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT asset, threshold, created_at 
            FROM subscriptions 
            WHERE chat_id = ? 
            ORDER BY created_at DESC
        """, (chat_id,))
        
        rows = cursor.fetchall()
        return [(row["asset"], row["threshold"]) for row in rows]

def get_all_unique_assets():
    """Ottieni tutti gli asset unici monitorati"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT DISTINCT asset 
            FROM subscriptions 
            ORDER BY asset
        """)
        
        assets = [row["asset"] for row in cursor.fetchall()]
        return assets

def get_subscribers_for(asset: str):
    """Ottieni tutti i subscriber per un asset"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT chat_id, threshold 
            FROM subscriptions 
            WHERE asset = ?
            ORDER BY threshold ASC
        """, (asset,))
        
        subscribers = [(row["chat_id"], row["threshold"]) for row in cursor.fetchall()]
        return subscribers

def should_send_notification(chat_id: int, asset: str, current_price: float, threshold: float):
    """Controlla se inviare notifica (evita spam)"""
    with get_db() as conn:
        # Controlla ultima notifica nelle ultime 4 ore
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM notifications 
            WHERE chat_id = ? AND asset = ? 
            AND sent_at > datetime('now', '-4 hours')
            AND price >= ?
        """, (chat_id, asset, threshold * 0.95))  # 5% tolerance
        
        result = cursor.fetchone()
        return result["count"] == 0

def log_notification(chat_id: int, asset: str, price: float, threshold: float):
    """Registra notifica inviata"""
    with _lock, get_db() as conn:
        conn.execute("""
            INSERT INTO notifications(chat_id, asset, price, threshold) 
            VALUES (?, ?, ?, ?)
        """, (chat_id, asset, price, threshold))
        conn.commit()

def get_total_users():
    """Conta utenti unici"""
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(DISTINCT chat_id) as count FROM subscriptions")
        return cursor.fetchone()["count"]

def get_total_subscriptions():
    """Conta sottoscrizioni totali"""
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as count FROM subscriptions")
        return cursor.fetchone()["count"]

def cleanup_old_notifications():
    """Pulisci notifiche vecchie (>30 giorni)"""
    with _lock, get_db() as conn:
        cursor = conn.execute("""
            DELETE FROM notifications 
            WHERE sent_at < datetime('now', '-30 days')
        """)
        deleted = cursor.rowcount
        conn.commit()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old notifications")
        
        return deleted

def get_user_stats(chat_id: int):
    """Statistiche utente"""
    with get_db() as conn:
        # Sottoscrizioni
        subs_cursor = conn.execute("""
            SELECT COUNT(*) as count 
            FROM subscriptions 
            WHERE chat_id = ?
        """, (chat_id,))
        
        # Notifiche ricevute (ultimo mese)
        notifs_cursor = conn.execute("""
            SELECT COUNT(*) as count 
            FROM notifications 
            WHERE chat_id = ? AND sent_at > datetime('now', '-30 days')
        """, (chat_id,))
        
        return {
            "subscriptions": subs_cursor.fetchone()["count"],
            "notifications_last_month": notifs_cursor.fetchone()["count"]
        }

def backup_db(backup_path: str = None):
    """Backup database"""
    if not backup_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"backup_subs_{timestamp}.db"
    
    try:
        with get_db() as conn:
            backup_conn = sqlite3.connect(backup_path)
            conn.backup(backup_conn)
            backup_conn.close()
            
        logger.info(f"Database backed up to {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise