import os
import requests
import logging
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError, Unauthorized, BadRequest
from typing import Dict, List, Tuple

from db import (
    get_all_active_subscriptions, log_notification, 
    should_send_notification, cleanup_old_notifications,
    get_user_subscription
)

# API Configuration
API_URL = "https://api.coingecko.com/api/v3/simple/price"
NEWS_API_URL = "https://api.coingecko.com/api/v3/news"
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

bot = Bot(token=TOKEN)
logger = logging.getLogger(__name__)

# Cache intelligente multi-layer
_price_cache = {}
_news_cache = {}
_technical_cache = {}
CACHE_DURATION = 240  # 4 minuti
_last_cleanup = datetime.now()

def get_cached_data(cache_dict: dict, key: str, max_age: int = CACHE_DURATION):
    """Recupera dati dalla cache se validi"""
    now = datetime.now()
    if key in cache_dict:
        data, timestamp = cache_dict[key]
        if now - timestamp < timedelta(seconds=max_age):
            return data
    return None

def set_cached_data(cache_dict: dict, key: str, data):
    """Salva dati in cache"""
    cache_dict[key] = (data, datetime.now())

def fetch_prices(assets: List[str]) -> Dict[str, float]:
    """Fetch prezzi con cache intelligente e resilienza"""
    if not assets:
        return {}
    
    # Controlla cache per ogni asset
    cached_prices = {}
    uncached_assets = []
    
    for asset in assets:
        cached_price = get_cached_data(_price_cache, asset)
        if cached_price is not None:
            cached_prices[asset] = cached_price
        else:
            uncached_assets.append(asset)
    
    if not uncached_assets:
        logger.debug(f"All {len(cached_prices)} prices served from cache")
        return cached_prices
    
    # Fetch asset non in cache
    logger.info(f"Fetching prices for {len(uncached_assets)} assets")
    
    try:
        params = {
            "ids": ",".join(uncached_assets),
            "vs_currencies": "usd,eur",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true"
        }
        
        response = requests.get(
            API_URL, 
            params=params, 
            timeout=15,
            headers={"User-Agent": "CryptoAlertBot-Pro/2.0"}
        )
        response.raise_for_status()
        data = response.json()
        
        # Processa e salva in cache
        fetched_prices = {}
        for asset in uncached_assets:
            if asset in data and "usd" in data[asset]:
                price_data = {
                    "usd": data[asset]["usd"],
                    "eur": data[asset].get("eur", 0),
                    "change_24h": data[asset].get("usd_24h_change", 0),
                    "market_cap": data[asset].get("usd_market_cap", 0),
                    "volume_24h": data[asset].get("usd_24h_vol", 0),
                    "timestamp": datetime.now().isoformat()
                }
                
                fetched_prices[asset] = price_data["usd"]
                set_cached_data(_price_cache, asset, price_data["usd"])
                
                # Cache dati estesi per analisi
                set_cached_data(_technical_cache, f"{asset}_data", price_data)
                
                logger.debug(f"Fetched {asset}: ${price_data['usd']:.2f}")
            else:
                logger.warning(f"No price data for asset: {asset}")
        
        # Combina cache + fetch
        all_prices = {**cached_prices, **fetched_prices}
        logger.info(f"Price fetch complete: {len(all_prices)}/{len(assets)} assets")
        return all_prices
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        if cached_prices:
            logger.info(f"Using cached prices due to API error: {len(cached_prices)} assets")
        return cached_prices
        
    except Exception as e:
        logger.error(f"Unexpected error in price fetch: {e}")
        return cached_prices

def get_technical_analysis(asset: str) -> Dict:
    """Analisi tecnica semplificata"""
    # Per ora simulata, in futuro collegare a API reali
    cached_analysis = get_cached_data(_technical_cache, f"{asset}_analysis", 3600)  # 1 ora cache
    
    if cached_analysis:
        return cached_analysis
    
    # Simula indicatori tecnici
    import random
    
    analysis = {
        "rsi": random.randint(20, 80),
        "macd_signal": random.choice(["BUY", "SELL", "NEUTRAL"]),
        "sma_20": random.uniform(0.8, 1.2),  # Moltiplicatore del prezzo attuale
        "support": random.uniform(0.85, 0.95),
        "resistance": random.uniform(1.05, 1.15),
        "sentiment": random.choice(["BULLISH", "BEARISH", "NEUTRAL"]),
        "volatility": random.uniform(0.1, 0.8)
    }
    
    set_cached_data(_technical_cache, f"{asset}_analysis", analysis)
    return analysis

