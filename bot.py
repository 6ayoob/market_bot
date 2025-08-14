import time
import threading
import requests
from flask import Flask
from trading_strategy import SYMBOLS, check_signal, execute_buy, manage_position

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TIMEFRAME

app = Flask(__name__)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload)
    except:
        pass

def bot_loop():
    while True:
        for symbol in SYMBOLS:
            if manage_position(symbol):
                send_telegram(f"✅ تم تحديث الصفقة لـ {symbol}")
            signal = check_signal(symbol)
            if signal=="buy":
                order, msg = execute_buy(symbol)
                if order:
                    send_telegram(msg)
        time.sleep(300)

@app.route("/")
def home():
    return "🤖 Bot is running!"

if __name__=="__main__":
    # تشغيل البوت في Thread
    t = threading.Thread(target=bot_loop)
    t.start()
    # تشغيل Flask
    app.run(host="0.0.0.0", port=10000)
