import sqlite3
import logging
import os
from threading import Lock
from contextlib import contextmanager
from os import getenv
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

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
    """Inizializza database con schema completo per tutte le features"""
    # Rimuovi database esistente se readonly
    if os.path.exists(DB_PATH):
        try:
            # Test se è scrivibile
            with sqlite3.connect(DB_PATH, timeout=1.0) as test_conn:
                test_conn.execute("CREATE TABLE IF NOT EXISTS test_write (id INTEGER)")
                test_conn.rollback()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            if "readonly" in str(e).lower() or "permission" in str(e).lower():
                logger.warning(f"Database {DB_PATH} is readonly, removing and recreating...")
                try:
                    os.remove(DB_PATH)
                except OSError:
                    pass
    
    # Crea directory se non esiste
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with _lock, get_db() as conn:
        # 1. Tabella utenti con abbonamenti
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            subscription_type TEXT DEFAULT 'free',
            subscription_expires TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_alerts_sent INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER REFERENCES users(chat_id)
        )""")
        
        # 2. Tabella sottoscrizioni alert
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL REFERENCES users(chat_id),
            asset TEXT NOT NULL,
            threshold REAL NOT NULL,
            alert_type TEXT DEFAULT 'price_above',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, asset, threshold, alert_type)
        )""")
        
        # 3. Tabella portfolio tracking
        conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL REFERENCES users(chat_id),
            asset TEXT NOT NULL,
            amount REAL NOT NULL,
            avg_buy_price REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # 4. Tabella notifiche inviate
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            price REAL NOT NULL,
            threshold REAL,
            message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # 5. Tabella watchlist condivise
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_by INTEGER NOT NULL REFERENCES users(chat_id),
            is_public BOOLEAN DEFAULT 0,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_assets (
            watchlist_id INTEGER REFERENCES watchlists(id),
            asset TEXT NOT NULL,
            added_by INTEGER REFERENCES users(chat_id),
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (watchlist_id, asset)
        )""")
        
        # 6. Tabella pagamenti
        conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL REFERENCES users(chat_id),
            stripe_payment_id TEXT,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'EUR',
            subscription_months INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # 7. Tabella codici promo
        conn.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            discount_percent INTEGER,
            max_uses INTEGER,
            current_uses INTEGER DEFAULT 0,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Indici per performance
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_chat_id ON subscriptions(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_asset ON subscriptions(asset)",
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_portfolio_chat_id ON portfolio(chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_notifications_chat_asset ON notifications(chat_id, asset)",
            "CREATE INDEX IF NOT EXISTS idx_notifications_sent_at ON notifications(sent_at)",
            "CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_type, subscription_expires)",
        ]
        
        for index in indices:
            conn.execute(index)
        
        conn.commit()
        logger.info("Database schema initialized successfully")

# ==============================================
# USER MANAGEMENT
# ==============================================

def create_or_update_user(chat_id: int, username: str = None, first_name: str = None):
    """Crea o aggiorna utente"""
    with _lock, get_db() as conn:
        # Genera codice referral unico
        import string
        import random
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        conn.execute("""
            INSERT OR REPLACE INTO users 
            (chat_id, username, first_name, last_active, referral_code) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (chat_id, username, first_name, referral_code))
        conn.commit()

