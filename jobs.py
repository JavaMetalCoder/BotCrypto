import os
import requests
from db import get_all_unique_assets, get_subscribers_for
from telegram import Bot

API_URL = "https://api.coingecko.com/api/v3/simple/price"
TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TOKEN)

def check_prices(context):
    assets = get_all_unique_assets()
    if not assets: 
        return
    params = {"ids": ",".join(assets), "vs_currencies": "usd"}
    data = requests.get(API_URL, params=params).json()
    for asset in assets:
        price = data.get(asset, {}).get("usd")
        if price is None:
            continue
        for chat_id, threshold in get_subscribers_for(asset):
            if price >= threshold:
                bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ {asset.upper()} è a ${price:.2f} (>= {threshold})"
                )
