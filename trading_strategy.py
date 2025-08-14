import pandas as pd
import json, os
from datetime import datetime
from okx_api import fetch_ohlcv, fetch_price, place_market_order, fetch_balance
from config import TRADE_AMOUNT_USDT, MAX_OPEN_POSITIONS, SYMBOLS, TIMEFRAME

POSITIONS_DIR = "positions"
CLOSED_POSITIONS_FILE = "closed_positions.json"

# ===============================
# 📂 التعامل مع ملفات الصفقات
# ===============================
def ensure_dirs():
    os.makedirs(POSITIONS_DIR, exist_ok=True)

def get_position_filename(symbol):
    ensure_dirs()
    symbol = symbol.replace("/", "_")
    return f"{POSITIONS_DIR}/{symbol}.json"

def load_position(symbol):
    try:
        file = get_position_filename(symbol)
        if os.path.exists(file):
            with open(file, 'r') as f:
                return json.load(f)
    except:
        return None

def save_position(symbol, position):
    ensure_dirs()
    file = get_position_filename(symbol)
    with open(file, 'w') as f:
        json.dump(position, f, indent=2, ensure_ascii=False)

def clear_position(symbol):
    file = get_position_filename(symbol)
    if os.path.exists(file):
        os.remove(file)

def count_open_positions():
    ensure_dirs()
    return len([f for f in os.listdir(POSITIONS_DIR) if f.endswith(".json")])

def load_closed_positions():
    if os.path.exists(CLOSED_POSITIONS_FILE):
        with open(CLOSED_POSITIONS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_closed_positions(closed_positions):
    with open(CLOSED_POSITIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(closed_positions, f, indent=2, ensure_ascii=False)

# ===============================
# 📊 المؤشرات الفنية
# ===============================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_indicators(df):
    df['ema9'] = ema(df['close'], 9)
    df['ema21'] = ema(df['close'], 21)
    df['rsi'] = rsi(df['close'], 14)
    df['ema50'] = ema(df['close'], 50)
    return df

# ===============================
# 🔎 دعم ومقاومة
# ===============================
def get_support_resistance(df, window=50):
    df_prev = df.iloc[:-1].copy()
    use_window = min(window, len(df_prev))
    resistance = df_prev['high'].rolling(use_window).max().iloc[-1]
    support = df_prev['low'].rolling(use_window).min().iloc[-1]
    return support, resistance

# ===============================
# 🎯 إشارات شراء
# ===============================
def check_signal(symbol):
    try:
        data = fetch_ohlcv(symbol, TIMEFRAME, 150)
        if not data:
            return None
        df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
        df = calculate_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        # فلتر الاتجاه والRSI
        if last['close'] < last['ema50']:
            return None
        if not (50 < last['rsi'] < 70):
            return None

        # الدعم والمقاومة
        support, resistance = get_support_resistance(df)
        last_price = float(last['close'])
        if last_price >= resistance or last_price <= support:
            return None

        # EMA9 يتقاطع صعوديًا مع EMA21
        if prev['ema9'] < prev['ema21'] and last['ema9'] > last['ema21']:
            return "buy"
    except:
        return None
    return None

# ===============================
# 🛒 تنفيذ الشراء
# ===============================
def execute_buy(symbol):
    if count_open_positions() >= MAX_OPEN_POSITIONS:
        return None, f"🚫 الحد الأقصى للصفقات المفتوحة"

    price = fetch_price(symbol)
    usdt_balance = fetch_balance('USDT')
    if usdt_balance < TRADE_AMOUNT_USDT:
        return None, f"🚫 رصيد USDT غير كافٍ"

    amount = TRADE_AMOUNT_USDT / price
    order = place_market_order(symbol, 'buy', amount)

    # وقف خسارة ديناميكي: أدنى سعر آخر 10 شموع
    data = fetch_ohlcv(symbol, TIMEFRAME, 20)
    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
    swing_low = df['low'].rolling(10).min().iloc[-2]
    stop_loss = float(swing_low)
    risk = price - stop_loss
    take_profit = price + risk*2

    position = {
        "symbol": symbol,
        "amount": amount,
        "entry_price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    }
    save_position(symbol, position)
    return order, f"✅ تم شراء {symbol} بسعر {price:.8f}\n🎯 TP: {take_profit:.8f} | 🛑 SL: {stop_loss:.8f}"

# ===============================
# 📈 إدارة الصفقة
# ===============================
def manage_position(symbol):
    position = load_position(symbol)
    if not position:
        return False
    current_price = fetch_price(symbol)
    amount = position['amount']
    entry_price = position['entry_price']
    base_asset = symbol.split('/')[0]
    actual_balance = fetch_balance(base_asset)
    sell_amount = round(min(amount, actual_balance),6)

    def close_trade(exit_price):
        profit = (exit_price - entry_price)*sell_amount
        closed_positions = load_closed_positions()
        closed_positions.append({
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "amount": sell_amount,
            "profit": profit,
            "closed_at": datetime.utcnow().isoformat()
        })
        save_closed_positions(closed_positions)
        clear_position(symbol)
        return True

    if current_price >= position['take_profit'] or current_price <= position['stop_loss']:
        order = place_market_order(symbol, 'sell', sell_amount)
        if order:
            return close_trade(current_price)
    return False