def get_user_subscription(chat_id: int) -> Dict:
    """Ottieni info abbonamento utente"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT subscription_type, subscription_expires, total_alerts_sent
            FROM users WHERE chat_id = ?
        """, (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            create_or_update_user(chat_id)
            return {"type": "free", "expires": None, "alerts_sent": 0}
        
        return {
            "type": row["subscription_type"],
            "expires": row["subscription_expires"],
            "alerts_sent": row["total_alerts_sent"]
        }

def upgrade_subscription(chat_id: int, months: int = 1):
    """Upgrade utente a premium"""
    with _lock, get_db() as conn:
        expires = datetime.now() + timedelta(days=30 * months)
        conn.execute("""
            UPDATE users 
            SET subscription_type = 'premium', subscription_expires = ?
            WHERE chat_id = ?
        """, (expires, chat_id))
        conn.commit()

def check_subscription_limits(chat_id: int) -> Tuple[bool, str]:
    """Controlla limiti abbonamento"""
    user = get_user_subscription(chat_id)
    
    if user["type"] == "premium":
        # Controlla se non è scaduto
        if user["expires"] and datetime.fromisoformat(user["expires"]) > datetime.now():
            return True, "premium_active"
        else:
            # Scaduto, downgrade a free
            with _lock, get_db() as conn:
                conn.execute("UPDATE users SET subscription_type = 'free' WHERE chat_id = ?", (chat_id,))
                conn.commit()
            return False, "premium_expired"
    
    # Free user - controlla limiti
    current_alerts = len(list_subscriptions(chat_id))
    if current_alerts >= 2:
        return False, "free_limit_reached"
    
    return True, "free_ok"

# ==============================================
# SUBSCRIPTION MANAGEMENT
# ==============================================

def add_subscription(chat_id: int, asset: str, threshold: float, alert_type: str = "price_above"):
    """Aggiungi sottoscrizione con controllo limiti"""
    # Controlla limiti abbonamento
    allowed, reason = check_subscription_limits(chat_id)
    if not allowed:
        return False, reason
    
    with _lock, get_db() as conn:
        try:
            conn.execute("""
                INSERT INTO subscriptions(chat_id, asset, threshold, alert_type) 
                VALUES (?, ?, ?, ?)
            """, (chat_id, asset, threshold, alert_type))
            conn.commit()
            logger.info(f"Added subscription: user={chat_id}, asset={asset}, threshold={threshold}")
            return True, "success"
        except sqlite3.IntegrityError:
            # Duplicato - aggiorna
            conn.execute("""
                UPDATE subscriptions 
                SET threshold = ?, is_active = 1
                WHERE chat_id = ? AND asset = ? AND alert_type = ?
            """, (threshold, chat_id, asset, alert_type))
            conn.commit()
            return True, "updated"

def remove_subscription(chat_id: int, asset: str, alert_type: str = "price_above"):
    """Rimuovi sottoscrizione"""
    with _lock, get_db() as conn:
        cursor = conn.execute("""
            DELETE FROM subscriptions 
            WHERE chat_id = ? AND asset = ? AND alert_type = ?
        """, (chat_id, asset, alert_type))
        conn.commit()
        return cursor.rowcount > 0

def list_subscriptions(chat_id: int) -> List[Tuple]:
    """Lista sottoscrizioni utente"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT asset, threshold, alert_type, is_active, created_at
            FROM subscriptions 
            WHERE chat_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """, (chat_id,))
        
        return [(row["asset"], row["threshold"], row["alert_type"]) for row in cursor.fetchall()]

def get_all_active_subscriptions():
    """Ottieni tutte le sottoscrizioni attive"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT chat_id, asset, threshold, alert_type
            FROM subscriptions 
            WHERE is_active = 1
        """)
        return cursor.fetchall()

# ==============================================
# PORTFOLIO MANAGEMENT
# ==============================================

def add_portfolio_position(chat_id: int, asset: str, amount: float, buy_price: float):
    """Aggiungi posizione al portfolio"""
    with _lock, get_db() as conn:
        # Controlla se esiste già
        cursor = conn.execute("""
            SELECT amount, avg_buy_price FROM portfolio 
            WHERE chat_id = ? AND asset = ?
        """, (chat_id, asset))
        
        existing = cursor.fetchone()
        
        if existing:
            # Calcola nuovo prezzo medio
            old_amount = existing["amount"]
            old_price = existing["avg_buy_price"]
            
            total_cost = (old_amount * old_price) + (amount * buy_price)
            new_amount = old_amount + amount
            new_avg_price = total_cost / new_amount
            
            conn.execute("""
                UPDATE portfolio 
                SET amount = ?, avg_buy_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = ? AND asset = ?
            """, (new_amount, new_avg_price, chat_id, asset))
        else:
            conn.execute("""
                INSERT INTO portfolio (chat_id, asset, amount, avg_buy_price)
                VALUES (?, ?, ?, ?)
            """, (chat_id, asset, amount, buy_price))
        
        conn.commit()
        return True

