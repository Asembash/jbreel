# jbreel_crypto_bot/main.py

import time
import hmac
import hashlib
import requests
import json
import telegram
import os
import pickle

API_KEY = os.getenv("COINEX_API_KEY")
API_SECRET = os.getenv("COINEX_API_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = telegram.Bot(token=TG_TOKEN)

BASE_URL = 'https://api.coinex.com'
LEARNING_FILE = "market_learning.pkl"
TRADE_LOG_FILE = "trade_log.json"

# === Create API Signature ===
def create_signature(method, path, timestamp):
    message = f"{method}{path}{timestamp}"
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

# === Authenticated Request ===
def make_request(method, path, payload=None):
    timestamp = int(time.time() * 1000)
    signature = create_signature(method, path, timestamp)
    headers = {
        'X-COINEX-KEY': API_KEY,
        'X-COINEX-SIGNATURE': signature,
        'X-COINEX-TIMESTAMP': str(timestamp),
        'Content-Type': 'application/json'
    }
    url = BASE_URL + path
    if method == 'GET':
        return requests.get(url, headers=headers).json()
    elif method == 'POST':
        return requests.post(url, headers=headers, data=json.dumps(payload)).json()

# === Get Balance for Futures ===
def get_futures_balance():
    res = make_request('GET', '/v2/perpetual/account')
    for item in res['data']['assets']:
        if item['margin_coin'] == 'USDT':
            return float(item['available'])
    return 0

# === Load Learning Memory ===
def load_memory():
    try:
        with open(LEARNING_FILE, 'rb') as f:
            return pickle.load(f)
    except:
        return {}

# === Save Learning Memory ===
def save_memory(mem):
    with open(LEARNING_FILE, 'wb') as f:
        pickle.dump(mem, f)

# === Save Trade Log ===
def save_trade_log(entry):
    try:
        with open(TRADE_LOG_FILE, 'r') as f:
            logs = json.load(f)
    except:
        logs = []
    logs.append(entry)
    with open(TRADE_LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=2)

# === Analyze Market Dynamically with Learning ===
def analyze_market():
    symbols = ['BTCUSDT', 'XAUUSDT']
    mem = load_memory()
    best = {"symbol": None, "confidence": 0}
    for symbol in symbols:
        try:
            res = requests.get(f"https://api.coinex.com/v1/market/kline?market={symbol}&type=900&limit=10").json()
            klines = res['data']
            close_prices = [float(k[4]) for k in klines]
            avg = sum(close_prices) / len(close_prices)
            last = close_prices[-1]
            change = (last - avg) / avg
            confidence = round(0.5 + change * 50, 2)

            prev_conf = mem.get(symbol, 0.5)
            new_conf = (prev_conf + confidence) / 2
            mem[symbol] = new_conf

            if new_conf > best['confidence']:
                best = {"symbol": symbol, "side": "buy" if change > 0 else "sell", "confidence": new_conf, "entry": last}
        except Exception as e:
            bot.send_message(chat_id=TG_CHAT_ID, text=f"⚠️ خطأ أثناء تحليل {symbol}: {e}")
            continue

    save_memory(mem)
    return best

# === Execute Futures Trade ===
def execute_trade(signal):
    symbol = signal['symbol']
    side = signal['side']
    direction = 3 if side == 'buy' else 4

    usdt_balance = get_futures_balance()
    margin_amount = round(usdt_balance * 0.05, 2)
    if margin_amount < 1:
        bot.send_message(chat_id=TG_CHAT_ID, text="🚫 الرصيد غير كافٍ للتداول بالعقود.")
        return

    ob = requests.get(f"https://api.coinex.com/v2/market/depth?market={symbol}&limit=1").json()
    price = float(ob['data']['asks'][0][0]) if side == 'buy' else float(ob['data']['bids'][0][0])
    price *= 1.001 if side == 'buy' else 0.999

    order = {
        "market": symbol,
        "price": round(price, 2),
        "amount": 0.01,
        "side": direction,
        "leverage": 3,
        "position_id": 0,
        "open_type": 1,
        "external_oid": f"jb-{int(time.time())}"
    }

    make_request('POST', '/v2/perpetual/order/create', order)

    msg = (
        f"[JB-Futures] ✅ صفقة {'شراء 🟢' if side == 'buy' else 'بيع 🔴'}\n"
        f"الرمز: {symbol}\n"
        f"السعر: {round(price, 2)} USDT\n"
        f"الرافعة: 3x\n"
        f"الثقة: {signal['confidence']}"
    )
    bot.send_message(chat_id=TG_CHAT_ID, text=msg)
    save_trade_log({"symbol": symbol, "side": side, "price": round(price, 2), "confidence": signal['confidence'], "timestamp": int(time.time())})

# === Main Loop ===
if __name__ == '__main__':
    while True:
        try:
            signal = analyze_market()
            if signal['confidence'] >= 0.9:
                execute_trade(signal)
            else:
                bot.send_message(chat_id=TG_CHAT_ID, text=f"[JB-Futures] لا توجد صفقة مناسبة، أفضل فرصة: {signal['symbol']} بثقة {signal['confidence']}")
            time.sleep(60)
        except Exception as e:
            bot.send_message(chat_id=TG_CHAT_ID, text=f"⚠️ خطأ: {str(e)}")
            time.sleep(60)

# === End of JB Futures Bot ===
