import os
import requests
import logging
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError, Unauthorized, BadRequest

from db import (
    get_all_unique_assets, get_subscribers_for, 
    should_send_notification, log_notification,
    cleanup_old_notifications
)

# API Configuration
API_URL = "https://api.coingecko.com/api/v3/simple/price"
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

bot = Bot(token=TOKEN)
logger = logging.getLogger(__name__)

# Cache per prezzi (evita spam API)
_price_cache = {}
CACHE_DURATION = 240  # 4 minuti
_last_cleanup = datetime.now()

def get_cached_price(asset: str):
    """Recupera prezzo dalla cache se disponibile"""
    now = datetime.now()
    if asset in _price_cache:
        price, timestamp = _price_cache[asset]
        if now - timestamp < timedelta(seconds=CACHE_DURATION):
            logger.debug(f"Cache hit for {asset}: ${price:.2f}")
            return price
    return None

def set_cached_price(asset: str, price: float):
    """Salva prezzo in cache"""
    _price_cache[asset] = (price, datetime.now())

def fetch_prices(assets: list):
    """Fetch prezzi da CoinGecko con retry e cache"""
    if not assets:
        return {}
    
    # Controlla cache prima
    cached_prices = {}
    uncached_assets = []
    
    for asset in assets:
        cached_price = get_cached_price(asset)
        if cached_price is not None:
            cached_prices[asset] = cached_price
        else:
            uncached_assets.append(asset)
    
    if not uncached_assets:
        logger.debug(f"All prices served from cache: {len(cached_prices)} assets")
        return cached_prices
    
    # Fetch solo asset non in cache
    logger.info(f"Fetching prices for {len(uncached_assets)} assets from API")
    
    try:
        params = {
            "ids": ",".join(uncached_assets),
            "vs_currencies": "usd",
            "include_last_updated_at": "true"
        }
        
        response = requests.get(
            API_URL, 
            params=params, 
            timeout=15,
            headers={"User-Agent": "CryptoAlertBot/1.0"}
        )
        response.raise_for_status()
        data = response.json()
        
        # Processa risultati
        fetched_prices = {}
        for asset in uncached_assets:
            if asset in data and "usd" in data[asset]:
                price = data[asset]["usd"]
                fetched_prices[asset] = price
                set_cached_price(asset, price)
                logger.debug(f"Fetched {asset}: ${price:.2f}")
            else:
                logger.warning(f"No price data for asset: {asset}")
        
        # Combina cache + fetch
        all_prices = {**cached_prices, **fetched_prices}
        
        logger.info(f"Price fetch complete: {len(all_prices)}/{len(assets)} assets")
        return all_prices
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        # Ritorna solo cache in caso di errore
        if cached_prices:
            logger.info(f"Using cached prices due to API error: {len(cached_prices)} assets")
        return cached_prices
        
    except Exception as e:
        logger.error(f"Unexpected error in price fetch: {e}")
        return cached_prices

def send_alert(chat_id: int, asset: str, price: float, threshold: float):
    """Invia singolo alert con formato elegante"""
    try:
        # Calcola variazione percentuale dalla soglia
        percent_over = ((price - threshold) / threshold) * 100
        
        # Emoji basato sulla grandezza del movimento
        if percent_over >= 10:
            emoji = "🚀"
        elif percent_over >= 5:
            emoji = "📈"
        else:
            emoji = "⚠️"
        
        asset_name = asset.replace('-', ' ').upper()
        
        message = (
            f"{emoji} *ALERT: {asset_name}*\n\n"
            f"💰 Prezzo attuale: *${price:,.2f}*\n"
            f"🎯 Tua soglia: ${threshold:,.2f}\n"
            f"📊 Oltre soglia: *+{percent_over:.1f}%*\n\n"
            f"🕐 {datetime.now().strftime('%H:%M - %d/%m/%Y')}"
        )
        
        bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        # Log notifica
        log_notification(chat_id, asset, price, threshold)
        logger.info(f"Alert sent: user={chat_id}, asset={asset}, price=${price:.2f}")
        
        return True
        
    except Unauthorized:
        logger.warning(f"User {chat_id} blocked the bot - removing subscriptions")
        # TODO: Rimuovi tutte le sottoscrizioni dell'utente bloccato
        return False
        
    except BadRequest as e:
        logger.error(f"Bad request sending alert to {chat_id}: {e}")
        return False
        
    except TelegramError as e:
        logger.error(f"Telegram error sending alert to {chat_id}: {e}")
        return False
        
    except Exception as e:
        logger.error(f"Unexpected error sending alert to {chat_id}: {e}")
        return False