def send_advanced_alert(chat_id: int, asset: str, price: float, threshold: float, alert_type: str):
    """Alert avanzato con analisi tecnica per utenti Premium"""
    try:
        subscription = get_user_subscription(chat_id)
        
        # Alert base per tutti
        percent_over = ((price - threshold) / threshold) * 100
        
        if percent_over >= 10:
            emoji = "🚀"
        elif percent_over >= 5:
            emoji = "📈"
        elif percent_over >= -5:
            emoji = "⚠️"
        elif percent_over >= -10:
            emoji = "📉"
        else:
            emoji = "💥"
        
        asset_name = asset.replace('-', ' ').upper()
        
        # Messaggio base
        message = f"""
{emoji} *ALERT: {asset_name}*

💰 Prezzo: *${price:,.2f}*
🎯 Soglia: ${threshold:,.2f}
📊 Variazione: *{percent_over:+.1f}%*
        """
        
        # Aggiungi analisi per Premium
        if subscription["type"] == "premium":
            try:
                analysis = get_technical_analysis(asset)
                
                rsi_emoji = "🟢" if analysis["rsi"] < 30 else "🔴" if analysis["rsi"] > 70 else "🟡"
                sentiment_emoji = {"BULLISH": "🐂", "BEARISH": "🐻", "NEUTRAL": "😐"}[analysis["sentiment"]]
                
                message += f"""

📈 *Analisi Tecnica:*
• RSI: {analysis["rsi"]} {rsi_emoji}
• MACD: {analysis["macd_signal"]}
• Sentiment: {analysis["sentiment"]} {sentiment_emoji}
• Support: ${price * analysis["support"]:.2f}
• Resistance: ${price * analysis["resistance"]:.2f}
                """
            except Exception as e:
                logger.error(f"Error getting technical analysis: {e}")
        
        message += f"\n🕐 {datetime.now().strftime('%H:%M - %d/%m/%Y')}"
        
        # Invia messaggio
        bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        # Log notifica
        log_notification(chat_id, asset, alert_type, price, threshold, message[:100])
        logger.info(f"Advanced alert sent: user={chat_id}, asset={asset}, price=${price:.2f}")
        
        return True
        
    except Unauthorized:
        logger.warning(f"User {chat_id} blocked the bot")
        return False
    except Exception as e:
        logger.error(f"Error sending advanced alert to {chat_id}: {e}")
        return False

def check_percentage_alerts(current_prices: Dict[str, float]):
    """Controlla alert percentuali (solo Premium)"""
    try:
        # Ottieni prezzi di 24h fa (simulato per ora)
        alerts_sent = 0
        
        for asset, current_price in current_prices.items():
            # Simula prezzo 24h fa (in futuro da API storica)
            price_24h_ago = current_price * (1 + ((-0.1 + 0.2) * hash(asset) % 100) / 1000)
            percent_change = ((current_price - price_24h_ago) / price_24h_ago) * 100
            
            # Alert per movimenti significativi (solo Premium)
            if abs(percent_change) > 15:  # Movimento > 15%
                # Trova utenti Premium interessati a questo asset
                from db import get_db
                
                with get_db() as conn:
                    cursor = conn.execute("""
                        SELECT DISTINCT s.chat_id 
                        FROM subscriptions s
                        JOIN users u ON s.chat_id = u.chat_id
                        WHERE s.asset = ? AND u.subscription_type = 'premium'
                        AND u.subscription_expires > datetime('now')
                    """, (asset,))
                    
                    premium_users = [row["chat_id"] for row in cursor.fetchall()]
                
                # Invia alert movimento significativo
                for chat_id in premium_users:
                    if should_send_notification(chat_id, asset, current_price, 0, "price_movement"):
                        try:
                            emoji = "🚀" if percent_change > 0 else "💥"
                            message = f"""
{emoji} *MOVIMENTO SIGNIFICATIVO*

📊 {asset.upper()}: {percent_change:+.1f}% (24h)
💰 Prezzo attuale: ${current_price:,.2f}
⏰ {datetime.now().strftime('%H:%M')}

📈 *Analisi Rapida:*
• Volatilità: {"Alta" if abs(percent_change) > 20 else "Media"}
• Trend: {"Bullish" if percent_change > 0 else "Bearish"}
                            """
                            
                            bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown'
                            )
                            
                            log_notification(chat_id, asset, "price_movement", current_price)
                            alerts_sent += 1
                            
                        except Exception as e:
                            logger.error(f"Error sending movement alert: {e}")
        
        if alerts_sent > 0:
            logger.info(f"Sent {alerts_sent} movement alerts")
            
    except Exception as e:
        logger.error(f"Error in percentage alerts: {e}")

