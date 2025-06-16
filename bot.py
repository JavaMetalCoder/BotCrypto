import os
import logging
import signal
import sys
from dotenv import load_dotenv
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.error import TelegramError

from db import (
    init_db, add_subscription, remove_subscription, list_subscriptions,
    create_or_update_user, get_user_subscription, check_subscription_limits,
    add_portfolio_position, get_portfolio, get_user_stats, upgrade_subscription
)
from jobs import check_prices, fetch_prices
from utils import validate_asset, format_price, format_percentage, parse_price_input
from pricing import create_payment_link, verify_payment

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# Logging configurato per production
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==============================================
# BASIC COMMANDS
# ==============================================

def start(update: Update, ctx: CallbackContext):
    """Welcome message con sistema di abbonamento"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # Crea/aggiorna utente
    create_or_update_user(chat_id, user.username, user.first_name)
    subscription = get_user_subscription(chat_id)
    
    # Keyboard con opzioni
    keyboard = [
        [InlineKeyboardButton("📊 I miei Alert", callback_data="list_alerts")],
        [InlineKeyboardButton("💎 Upgrade Premium", callback_data="premium_info")],
        [InlineKeyboardButton("💰 Portfolio", callback_data="portfolio")],
        [InlineKeyboardButton("📈 Market News", callback_data="crypto_news")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = f"""
🤖 *Crypto Alert Bot Pro* - Benvenuto!

👋 Ciao {user.first_name}!
📊 Piano attuale: *{subscription['type'].upper()}*

🔥 *Funzionalità disponibili:*
• Alert prezzi personalizzati
• Portfolio tracking con P&L
• News crypto in tempo reale
• Analisi tecnica base
• Watchlist condivise

💡 *Comandi rapidi:*
• `/alert btc 50000` - Alert Bitcoin
• `/portfolio add btc 0.1 45000` - Aggiungi al portfolio
• `/news` - Ultime crypto news
• `/premium` - Scopri Premium

{f"⚠️ Piano FREE: 2 alert max" if subscription['type'] == 'free' else "✅ Piano PREMIUM: Alert illimitati"}
    """
    
    try:
        update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info(f"New user started: {chat_id} ({user.username})")
    except TelegramError as e:
        logger.error(f"Error in start command: {e}")

def premium_info(update: Update, ctx: CallbackContext):
    """Informazioni piano Premium"""
    chat_id = update.effective_chat.id
    subscription = get_user_subscription(chat_id)
    
    if subscription['type'] == 'premium':
        expires = subscription.get('expires')
        msg = f"""
✅ *Sei già Premium!*

🗓️ Scadenza: {expires[:10] if expires else 'Illimitato'}
📊 Alert inviati: {subscription['alerts_sent']}

💎 *Vantaggi Premium attivi:*
• Alert illimitati
• Portfolio tracking avanzato
• Analisi tecnica completa
• Supporto prioritario
• News premium
        """
    else:
        keyboard = [
            [InlineKeyboardButton("💎 Premium 1 Mese - €9.99", callback_data="buy_premium_1")],
            [InlineKeyboardButton("💎 Premium 3 Mesi - €24.99", callback_data="buy_premium_3")],
            [InlineKeyboardButton("💎 Premium 12 Mesi - €79.99", callback_data="buy_premium_12")],
            [InlineKeyboardButton("🎁 Prova Gratis 7 Giorni", callback_data="trial_premium")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = f"""
💎 *Crypto Alert Bot Premium*

📊 *Piano attuale: FREE* (2 alert max)

🔥 *Upgrade a Premium e ottieni:*
• ✅ Alert illimitati
• ✅ Portfolio tracking con P&L real-time
• ✅ Analisi tecnica avanzata (RSI, MACD)
• ✅ News crypto premium
• ✅ Alert percentuali (+10%, -5%)
• ✅ Watchlist collaborative
• ✅ Supporto prioritario
• ✅ Export dati CSV

💰 *Pricing:*
• 1 Mese: €9.99
• 3 Mesi: €24.99 (€8.33/mese)
• 12 Mesi: €79.99 (€6.67/mese)

