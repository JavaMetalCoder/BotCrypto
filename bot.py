import os
import logging
import signal
import sys
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.error import TelegramError

from db import init_db, add_subscription, remove_subscription, list_subscriptions
from jobs import check_prices
from utils import validate_asset, format_price

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # 5 min default
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Logging configurato per production
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def start(update: Update, ctx: CallbackContext):
    """Welcome message con istruzioni complete"""
    welcome_msg = (
        "🤖 *Crypto Alert Bot* attivo!\n\n"
        "💡 *Comandi disponibili:*\n"
        "• `/subscribe btc 50000` - Alert quando BTC >= $50,000\n"
        "• `/unsubscribe btc` - Rimuovi alert BTC\n"
        "• `/list` - Mostra tutti i tuoi alert\n"
        "• `/help` - Aiuto completo\n\n"
        "📊 *Asset supportati:* BTC, ETH, ADA, SOL, DOT, MATIC, LINK..."
    )
    
    try:
        update.message.reply_text(welcome_msg, parse_mode='Markdown')
        logger.info(f"New user started: {update.effective_user.id}")
    except TelegramError as e:
        logger.error(f"Error in start command: {e}")

def subscribe(update: Update, ctx: CallbackContext):
    """Sottoscrivi alert con validazione robusta"""
    try:
        if len(ctx.args) != 2:
            raise ValueError("Argomenti insufficienti")
            
        chat_id = update.effective_chat.id
        user_asset = ctx.args[0].lower()
        threshold = float(ctx.args[1])
        
        # Validazione asset
        asset_id = validate_asset(user_asset)
        if not asset_id:
            available = ", ".join(["BTC", "ETH", "ADA", "SOL", "DOT", "MATIC", "LINK"])
            update.message.reply_text(
                f"❌ Asset '{user_asset}' non supportato.\n"
                f"📋 Disponibili: {available}"
            )
            return
            
        # Validazione soglia
        if threshold <= 0:
            update.message.reply_text("❌ La soglia deve essere > 0")
            return
            
        if threshold > 1000000:
            update.message.reply_text("❌ Soglia troppo alta (max $1M)")
            return
        
        # Controlla duplicati
        existing_subs = list_subscriptions(chat_id)
        for existing_asset, _ in existing_subs:
            if existing_asset == asset_id:
                update.message.reply_text(
                    f"⚠️ Hai già un alert per {user_asset.upper()}.\n"
                    f"Usa `/unsubscribe {user_asset}` prima di crearne uno nuovo."
                )
                return
        
        # Limite sottoscrizioni per user
        if len(existing_subs) >= 10:
            update.message.reply_text("❌ Limite massimo: 10 alert per utente")
            return
            
        add_subscription(chat_id, asset_id, threshold)
        formatted_price = format_price(threshold)
        
        update.message.reply_text(
            f"✅ *Alert configurato!*\n"
            f"📈 {user_asset.upper()} >= {formatted_price}\n"
            f"🔔 Riceverai notifica quando viene raggiunta",
            parse_mode='Markdown'
        )
        
        logger.info(f"Subscription added: user={chat_id}, asset={asset_id}, threshold={threshold}")
        
    except (IndexError, ValueError):
        update.message.reply_text(
            "❌ *Formato errato*\n\n"
            "✅ *Uso corretto:*\n"
            "`/subscribe btc 50000`\n"
            "`/subscribe eth 3000`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in subscribe: {e}")
        update.message.reply_text("❌ Errore interno. Riprova tra poco.")

def unsubscribe(update: Update, ctx: CallbackContext):
    """Rimuovi sottoscrizione con feedback chiaro"""
    try:
        if len(ctx.args) != 1:
            raise ValueError("Argomenti errati")
            
        chat_id = update.effective_chat.id
        user_asset = ctx.args[0].lower()
        asset_id = validate_asset(user_asset)
        
        if not asset_id:
            update.message.reply_text(f"❌ Asset '{user_asset}' non riconosciuto")
            return
            
        removed = remove_subscription(chat_id, asset_id)
        
        if removed:
            update.message.reply_text(
                f"🚫 *Alert rimosso*\n"
                f"📉 {user_asset.upper()} non è più monitorato",
                parse_mode='Markdown'
            )
            logger.info(f"Subscription removed: user={chat_id}, asset={asset_id}")
        else:
            update.message.reply_text(
                f"❓ Non avevi alert attivi per {user_asset.upper()}\n"
                f"Usa `/list` per vedere i tuoi alert"
            )
            
    except (IndexError, ValueError):
        update.message.reply_text(
            "❌ *Formato errato*\n\n"
            "✅ *Uso corretto:*\n"
            "`/unsubscribe btc`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in unsubscribe: {e}")
        update.message.reply_text("❌ Errore interno. Riprova tra poco.")

