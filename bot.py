import os
import logging
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Updater, CommandHandler, CallbackContext

from db import init_db, add_subscription, remove_subscription, list_subscriptions
from jobs import check_prices

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

# Logging
logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)

def start(update: Update, ctx: CallbackContext):
    update.message.reply_text(
        "Bot crypto-alert pronto. Usa /subscribe <asset> <soglia>, /unsubscribe <asset>, /list."
    )

def subscribe(update: Update, ctx: CallbackContext):
    try:
        chat_id = update.effective_chat.id
        asset = ctx.args[0].lower()
        threshold = float(ctx.args[1])
        add_subscription(chat_id, asset, threshold)
        update.message.reply_text(f"✅ Sottoscritto {asset} con soglia {threshold}")
    except (IndexError, ValueError):
        update.message.reply_text("Uso corretto: /subscribe <asset> <soglia>")

def unsubscribe(update: Update, ctx: CallbackContext):
    try:
        chat_id = update.effective_chat.id
        asset = ctx.args[0].lower()
        removed = remove_subscription(chat_id, asset)
        msg = "🚫 Sottoscrizione rimossa" if removed else "‽ Non avevi sottoscritto quel asset"
        update.message.reply_text(msg)
    except IndexError:
        update.message.reply_text("Uso corretto: /unsubscribe <asset>")

def lst(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    subs = list_subscriptions(chat_id)
    if not subs:
        update.message.reply_text("Nessuna sottoscrizione attiva.")
    else:
        lines = [f"{a.upper()}: {t}" for a,t in subs]
        update.message.reply_text("🗒️ Le tue soglie:\n" + "\n".join(lines))

def help_cmd(update: Update, ctx: CallbackContext):
    update.message.reply_text(
        "/subscribe <asset> <soglia>\n"
        "/unsubscribe <asset>\n"
        "/list\n"
        "/help"
    )

def main():
    init_db()
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    # register commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))
    dp.add_handler(CommandHandler("list", lst))
    dp.add_handler(CommandHandler("help", help_cmd))

    # JobQueue: ripeti check_prices
    jq = updater.job_queue
    jq.run_repeating(check_prices, interval=INTERVAL, first=10)

    # Bot commands per UI
    updater.bot.set_my_commands([
        BotCommand("subscribe", "Sottoscrivi alert"),
        BotCommand("unsubscribe", "Rimuovi sottoscrizione"),
        BotCommand("list", "Mostra sottoscrizioni"),
        BotCommand("help", "Aiuto")
    ])

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