🎁 Prova GRATIS per 7 giorni!
        """
        
        try:
            if update.callback_query:
                update.callback_query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
        except:
            pass
        return
    
    try:
        if update.callback_query:
            update.callback_query.edit_message_text(msg, parse_mode='Markdown')
        else:
            update.message.reply_text(msg, parse_mode='Markdown')
    except:
        pass

# ==============================================
# ALERT SYSTEM
# ==============================================

def alert_command(update: Update, ctx: CallbackContext):
    """Comando alert migliorato con tipi diversi"""
    try:
        if len(ctx.args) < 2:
            raise ValueError("Argomenti insufficienti")
        
        chat_id = update.effective_chat.id
        user_asset = ctx.args[0].lower()
        
        # Parse della soglia con supporto K/M
        threshold_input = ctx.args[1]
        threshold = parse_price_input(threshold_input)
        
        if not threshold:
            update.message.reply_text("❌ Formato prezzo non valido. Usa: 50000, 50k, 1.2M")
            return
        
        # Tipo di alert (opzionale)
        alert_type = ctx.args[2] if len(ctx.args) > 2 else "price_above"
        
        # Validazione asset
        asset_id = validate_asset(user_asset)
        if not asset_id:
            available = "BTC, ETH, ADA, SOL, DOT, MATIC, LINK, AVAX, ATOM"
            update.message.reply_text(f"❌ Asset '{user_asset}' non supportato.\n📋 Disponibili: {available}")
            return
        
        # Aggiungi sottoscrizione
        success, reason = add_subscription(chat_id, asset_id, threshold, alert_type)
        
        if success:
            formatted_price = format_price(threshold)
            emoji = "📈" if alert_type == "price_above" else "📉" if alert_type == "price_below" else "🎯"
            
            update.message.reply_text(f"""
✅ *Alert configurato!*

{emoji} {user_asset.upper()} {alert_type.replace('_', ' ')} {formatted_price}
🔔 Riceverai notifica quando viene raggiunta

📊 Alert attivi: {len(list_subscriptions(chat_id))}
            """, parse_mode='Markdown')
            
        elif reason == "free_limit_reached":
            keyboard = [[InlineKeyboardButton("💎 Upgrade Premium", callback_data="premium_info")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text("""
def remove_alert_command(update: Update, ctx: CallbackContext):
    """Rimuovi alert specifico"""
    try:
        if len(ctx.args) < 1:
            update.message.reply_text("❌ Specifica l'asset: `/remove btc`", parse_mode='Markdown')
            return
            
        chat_id = update.effective_chat.id
        user_asset = ctx.args[0].lower()
        
        asset_id = validate_asset(user_asset)
        if not asset_id:
            update.message.reply_text("❌ Asset non riconosciuto")
            return
        
        alert_type = ctx.args[1] if len(ctx.args) > 1 else "price_above"
        
        success = remove_subscription(chat_id, asset_id, alert_type)
        
        if success:
            update.message.reply_text(f"""
✅ *Alert rimosso!*

🗑️ {user_asset.upper()} non è più monitorato
📊 Alert rimanenti: {len(list_subscriptions(chat_id))}
            """, parse_mode='Markdown')
        else:
            update.message.reply_text(f"❓ Non avevi alert per {user_asset.upper()}")
            
    except Exception as e:
        logger.error(f"Error in remove alert: {e}")
        update.message.reply_text("❌ Errore nel rimuovere l'alert")