def check_prices(context):
    """Job principale - controlla prezzi e invia alert"""
    global _last_cleanup
    
    try:
        logger.debug("Starting price check cycle")
        
        # Ottieni asset da monitorare
        assets = get_all_unique_assets()
        if not assets:
            logger.debug("No assets to monitor")
            return
        
        logger.info(f"Checking prices for {len(assets)} assets")
        
        # Fetch prezzi
        prices = fetch_prices(assets)
        if not prices:
            logger.warning("No prices fetched - skipping cycle")
            return
        
        # Statistiche ciclo
        alerts_sent = 0
        total_checks = 0
        
        # Controlla ogni asset
        for asset in assets:
            if asset not in prices:
                continue
                
            current_price = prices[asset]
            subscribers = get_subscribers_for(asset)
            
            logger.debug(f"{asset}: ${current_price:.2f} - {len(subscribers)} subscribers")
            
            for chat_id, threshold in subscribers:
                total_checks += 1
                
                # Controlla se soglia raggiunta
                if current_price >= threshold:
                    # Anti-spam check
                    if should_send_notification(chat_id, asset, current_price, threshold):
                        if send_alert(chat_id, asset, current_price, threshold):
                            alerts_sent += 1
                    else:
                        logger.debug(f"Skipped duplicate alert: user={chat_id}, asset={asset}")
        
        # Log statistiche ciclo
        logger.info(f"Price check complete: {alerts_sent} alerts sent, {total_checks} checks performed")
        
        # Cleanup periodico (ogni ora)
        now = datetime.now()
        if now - _last_cleanup > timedelta(hours=1):
            cleanup_old_notifications()
            _last_cleanup = now
        
        # Notifica admin se molti alert
        if ADMIN_CHAT_ID and alerts_sent >= 10:
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"📊 *Ciclo completato*\n"
                    f"🔔 Alert inviati: {alerts_sent}\n"
                    f"📈 Asset monitorati: {len(assets)}\n"
                    f"👥 Controlli totali: {total_checks}",
                    parse_mode='Markdown'
                )
            except:
                pass
                
    except Exception as e:
        logger.error(f"Critical error in price check: {e}")
        
        # Notifica admin dell'errore
        if ADMIN_CHAT_ID:
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"❌ *Errore nel controllo prezzi*\n"
                    f"🐛 {str(e)[:200]}",
                    parse_mode='Markdown'
                )
            except:
                pass

def send_broadcast(message: str, parse_mode: str = None):
    """Invia messaggio broadcast a tutti gli utenti (solo admin)"""
    from db import get_total_users
    
    try:
        # Ottieni tutti gli utenti unici
        with get_db() as conn:
            cursor = conn.execute("SELECT DISTINCT chat_id FROM subscriptions")
            chat_ids = [row["chat_id"] for row in cursor.fetchall()]
        
        sent = 0
        failed = 0
        
        for chat_id in chat_ids:
            try:
                bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=parse_mode
                )
                sent += 1
            except:
                failed += 1
        
        logger.info(f"Broadcast complete: {sent} sent, {failed} failed")
        return sent, failed
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        return 0, 0

def health_check():
    """Health check per monitoring"""
    try:
        # Test API
        test_response = requests.get(
            f"{API_URL}?ids=bitcoin&vs_currencies=usd",
            timeout=10
        )
        api_ok = test_response.status_code == 200
        
        # Test Bot
        bot_info = bot.get_me()
        bot_ok = bot_info.username is not None
        
        # Test DB
        from db import get_total_users
        users = get_total_users()
        db_ok = isinstance(users, int)
        
        status = {
            "api": api_ok,
            "bot": bot_ok, 
            "database": db_ok,
            "cache_size": len(_price_cache),
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Health check: {status}")
        return status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"error": str(e), "timestamp": datetime.now().isoformat()}