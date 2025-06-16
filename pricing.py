import os
import stripe
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Setup Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Pricing configuration
PRICING = {
    1: {"price": 9.99, "currency": "EUR", "name": "Premium 1 Mese"},
    3: {"price": 24.99, "currency": "EUR", "name": "Premium 3 Mesi"},
    12: {"price": 79.99, "currency": "EUR", "name": "Premium 12 Mesi"}
}

def create_payment_link(user_id: int, months: int, amount: float) -> str:
    """Crea link di pagamento Stripe"""
    try:
        # Crea prodotto
        product = stripe.Product.create(
            name=PRICING[months]["name"],
            description=f"Crypto Alert Bot Premium - {months} mes{'e' if months == 1 else 'i'}"
        )
        
        # Crea prezzo
        price = stripe.Price.create(
            product=product.id,
            unit_amount=int(amount * 100),  # Stripe usa centesimi
            currency=PRICING[months]["currency"].lower(),
        )
        
        # Crea sessione checkout
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price.id,
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'https://t.me/your_bot?start=payment_success_{user_id}',
            cancel_url=f'https://t.me/your_bot?start=payment_cancel_{user_id}',
            metadata={
                'user_id': user_id,
                'months': months,
                'bot_payment': 'crypto_alert_bot'
            }
        )
        
        # Log del pagamento
        from db import log_payment_attempt
        log_payment_attempt(user_id, session.id, amount, months)
        
        logger.info(f"Payment link created: user={user_id}, months={months}, amount={amount}")
        
        return session.url
        
    except Exception as e:
        logger.error(f"Stripe error creating payment link: {e}")
        raise

def verify_payment(session_id: str) -> Optional[Dict]:
    """Verifica pagamento completato"""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.payment_status == 'paid':
            return {
                'user_id': int(session.metadata['user_id']),
                'months': int(session.metadata['months']),
                'amount': session.amount_total / 100,
                'currency': session.currency,
                'payment_id': session.payment_intent
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        return None

def handle_webhook(payload: str, sig_header: str) -> bool:
    """Gestisce webhook Stripe"""
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
        
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            if session.get('metadata', {}).get('bot_payment') == 'crypto_alert_bot':
                # Attiva abbonamento
                user_id = int(session['metadata']['user_id'])
                months = int(session['metadata']['months'])
                
                from db import upgrade_subscription, log_payment_success
                
                upgrade_subscription(user_id, months)
                log_payment_success(user_id, session['id'], session['amount_total'] / 100)
                
                logger.info(f"Payment completed: user={user_id}, months={months}")
                
                # Invia notifica all'utente
                send_payment_success_notification(user_id, months)
                
                return True
                
        elif event['type'] == 'payment_intent.payment_failed':
            # Gestisci pagamento fallito
            payment_intent = event['data']['object']
            logger.warning(f"Payment failed: {payment_intent['id']}")
        
        return True
        
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        return False
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        return False
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return False

def send_payment_success_notification(user_id: int, months: int):
    """Invia notifica di pagamento completato"""
    try:
        from telegram import Bot
        
        bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
        
        message = f"""
🎉 *Pagamento completato con successo!*

✅ Premium attivato per {months} mes{'e' if months == 1 else 'i'}
💎 Tutte le funzionalità Premium sono ora disponibili

🔥 *Cosa puoi fare ora:*
• Alert illimitati
• Portfolio tracking avanzato
• Analisi tecnica completa
• News premium
• Supporto prioritario

Grazie per aver scelto Crypto Alert Bot Pro! 🚀
        """
        
        bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error sending payment notification: {e}")

def generate_promo_code(code: str, discount_percent: int, max_uses: int, expires_days: int = 30):
    """Genera codice promo"""
    try:
        from db import create_promo_code
        
        expires_at = datetime.now() + timedelta(days=expires_days)
        
        success = create_promo_code(code, discount_percent, max_uses, expires_at)
        
        if success:
            logger.info(f"Promo code created: {code} ({discount_percent}% off, {max_uses} uses)")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error creating promo code: {e}")
        return False

def apply_promo_code(code: str, user_id: int) -> Optional[Dict]:
    """Applica codice promo"""
    try:
        from db import get_promo_code, use_promo_code
        
        promo = get_promo_code(code)
        
        if not promo:
            return {"error": "Codice promo non valido"}
        
        if promo["current_uses"] >= promo["max_uses"]:
            return {"error": "Codice promo esaurito"}
        
        if datetime.fromisoformat(promo["expires_at"]) < datetime.now():
            return {"error": "Codice promo scaduto"}
        
        # Usa il codice
        use_promo_code(code)
        
        return {
            "discount_percent": promo["discount_percent"],
            "code": code
        }
        
    except Exception as e:
        logger.error(f"Error applying promo code: {e}")
        return {"error": "Errore nell'applicare il codice"}

def calculate_discounted_price(months: int, discount_percent: int) -> float:
    """Calcola prezzo scontato"""
    base_price = PRICING[months]["price"]
    discount = base_price * (discount_percent / 100)
    return base_price - discount

# Funzioni database per pagamenti (da aggiungere al db.py)
def log_payment_attempt(user_id: int, session_id: str, amount: float, months: int):
    """Log tentativo di pagamento"""
    from db import get_db, _lock
    
    with _lock, get_db() as conn:
        conn.execute("""
            INSERT INTO payments (chat_id, stripe_payment_id, amount, subscription_months, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (user_id, session_id, amount, months))
        conn.commit()

def log_payment_success(user_id: int, session_id: str, amount: float):
    """Log pagamento completato"""
    from db import get_db, _lock
    
    with _lock, get_db() as conn:
        conn.execute("""
            UPDATE payments 
            SET status = 'completed'
            WHERE chat_id = ? AND stripe_payment_id = ?
        """, (user_id, session_id))
        conn.commit()

def create_promo_code(code: str, discount_percent: int, max_uses: int, expires_at: datetime):
    """Crea codice promo nel database"""
    from db import get_db, _lock
    
    try:
        with _lock, get_db() as conn:
            conn.execute("""
                INSERT INTO promo_codes (code, discount_percent, max_uses, expires_at)
                VALUES (?, ?, ?, ?)
            """, (code, discount_percent, max_uses, expires_at))
            conn.commit()
            return True
    except:
        return False

def get_promo_code(code: str):
    """Ottieni info codice promo"""
    from db import get_db
    
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM promo_codes WHERE code = ?
        """, (code,))
        
        row = cursor.fetchone()
        return dict(row) if row else None

def use_promo_code(code: str):
    """Incrementa uso del codice promo"""
    from db import get_db, _lock
    
    with _lock, get_db() as conn:
        conn.execute("""
            UPDATE promo_codes 
            SET current_uses = current_uses + 1
            WHERE code = ?
        """, (code,))
        conn.commit()