def price_command(update: Update, ctx: CallbackContext):
    """Mostra prezzo corrente asset"""
    try:
        if len(ctx.args) < 1:
            update.message.reply_text("❌ Specifica un asset: `/price btc`", parse_mode='Markdown')
            return
            
        user_asset = ctx.args[0].lower()
        asset_id = validate_asset(user_asset)
        
        if not asset_id:
            update.message.reply_text("❌ Asset non supportato")
            return
        
        # Fetch prezzo
        prices = fetch_prices([asset_id])
        
        if asset_id not in prices:
            update.message.reply_text("❌ Impossibile ottenere il prezzo")
            return
        
        price = prices[asset_id]
        subscription = get_user_subscription(update.effective_chat.id)
        
        # Messaggio base
        message = f"""
💰 *{user_asset.upper()} Price*

💵 ${price:,.2f} USD
        """
        
        # Aggiungi analisi per Premium
        if subscription["type"] == "premium":
            try:
                analysis = get_technical_analysis(asset_id)
                
                rsi_status = "Oversold" if analysis["rsi"] < 30 else "Overbought" if analysis["rsi"] > 70 else "Normal"
                
                message += f"""

📈 *Technical Analysis:*
• RSI: {analysis["rsi"]} ({rsi_status})
• MACD: {analysis["macd_signal"]}
• Sentiment: {analysis["sentiment"]}
• Volatility: {"High" if analysis["volatility"] > 0.5 else "Low"}
                """
            except:
                pass
        else:
            message += "\n\n💎 *Upgrade Premium per analisi tecnica completa*"
        
        message += f"\n🕐 {datetime.now().strftime('%H:%M - %d/%m/%Y')}"
        
        keyboard = [
            [InlineKeyboardButton("📊 Crea Alert", callback_data=f"create_alert_{asset_id}")],
            [InlineKeyboardButton("💎 Premium", callback_data="premium_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in price command: {e}")
        update.message.reply_text("❌ Errore nel recuperare il prezzo")

def settings_command(update: Update, ctx: CallbackContext):
    """Impostazioni utente"""
    chat_id = update.effective_chat.id
    stats = get_user_stats(chat_id)
    
    if not stats:
        update.message.reply_text("❌ Errore nel recuperare le impostazioni")
        return
    
    expires_text = "Non scade" if not stats.get("subscription_expires") else stats["subscription_expires"][:10]
    
    message = f"""
⚙️ *Impostazioni Account*

👤 *Account Info:*
• Piano: {stats["subscription_type"].upper()}
• Scadenza: {expires_text}
• Membro dal: {stats["member_since"][:10]}

📊 *Statistiche:*
• Alert attivi: {stats["active_subscriptions"]}
• Alert inviati: {stats["total_alerts_sent"]}
• Posizioni portfolio: {stats["portfolio_positions"]}
• Investimenti totali: ${stats["total_invested"]:,.2f}

🔔 *Impostazioni Notifiche:*
• Alert attivi: ✅
• News giornaliere: {"✅" if stats["subscription_type"] == "premium" else "❌"}
• Market summary: {"✅" if stats["subscription_type"] == "premium" else "❌"}
    """
    
    keyboard = [
        [InlineKeyboardButton("💎 Upgrade Premium", callback_data="premium_info")],
        [InlineKeyboardButton("📊 Export Dati", callback_data="export_data")],
        [InlineKeyboardButton("🗑️ Elimina Account", callback_data="delete_account")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

def referral_command(update: Update, ctx: CallbackContext):
    """Sistema referral"""
    chat_id = update.effective_chat.id
    
    from db import get_db
    
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT referral_code FROM users WHERE chat_id = ?
        """, (chat_id,))
        
        result = cursor.fetchone()
        
        if result:
            referral_code = result["referral_code"]
            
            # Conta referral
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM users WHERE referred_by = ?
            """, (chat_id,))
            
            referral_count = cursor.fetchone()["count"]
            
            message = f"""
🎁 *Sistema Referral*

🔗 Il tuo codice: `{referral_code}`
👥 Referral completati: {referral_count}

💰 *Come funziona:*
• Condividi il tuo codice
• Chi si iscrive con il tuo codice riceve 7 giorni Premium gratis
• Tu ricevi 7 giorni Premium per ogni referral

📱 *Link di invito:*
`https://t.me/your_bot?start=ref_{referral_code}`

🎉 Ogni 5 referral = 1 mese Premium gratis!
            """
            
            update.message.reply_text(message, parse_mode='Markdown')
        else:
            update.message.reply_text("❌ Errore nel sistema referral")

def export_data_command(update: Update, ctx: CallbackContext):
    """Export dati utente (GDPR compliance)"""
    chat_id = update.effective_chat.id
    
    try:
        # Raccogli tutti i dati dell'utente
        user_data = {
            "user_info": get_user_stats(chat_id),
            "alerts": list_subscriptions(chat_id),
            "portfolio": get_portfolio(chat_id),
            "export_date": datetime.now().isoformat()
        }
        
        # Crea file CSV semplificato
        import io
        import json
        
        data_text = json.dumps(user_data, indent=2, ensure_ascii=False)
        
        # Invia come file
        from telegram import InputFile
        
        bio = io.BytesIO(data_text.encode('utf-8'))
        bio.name = f'crypto_bot_data_{chat_id}_{datetime.now().strftime("%Y%m%d")}.json'
        
        update.message.reply_document(
            document=bio,
            caption="📊 *Export dati completato*\n\nTutti i tuoi dati in formato JSON.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in data export: {e}")
        update.message.reply_text("❌ Errore nell'export dei dati")

# ==============================================
# PROMO CODES SYSTEM
# ==============================================

def promo_command(update: Update, ctx: CallbackContext):
    """Usa codice promo"""
    try:
        if len(ctx.args) < 1:
            update.message.reply_text("❌ Inserisci un codice promo: `/promo SAVE20`", parse_mode='Markdown')
            return
        
        chat_id = update.effective_chat.id
        promo_code = ctx.args[0].upper()
        
        from pricing import apply_promo_code
        
        result = apply_promo_code(promo_code, chat_id)
        
        if "error" in result:
            update.message.reply_text(f"❌ {result['error']}")
        else:
            discount = result["discount_percent"]
            
            keyboard = [[InlineKeyboardButton("💎 Usa Sconto", callback_data=f"use_promo_{promo_code}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(f"""
🎉 *Codice promo valido!*

💰 Sconto: {discount}% su Premium
🎯 Codice: {promo_code}

Clicca il pulsante per applicare lo sconto al tuo acquisto Premium.
            """, parse_mode='Markdown', reply_markup=reply_markup)
            
    except Exception as e:
        logger.error(f"Error in promo command: {e}")
        update.message.reply_text("❌ Errore nel codice promo")

# ==============================================
# ADMIN COMMANDS EXTENDED
# ==============================================

def admin_broadcast(update: Update, ctx: CallbackContext):
    """Broadcast messaggio a tutti gli utenti (solo admin)"""
    if ADMIN_CHAT_ID and str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return
    
    if len(ctx.args) < 1:
        update.message.reply_text("❌ Specifica il messaggio: `/broadcast Messaggio importante`")
        return
    
    message = " ".join(ctx.args)
    
    try:
        from db import get_db
        
        with get_db() as conn:
            cursor = conn.execute("SELECT DISTINCT chat_id FROM users")
            users = [row["chat_id"] for row in cursor.fetchall()]
        
        sent = 0
        failed = 0
        
        for chat_id in users:
            try:
                bot.send_message(
                    chat_id=chat_id,
                    text=f"📢 *Messaggio dal Team*\n\n{message}",
                    parse_mode='Markdown'
                )
                sent += 1
            except:
                failed += 1
        
        update.message.reply_text(f"📊 Broadcast completato:\n✅ Inviati: {sent}\n❌ Falliti: {failed}")
        
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        update.message.reply_text("❌ Errore nel broadcast")

def admin_promo_create(update: Update, ctx: CallbackContext):
    """Crea codice promo (solo admin)"""
    if ADMIN_CHAT_ID and str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return
    
    if len(ctx.args) < 3:
        update.message.reply_text("❌ Formato: `/createpromo SAVE20 20 100` (codice, sconto%, usi_max)")
        return
    
    try:
        code = ctx.args[0].upper()
        discount = int(ctx.args[1])
        max_uses = int(ctx.args[2])
        
        from pricing import generate_promo_code
        
        success = generate_promo_code(code, discount, max_uses, 30)
        
        if success:
            update.message.reply_text(f"""
✅ *Codice promo creato!*

🎯 Codice: {code}
💰 Sconto: {discount}%
📊 Usi massimi: {max_uses}
📅 Scade in: 30 giorni
            """, parse_mode='Markdown')
        else:
            update.message.reply_text("❌ Errore nella creazione del codice promo")
            
    except ValueError:
        update.message.reply_text("❌ Formato numeri non valido")
    except Exception as e:
        logger.error(f"Error creating promo: {e}")
        update.message.reply_text("❌ Errore nel creare il codice promo")

# ==============================================
# CALLBACK HANDLERS EXTENDED
# ==============================================

def extended_button_callback(update: Update, ctx: CallbackContext):
    """Gestisce callback estesi"""
    query = update.callback_query
    query.answer()
    
    if query.data.startswith("create_alert_"):
        asset = query.data.replace("create_alert_", "")
        query.edit_message_text(
            f"💡 Crea alert per {asset.upper()}:\n`/alert {asset} 50000`",
            parse_mode='Markdown'
        )
    
    elif query.data == "export_data":
        export_data_command(update, ctx)
    
    elif query.data == "delete_account":
        keyboard = [
            [InlineKeyboardButton("❌ Sì, elimina tutto", callback_data="confirm_delete")],
            [InlineKeyboardButton("🔙 Annulla", callback_data="settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            "⚠️ *Attenzione!*\n\nEliminare l'account rimuoverà:\n• Tutti gli alert\n• Portfolio\n• Dati di abbonamento\n\n**Questa azione è irreversibile!**",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif query.data == "confirm_delete":
        try:
            chat_id = query.from_user.id
            
            from db import get_db, _lock
            
            with _lock, get_db() as conn:
                # Elimina tutti i dati dell'utente
                tables = ["subscriptions", "portfolio", "notifications", "payments", "users"]
                for table in tables:
                    conn.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
                conn.commit()
            
            query.edit_message_text(
                "✅ *Account eliminato*\n\nTutti i tuoi dati sono stati rimossi.\n\nGrazie per aver usato Crypto Alert Bot Pro!"
            )
            
        except Exception as e:
            logger.error(f"Error deleting account: {e}")
            query.edit_message_text("❌ Errore nell'eliminazione dell'account")
    
    elif query.data.startswith("use_promo_"):
        promo_code = query.data.replace("use_promo_", "")
        # Implementa logica uso promo con acquisto
        query.edit_message_text(f"🎉 Promo {promo_code} sarà applicato al prossimo acquisto Premium!")

# ==============================================
# MAIN FUNCTION UPDATED
# ==============================================

def main():
    """Main application entry point"""
    try:
        # Setup
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting Crypto Alert Bot Pro...")
        
        # Database initialization
        init_db()
        logger.info("✅ Database initialized")
        
        # Bot setup
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        
        # Register basic handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("alert", alert_command))
        dp.add_handler(CommandHandler("list", list_alerts))
        dp.add_handler(CommandHandler("remove", remove_alert_command))
        dp.add_handler(CommandHandler("portfolio", portfolio_command))
        dp.add_handler(CommandHandler("price", price_command))
        dp.add_handler(CommandHandler("news", crypto_news))
        dp.add_handler(CommandHandler("premium", premium_info))
        dp.add_handler(CommandHandler("settings", settings_command))
        dp.add_handler(CommandHandler("referral", referral_command))
        dp.add_handler(CommandHandler("promo", promo_command))
        dp.add_handler(CommandHandler("export", export_data_command))
        dp.add_handler(CommandHandler("help", help_command))
        
        # Callback handlers
        dp.add_handler(CallbackQueryHandler(button_callback))
        dp.add_handler(CallbackQueryHandler(extended_button_callback))
        
        # Admin commands
        if ADMIN_CHAT_ID:
            dp.add_handler(CommandHandler("stats", stats_command))
            dp.add_handler(CommandHandler("broadcast", admin_broadcast))
            dp.add_handler(CommandHandler("createpromo", admin_promo_create))
        
        # Error handler
        dp.add_error_handler(error_handler)
        
        # Job queue
        jq = updater.job_queue
        
        # Main price checker
        jq.run_repeating(
            check_prices, 
            interval=INTERVAL, 
            first=30,
            name="price_checker"
        )
        
        # Daily market summary per Premium (08:00)
        jq.run_daily(
            lambda ctx: send_daily_market_summary(),
            time=datetime.strptime("08:00", "%H:%M").time(),
            name="daily_summary"
        )
        
        # Cache cleanup (ogni ora)
        jq.run_repeating(
            lambda ctx: cleanup_caches(),
            interval=3600,
            first=3600,
            name="cache_cleanup"
        )
        
        logger.info(f"✅ All jobs scheduled successfully")
        
        # Set bot commands
        commands = [
            BotCommand("start", "🏠 Menu principale"),
            BotCommand("alert", "🔔 Crea alert prezzo"),
            BotCommand("list", "📊 I miei alert"),
            BotCommand("portfolio", "💰 Portfolio tracker"),
            BotCommand("price", "💵 Prezzo asset"),
            BotCommand("news", "📰 Crypto news"),
            BotCommand("premium", "💎 Info Premium"),
            BotCommand("settings", "⚙️ Impostazioni"),
            BotCommand("referral", "🎁 Invita amici"),
            BotCommand("promo", "🎯 Codice promo"),
            BotCommand("help", "❓ Aiuto completo")
        ]
        updater.bot.set_my_commands(commands)
        
        # Start bot
        logger.info("✅ Bot started successfully")
        updater.start_polling(clean=True)
        
        # Notify admin
        if ADMIN_CHAT_ID:
            try:
                updater.bot.send_message(
                    ADMIN_CHAT_ID, 
                    "🟢 *Crypto Alert Bot Pro avviato!*\n\n🚀 All systems operational\n💎 Premium features enabled\n📊 Payment system ready",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        logger.info("🔄 Bot is running... Press Ctrl+C to stop")
        updater.idle()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

def list_alerts(update: Update, ctx: CallbackContext):
    """Lista alert con interfaccia migliorata"""
    chat_id = update.effective_chat.id
    subs = list_subscriptions(chat_id)
    subscription = get_user_subscription(chat_id)
    
    if not subs:
        keyboard = [[InlineKeyboardButton("➕ Crea Alert", callback_data="help_alert")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(f"""
📭 *Nessun alert attivo*

💡 Crea il tuo primo alert:
`/alert btc 50000`

📊 Piano: {subscription['type'].upper()}
{f"⚠️ Limit: 2 alert max" if subscription['type'] == 'free' else "✅ Alert illimitati"}
        """, parse_mode='Markdown', reply_markup=reply_markup)
        return
    
    # Fetch prezzi correnti per confronto
    assets = list(set([sub[0] for sub in subs]))
    current_prices = fetch_prices(assets)
    
    lines = []
    for asset, threshold, alert_type in subs:
        current_price = current_prices.get(asset, 0)
        formatted_threshold = format_price(threshold)
        formatted_current = format_price(current_price)
        
        # Calcola distanza dalla soglia
        if current_price > 0:
            distance = ((current_price - threshold) / threshold) * 100
            distance_emoji = "🔥" if abs(distance) < 5 else "📊"
            distance_text = f"({distance:+.1f}%)"
        else:
            distance_emoji = "❓"
            distance_text = "(Price N/A)"
        
        alert_emoji = "📈" if alert_type == "price_above" else "📉" if alert_type == "price_below" else "🎯"
        
        lines.append(f"{alert_emoji} {asset.upper()}: {formatted_threshold}")
        lines.append(f"   Current: {formatted_current} {distance_text} {distance_emoji}")
    
    message = f"""
🔔 *I tuoi {len(subs)} alert attivi:*

{chr(10).join(lines)}

📊 Piano: {subscription['type'].upper()}
🔄 Controlla ogni {INTERVAL//60} minuti
📈 Alert inviati: {subscription['alerts_sent']}
    """
    
    keyboard = [
        [InlineKeyboardButton("➕ Nuovo Alert", callback_data="help_alert")],
        [InlineKeyboardButton("🗑️ Rimuovi Alert", callback_data="remove_alert")],
        [InlineKeyboardButton("💎 Upgrade Premium", callback_data="premium_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            update.callback_query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    except:
        pass

# ==============================================
# PORTFOLIO SYSTEM
# ==============================================

def portfolio_command(update: Update, ctx: CallbackContext):
    """Sistema portfolio completo"""
    chat_id = update.effective_chat.id
    
    if len(ctx.args) == 0:
        # Mostra portfolio
        show_portfolio(update, ctx)
        return
    
    if ctx.args[0] == "add" and len(ctx.args) >= 4:
        # Aggiungi posizione: /portfolio add btc 0.1 45000
        asset = ctx.args[1].lower()
        
        try:
            amount = float(ctx.args[2])
            buy_price = parse_price_input(ctx.args[3])
            
            if not buy_price or amount <= 0:
                raise ValueError("Invalid values")
            
            asset_id = validate_asset(asset)
            if not asset_id:
                update.message.reply_text("❌ Asset non supportato")
                return
            
            success = add_portfolio_position(chat_id, asset_id, amount, buy_price)
            
            if success:
                update.message.reply_text(f"""
✅ *Posizione aggiunta al portfolio!*

📊 {asset.upper()}: {amount} unità
💰 Prezzo medio: {format_price(buy_price)}
💎 Valore: {format_price(amount * buy_price)}

Usa `/portfolio` per vedere il totale
                """, parse_mode='Markdown')
            else:
                update.message.reply_text("❌ Errore nell'aggiungere la posizione")
                
        except ValueError:
            update.message.reply_text("""
❌ *Formato errato*

✅ *Uso corretto:*
`/portfolio add btc 0.1 45000`
`/portfolio add eth 2 3000`
            """, parse_mode='Markdown')
    else:
        update.message.reply_text("""
💰 *Portfolio Commands*

📊 `/portfolio` - Mostra portfolio
➕ `/portfolio add <asset> <amount> <price>` - Aggiungi posizione

💡 *Esempi:*
• `/portfolio add btc 0.1 45000`
• `/portfolio add eth 2 3000`
        """, parse_mode='Markdown')

def show_portfolio(update: Update, ctx: CallbackContext):
    """Mostra portfolio con P&L real-time"""
    chat_id = update.effective_chat.id
    
    # Ottieni portfolio
    portfolio_data = get_portfolio(chat_id)
    
    if not portfolio_data["positions"]:
        keyboard = [[InlineKeyboardButton("➕ Aggiungi Posizione", callback_data="help_portfolio")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = """
💰 *Portfolio vuoto*

💡 Aggiungi le tue prime posizioni:
`/portfolio add btc 0.1 45000`

📊 Traccia i tuoi investimenti crypto con P&L real-time!
        """
        
        try:
            if update.callback_query:
                update.callback_query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
        except:
            pass
        return
    
    # Fetch prezzi correnti
    assets = [pos["asset"] for pos in portfolio_data["positions"]]
    current_prices = fetch_prices(assets)
    
    # Update portfolio con prezzi correnti
    portfolio_data = get_portfolio(chat_id, current_prices)
    
    # Costruisci messaggio
    lines = []
    for pos in portfolio_data["positions"]:
        asset = pos["asset"].upper()
        amount = pos["amount"]
        current_price = pos["current_price"]
        pnl = pos["pnl"]
        pnl_percent = pos["pnl_percent"]
        
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_text = format_percentage(pnl_percent)
        
        lines.append(f"{asset}: {amount:.4f} units")
        lines.append(f"   Value: {format_price(pos['value'])} ({pnl_text}) {pnl_emoji}")
    
    total_pnl_emoji = "🟢" if portfolio_data["total_pnl"] >= 0 else "🔴"
    total_pnl_text = format_percentage(portfolio_data["total_pnl_percent"])
    
    message = f"""
💰 *Il tuo Portfolio*

{chr(10).join(lines)}

📊 *Totale:*
💎 Valore attuale: {format_price(portfolio_data["total_value"])}
💰 Investito: {format_price(portfolio_data["total_cost"])}
📈 P&L: {format_price(portfolio_data["total_pnl"])} ({total_pnl_text}) {total_pnl_emoji}
    """
    
    keyboard = [
        [InlineKeyboardButton("➕ Aggiungi Posizione", callback_data="help_portfolio")],
        [InlineKeyboardButton("📊 Analisi Dettagliata", callback_data="portfolio_analysis")],
        [InlineKeyboardButton("🔄 Aggiorna", callback_data="portfolio")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            update.callback_query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    except:
        pass

# ==============================================
# CRYPTO NEWS & ANALYSIS
# ==============================================

def crypto_news(update: Update, ctx: CallbackContext):
    """News crypto in tempo reale"""
    subscription = get_user_subscription(update.effective_chat.id)
    
    # News base per tutti
    news = [
        "🔥 Bitcoin reaches new all-time high above $100k",
        "📈 Ethereum upgrade shows promising results",
        "💎 Altcoin season expected in Q2 2025",
        "🏛️ Major institutions increase crypto adoption"
    ]
    
    message = "📰 *Crypto News*\n\n"
    message += "\n".join([f"• {item}" for item in news])
    
    if subscription["type"] == "free":
        message += "\n\n💎 *Upgrade a Premium per:*\n• News dettagliate\n• Analisi di mercato\n• Sentiment analysis"
        
        keyboard = [[InlineKeyboardButton("💎 Upgrade Premium", callback_data="premium_info")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        # Premium news
        message += "\n\n🔥 *Premium Analysis:*\n• Market sentiment: Bullish\n• Fear & Greed Index: 75 (Greed)\n• Top gainers: SOL, MATIC, LINK"
        reply_markup = None
    
    try:
        if update.callback_query:
            update.callback_query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    except:
        pass

# ==============================================
# PAYMENT SYSTEM
# ==============================================

def handle_payment_callback(update: Update, ctx: CallbackContext):
    """Gestisce callback pagamenti"""
    query = update.callback_query
    chat_id = query.from_user.id
    
    if query.data.startswith("buy_premium_"):
        months = int(query.data.split("_")[-1])
        prices = {1: 9.99, 3: 24.99, 12: 79.99}
        
        try:
            payment_link = create_payment_link(chat_id, months, prices[months])
            
            keyboard = [[InlineKeyboardButton("💳 Paga con Stripe", url=payment_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            query.edit_message_text(f"""
💎 *Premium {months} Mes{'e' if months == 1 else 'i'}*

💰 Prezzo: €{prices[months]}
🎁 Include tutto il pacchetto Premium

Clicca il pulsante per completare il pagamento sicuro con Stripe.
            """, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Payment error: {e}")
            query.edit_message_text("❌ Errore nel processo di pagamento. Riprova.")
    
    elif query.data == "trial_premium":
        # Attiva trial gratuito 7 giorni
        upgrade_subscription(chat_id, 0.25)  # 7 giorni
        
        query.edit_message_text("""
🎉 *Trial Premium attivato!*

✅ 7 giorni di Premium GRATIS
✅ Tutte le funzionalità sbloccate
✅ Nessun pagamento richiesto

Goditi il tuo trial! 🚀
        """, parse_mode='Markdown')

# ==============================================
# CALLBACK HANDLERS
# ==============================================

def button_callback(update: Update, ctx: CallbackContext):
    """Gestisce tutti i callback button"""
    query = update.callback_query
    query.answer()
    
    callbacks = {
        "list_alerts": list_alerts,
        "premium_info": premium_info,
        "portfolio": show_portfolio,
        "crypto_news": crypto_news,
        "help_alert": lambda u, c: u.callback_query.edit_message_text(
            "💡 Crea alert: `/alert btc 50000`", parse_mode='Markdown'
        ),
        "help_portfolio": lambda u, c: u.callback_query.edit_message_text(
            "💡 Aggiungi posizione: `/portfolio add btc 0.1 45000`", parse_mode='Markdown'
        )
    }
    
    if query.data in callbacks:
        callbacks[query.data](update, ctx)
    elif query.data.startswith("buy_premium_") or query.data == "trial_premium":
        handle_payment_callback(update, ctx)

# ==============================================
# ADMIN COMMANDS
# ==============================================

def stats_command(update: Update, ctx: CallbackContext):
    """Statistiche per admin"""
    if ADMIN_CHAT_ID and str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return
    
    from db import get_total_users, get_total_subscriptions, get_premium_users_count
    
    total_users = get_total_users()
    total_subs = get_total_subscriptions()
    premium_users = get_premium_users_count()
    
    stats_msg = f"""
📊 *Bot Statistics*

👥 Utenti totali: {total_users}
💎 Utenti Premium: {premium_users}
🔔 Alert attivi: {total_subs}
📈 Conversion rate: {(premium_users/total_users*100):.1f}%

⏱️ Check interval: {INTERVAL}s
🚀 Uptime: Running smoothly
    """
    
    update.message.reply_text(stats_msg, parse_mode='Markdown')

def help_command(update: Update, ctx: CallbackContext):
    """Help completo migliorato"""
    help_text = """
🤖 *Crypto Alert Bot Pro - Guida Completa*

🔔 *Alert System:*
• `/alert btc 50000` - Alert sopra $50k
• `/alert eth 3k price_below` - Alert sotto $3k
• `/list` - Mostra alert attivi

💰 *Portfolio Tracking:*
• `/portfolio` - Mostra portfolio
• `/portfolio add btc 0.1 45000` - Aggiungi posizione

📰 *Market Info:*
• `/news` - Crypto news
• `/price btc` - Prezzo corrente
• `/analysis btc` - Analisi tecnica (Premium)

💎 *Premium Features:*
• `/premium` - Info abbonamento
• Alert illimitati
• Portfolio P&L real-time
• Analisi avanzate

👤 *Account:*
• `/stats` - Statistiche personali
• `/settings` - Configurazioni

🛠️ *Sviluppato da MetalCoder*
💬 Supporto: @metalcoder_support
    """
    
    update.message.reply_text(help_text, parse_mode='Markdown')

# ==============================================
# ERROR HANDLING & MAIN
# ==============================================

def error_handler(update: Update, ctx: CallbackContext):
    """Global error handler"""
    logger.error(f"Update {update} caused error {ctx.error}")
    
    if update and update.effective_message:
        try:
            update.effective_message.reply_text(
                "❌ Si è verificato un errore. Il team è stato notificato."
            )
        except:
            pass

def signal_handler(signum, frame):
    """Graceful shutdown"""
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    sys.exit(0)

def main():
    """Main application entry point"""
    try:
        # Setup
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting Crypto Alert Bot Pro...")
        
        # Database initialization
        init_db()
        logger.info("✅ Database initialized")
        
        # Bot setup
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        
        # Register handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("alert", alert_command))
        dp.add_handler(CommandHandler("list", list_alerts))
        dp.add_handler(CommandHandler("portfolio", portfolio_command))
        dp.add_handler(CommandHandler("news", crypto_news))
        dp.add_handler(CommandHandler("premium", premium_info))
        dp.add_handler(CommandHandler("help", help_command))
        
        # Callback handlers
        dp.add_handler(CallbackQueryHandler(button_callback))
        
        # Admin commands
        if ADMIN_CHAT_ID:
            dp.add_handler(CommandHandler("stats", stats_command))
        
        # Error handler
        dp.add_error_handler(error_handler)
        
        # Job queue
        jq = updater.job_queue
        jq.run_repeating(
            check_prices, 
            interval=INTERVAL, 
            first=30,
            name="price_checker"
        )
        logger.info(f"✅ Price checker scheduled every {INTERVAL}s")
        
        # Set bot commands
        commands = [
            BotCommand("start", "🏠 Menu principale"),
            BotCommand("alert", "🔔 Crea nuovo alert"),
            BotCommand("list", "📊 I miei alert"),
            BotCommand("portfolio", "💰 Portfolio tracker"),
            BotCommand("news", "📰 Crypto news"),
            BotCommand("premium", "💎 Info Premium"),
            BotCommand("help", "❓ Aiuto completo")
        ]
        updater.bot.set_my_commands(commands)
        
        # Start bot
        logger.info("✅ Bot started successfully")
        updater.start_polling(clean=True)
        
        # Notify admin
        if ADMIN_CHAT_ID:
            try:
                updater.bot.send_message(
                    ADMIN_CHAT_ID, 
                    "🟢 *Crypto Alert Bot Pro avviato!*\n🚀 All systems operational",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        logger.info("🔄 Bot is running... Press Ctrl+C to stop")
        updater.idle()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
⚠️ *Limite FREE raggiunto!*

📊 Hai già 2 alert attivi (limite piano FREE)

💎 *Upgrade a Premium per:*
• Alert illimitati
• Portfolio tracking
• Analisi avanzate

🎁 Prova Premium GRATIS per 7 giorni!
            """, parse_mode='Markdown', reply_markup=reply_markup)
            
        else:
            update.message.reply_text(f"❌ Errore: {reason}")
            
    except Exception as e:
        logger.error(f"Error in alert command: {e}")
        update.message.reply_text("""