def lst(update: Update, ctx: CallbackContext):
    """Lista sottoscrizioni con formato elegante"""
    try:
        chat_id = update.effective_chat.id
        subs = list_subscriptions(chat_id)
        
        if not subs:
            update.message.reply_text(
                "📭 *Nessun alert attivo*\n\n"
                "💡 Usa `/subscribe btc 50000` per iniziare!",
                parse_mode='Markdown'
            )
        else:
            lines = []
            for asset, threshold in subs:
                formatted_price = format_price(threshold)
                asset_upper = asset.replace('-', ' ').upper()
                lines.append(f"📊 {asset_upper}: {formatted_price}")
                
            message = (
                f"🔔 *I tuoi {len(subs)} alert attivi:*\n\n" +
                "\n".join(lines) +
                f"\n\n💡 Controlla ogni {INTERVAL//60} minuti"
            )
            
            update.message.reply_text(message, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in list: {e}")
        update.message.reply_text("❌ Errore nel recuperare la lista.")

def help_cmd(update: Update, ctx: CallbackContext):
    """Help completo con esempi"""
    help_text = (
        "🤖 *Crypto Alert Bot - Guida Completa*\n\n"
        
        "📋 *Comandi:*\n"
        "• `/subscribe <asset> <soglia>` - Crea alert\n"
        "• `/unsubscribe <asset>` - Rimuovi alert\n"
        "• `/list` - Mostra tutti i tuoi alert\n"
        "• `/help` - Questa guida\n\n"
        
        "💡 *Esempi:*\n"
        "• `/subscribe btc 50000` - Alert BTC >= $50,000\n"
        "• `/subscribe eth 3000` - Alert ETH >= $3,000\n"
        "• `/unsubscribe btc` - Rimuovi alert BTC\n\n"
        
        "📊 *Asset supportati:*\n"
        "BTC, ETH, ADA, SOL, DOT, MATIC, LINK, AVAX, ATOM, XTZ\n\n"
        
        "⚙️ *Limiti:*\n"
        "• Max 10 alert per utente\n"
        "• Controllo ogni 5 minuti\n"
        "• Soglia max: $1,000,000\n\n"
        
        "🛠️ *Sviluppato da MetalCoder*"
    )
    
    try:
        update.message.reply_text(help_text, parse_mode='Markdown')
    except TelegramError as e:
        logger.error(f"Error in help command: {e}")

def stats(update: Update, ctx: CallbackContext):
    """Statistiche per admin"""
    try:
        if ADMIN_CHAT_ID and str(update.effective_chat.id) != ADMIN_CHAT_ID:
            return
            
        from db import get_total_users, get_total_subscriptions
        
        users = get_total_users()
        subs = get_total_subscriptions()
        
        stats_msg = (
            f"📊 *Bot Statistics*\n\n"
            f"👥 Utenti totali: {users}\n"
            f"🔔 Alert attivi: {subs}\n"
            f"⏱️ Intervallo check: {INTERVAL}s"
        )
        
        update.message.reply_text(stats_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in stats: {e}")

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
        
        logger.info("🚀 Starting Crypto Alert Bot...")
        
        # Database initialization
        init_db()
        logger.info("✅ Database initialized")
        
        # Bot setup
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        
        # Register handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("subscribe", subscribe))
        dp.add_handler(CommandHandler("unsubscribe", unsubscribe))
        dp.add_handler(CommandHandler("list", lst))
        dp.add_handler(CommandHandler("help", help_cmd))
        
        if ADMIN_CHAT_ID:
            dp.add_handler(CommandHandler("stats", stats))
            
        # Error handler
        dp.add_error_handler(error_handler)
        
        # Job queue
        jq = updater.job_queue
        jq.run_repeating(
            check_prices, 
            interval=INTERVAL, 
            first=30,  # Prima check dopo 30s
            name="price_checker"
        )
        logger.info(f"✅ Price checker scheduled every {INTERVAL}s")
        
        # Set bot commands
        commands = [
            BotCommand("subscribe", "Crea un nuovo alert"),
            BotCommand("unsubscribe", "Rimuovi un alert"),
            BotCommand("list", "Mostra tutti i tuoi alert"),
            BotCommand("help", "Guida completa")
        ]
        updater.bot.set_my_commands(commands)
        
        # Start bot
        logger.info("✅ Bot started successfully")
        updater.start_polling(clean=True)
        
        # Notify admin if configured
        if ADMIN_CHAT_ID:
            try:
                updater.bot.send_message(
                    ADMIN_CHAT_ID, 
                    "🟢 *Bot avviato con successo!*",
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