def get_portfolio(chat_id: int, current_prices: Dict[str, float] = None):
    """Ottieni portfolio con P&L"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT asset, amount, avg_buy_price 
            FROM portfolio WHERE chat_id = ?
        """, (chat_id,))
        
        portfolio = []
        total_value = 0
        total_cost = 0
        
        for row in cursor.fetchall():
            asset = row["asset"]
            amount = row["amount"]
            avg_price = row["avg_buy_price"]
            cost = amount * avg_price
            
            current_price = current_prices.get(asset, 0) if current_prices else 0
            current_value = amount * current_price
            pnl = current_value - cost
            pnl_percent = (pnl / cost * 100) if cost > 0 else 0
            
            portfolio.append({
                "asset": asset,
                "amount": amount,
                "avg_price": avg_price,
                "current_price": current_price,
                "cost": cost,
                "value": current_value,
                "pnl": pnl,
                "pnl_percent": pnl_percent
            })
            
            total_value += current_value
            total_cost += cost
        
        total_pnl = total_value - total_cost
        total_pnl_percent = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        return {
            "positions": portfolio,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_percent": total_pnl_percent
        }

# ==============================================
# NOTIFICATION SYSTEM
# ==============================================

def should_send_notification(chat_id: int, asset: str, current_price: float, threshold: float, alert_type: str):
    """Controlla se inviare notifica (anti-spam intelligente)"""
    with get_db() as conn:
        # Controlla ultima notifica simile nelle ultime 4 ore
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM notifications 
            WHERE chat_id = ? AND asset = ? AND alert_type = ?
            AND sent_at > datetime('now', '-4 hours')
            AND ABS(price - ?) < ?
        """, (chat_id, asset, alert_type, current_price, threshold * 0.02))  # 2% tolerance
        
        return cursor.fetchone()["count"] == 0

def log_notification(chat_id: int, asset: str, alert_type: str, price: float, threshold: float = None, message: str = None):
    """Registra notifica inviata"""
    with _lock, get_db() as conn:
        conn.execute("""
            INSERT INTO notifications(chat_id, asset, alert_type, price, threshold, message) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, asset, alert_type, price, threshold, message))
        
        # Incrementa counter utente
        conn.execute("""
            UPDATE users SET total_alerts_sent = total_alerts_sent + 1 
            WHERE chat_id = ?
        """, (chat_id,))
        
        conn.commit()

# ==============================================
# LEGACY COMPATIBILITY
# ==============================================

def get_all_unique_assets():
    """Compatibilità: ottieni asset unici"""
    with get_db() as conn:
        cursor = conn.execute("SELECT DISTINCT asset FROM subscriptions WHERE is_active = 1")
        return [row["asset"] for row in cursor.fetchall()]

def get_subscribers_for(asset: str):
    """Compatibilità: ottieni subscriber per asset"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT chat_id, threshold, alert_type 
            FROM subscriptions 
            WHERE asset = ? AND is_active = 1
        """, (asset,))
        return [(row["chat_id"], row["threshold"], row["alert_type"]) for row in cursor.fetchall()]

# ==============================================
# STATISTICS & ADMIN
# ==============================================

def get_total_users():
    """Conta utenti totali"""
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as count FROM users")
        return cursor.fetchone()["count"]

def get_total_subscriptions():
    """Conta sottoscrizioni attive"""
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as count FROM subscriptions WHERE is_active = 1")
        return cursor.fetchone()["count"]

def get_premium_users_count():
    """Conta utenti premium attivi"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM users 
            WHERE subscription_type = 'premium' 
            AND subscription_expires > datetime('now')
        """)
        return cursor.fetchone()["count"]

def cleanup_old_notifications():
    """Pulisci notifiche vecchie"""
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
    """Statistiche complete utente"""
    with get_db() as conn:
        user_cursor = conn.execute("""
            SELECT subscription_type, subscription_expires, total_alerts_sent, created_at
            FROM users WHERE chat_id = ?
        """, (chat_id,))
        
        user = user_cursor.fetchone()
        if not user:
            return {}
        
        subs_cursor = conn.execute("""
            SELECT COUNT(*) as count FROM subscriptions 
            WHERE chat_id = ? AND is_active = 1
        """, (chat_id,))
        
        portfolio_cursor = conn.execute("""
            SELECT COUNT(*) as positions, SUM(amount * avg_buy_price) as total_invested
            FROM portfolio WHERE chat_id = ?
        """, (chat_id,))
        
        portfolio_data = portfolio_cursor.fetchone()
        
        return {
            "subscription_type": user["subscription_type"],
            "subscription_expires": user["subscription_expires"],
            "total_alerts_sent": user["total_alerts_sent"],
            "member_since": user["created_at"],
            "active_subscriptions": subs_cursor.fetchone()["count"],
            "portfolio_positions": portfolio_data["positions"] or 0,
            "total_invested": portfolio_data["total_invested"] or 0
        }