def check_prices(context):
    """Job principale potenziato con multiple tipologie di alert"""
    global _last_cleanup
    
    try:
        logger.debug("Starting enhanced price check cycle")
        
        # Ottieni tutte le sottoscrizioni attive
        subscriptions = get_all_active_subscriptions()
        if not subscriptions:
            logger.debug("No active subscriptions")
            return
        
        # Estrai asset unici
        assets = list(set([sub["asset"] for sub in subscriptions]))
        logger.info(f"Checking prices for {len(assets)} assets, {len(subscriptions)} subscriptions")
        
        # Fetch prezzi
        current_prices = fetch_prices(assets)
        if not current_prices:
            logger.warning("No prices fetched - skipping cycle")
            return
        
        # Statistiche ciclo
        alerts_sent = 0
        total_checks = 0
        
        # Controlla alert tradizionali
        for sub in subscriptions:
            chat_id = sub["chat_id"]
            asset = sub["asset"]
            threshold = sub["threshold"]
            alert_type = sub["alert_type"]
            
            if asset not in current_prices:
                continue
            
            current_price = current_prices[asset]
            total_checks += 1
            
            # Verifica condizione alert
            alert_triggered = False
            
            if alert_type == "price_above" and current_price >= threshold:
                alert_triggered = True
            elif alert_type == "price_below" and current_price <= threshold:
                alert_triggered = True
            elif alert_type == "percent_change":
                # Implementazione futura per alert percentuali
                pass
            
            if alert_triggered:
                # Anti-spam check
                if should_send_notification(chat_id, asset, current_price, threshold, alert_type):
                    if send_advanced_alert(chat_id, asset, current_price, threshold, alert_type):
                        alerts_sent += 1
                else:
                    logger.debug(f"Skipped duplicate alert: user={chat_id}, asset={asset}")
        
        # Controlla alert percentuali per utenti Premium
        check_percentage_alerts(current_prices)
        
        # Log statistiche
        logger.info(f"Price check complete: {alerts_sent} alerts sent, {total_checks} checks performed")
        
        # Cleanup periodico
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
        logger.error(f"Critical error in enhanced price check: {e}")
        
        # Notifica admin errori critici
        if ADMIN_CHAT_ID:
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"❌ *Errore critico nel price check*\n"
                    f"🐛 {str(e)[:200]}",
                    parse_mode='Markdown'
                )
            except:
                pass

def fetch_crypto_news(limit: int = 5) -> List[Dict]:
    """Fetch crypto news con cache"""
    cached_news = get_cached_data(_news_cache, "latest_news", 1800)  # 30 min cache
    
    if cached_news:
        return cached_news
    
    try:
        response = requests.get(
            NEWS_API_URL,
            params={"per_page": limit},
            timeout=10,
            headers={"User-Agent": "CryptoAlertBot-Pro/2.0"}
        )
        response.raise_for_status()
        
        news_data = response.json()
        
        # Processa news
        processed_news = []
        for item in news_data.get("data", []):
            processed_news.append({
                "title": item.get("title", "")[:100],
                "description": item.get("description", "")[:200],
                "url": item.get("url", ""),
                "published_at": item.get("published_at", ""),
                "source": item.get("news_site", "")
            })
        
        set_cached_data(_news_cache, "latest_news", processed_news)
        logger.info(f"Fetched {len(processed_news)} crypto news")
        
        return processed_news
        
    except Exception as e:
        logger.error(f"Error fetching crypto news: {e}")
        return []

def send_daily_market_summary():
    """Invia riassunto giornaliero ai Premium (job schedulato)"""
    try:
        from db import get_db
        
        # Ottieni utenti Premium attivi
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT chat_id FROM users 
                WHERE subscription_type = 'premium' 
                AND subscription_expires > datetime('now')
            """)
            premium_users = [row["chat_id"] for row in cursor.fetchall()]
        
        if not premium_users:
            return
        
        # Genera riassunto mercato
        top_assets = ["bitcoin", "ethereum", "cardano", "solana", "polkadot"]
        prices = fetch_prices(top_assets)
        news = fetch_crypto_news(3)
        
        # Costruisci messaggio
        message = "📊 *Daily Market Summary*\n\n"
        
        # Top prezzi
        message += "💰 *Top Assets:*\n"
        for asset in top_assets:
            if asset in prices:
                price = prices[asset]
                message += f"• {asset.upper()}: ${price:,.2f}\n"
        
        # Top news
        message += "\n📰 *Latest News:*\n"
        for news_item in news[:3]:
            message += f"• {news_item['title'][:60]}...\n"
        
        message += f"\n🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        
        # Invia a tutti i Premium
        sent_count = 0
        for chat_id in premium_users:
            try:
                bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='Markdown'
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending daily summary to {chat_id}: {e}")
        
        logger.info(f"Daily market summary sent to {sent_count} premium users")
        
    except Exception as e:
        logger.error(f"Error in daily market summary: {e}")

def health_check() -> Dict:
    """Health check completo del sistema"""
    try:
        status = {
            "timestamp": datetime.now().isoformat(),
            "api_status": "unknown",
            "bot_status": "unknown",
            "database_status": "unknown",
            "cache_stats": {
                "price_cache_size": len(_price_cache),
                "news_cache_size": len(_news_cache),
                "technical_cache_size": len(_technical_cache)
            }
        }
        
        # Test API CoinGecko
        try:
            test_response = requests.get(
                f"{API_URL}?ids=bitcoin&vs_currencies=usd",
                timeout=10
            )
            status["api_status"] = "ok" if test_response.status_code == 200 else "error"
        except:
            status["api_status"] = "error"
        
        # Test Bot
        try:
            bot_info = bot.get_me()
            status["bot_status"] = "ok" if bot_info.username else "error"
        except:
            status["bot_status"] = "error"
        
        # Test Database
        try:
            from db import get_total_users
            users = get_total_users()
            status["database_status"] = "ok" if isinstance(users, int) else "error"
            status["total_users"] = users
        except:
            status["database_status"] = "error"
        
        logger.info(f"Health check completed: {status}")
        return status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

def cleanup_caches():
    """Pulizia periodica delle cache"""
    global _price_cache, _news_cache, _technical_cache
    
    now = datetime.now()
    
    # Pulisci cache scadute
    for cache_dict in [_price_cache, _news_cache, _technical_cache]:
        expired_keys = []
        for key, (data, timestamp) in cache_dict.items():
            if now - timestamp > timedelta(seconds=CACHE_DURATION * 2):
                expired_keys.append(key)
        
        for key in expired_keys:
            del cache_dict[key]
    
    logger.info(f"Cache cleanup: removed {len(expired_keys)} expired entries")

# Funzione di compatibilità per il sistema esistente
def get_all_unique_assets():
    """Compatibilità: wrapper per nuova struttura"""
    subscriptions = get_all_active_subscriptions()
    return list(set([sub["asset"] for sub in subscriptions]))

def get_subscribers_for(asset: str):
    """Compatibilità: wrapper per nuova struttura"""
    subscriptions = get_all_active_subscriptions()
    return [(sub["chat_id"], sub["threshold"]) for sub in subscriptions if sub["asset"] == asset]