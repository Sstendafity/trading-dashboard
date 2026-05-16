# ==========================================
# FILE: alert_check_eth.py
# ==========================================

"""
alert_check_eth.py
Runs via cron every 15 minutes.

ETH ONLY VERSION
"""

import json
import os
import datetime
import requests

# ccxt for price fetching
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# ==========================================
# CONFIGURATION
# ==========================================

SYMBOL = "ETH"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_CHAT_IDS = [
    os.environ["TELEGRAM_CHAT_ID"],
    os.environ.get("TELEGRAM_CHAT_ID_2", ""),
]

TELEGRAM_CHAT_IDS = [cid for cid in TELEGRAM_CHAT_IDS if cid]

ORDERS_DB = "running_orders.json"
ALERT_STATE_DB = "alert_state_eth.json"

DEFAULT_THRESHOLD_PCT = 3.0
USD_TO_INR = 85.0

LOT_SIZE = 0.01  # ETH lot size

REPORT_INTERVAL_MINUTES = 13


def get_symbol(order):
    symbol = str(order.get("symbol", "")).upper()

    if "ETH" in symbol:
        return "ETH"

    if "BTC" in symbol:
        return "BTC"

    account = str(order.get("account", "")).upper()

    if "ETH" in account:
        return "ETH"

    return "BTC"


def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)


# ==========================================
# PRICE FETCHING
# ==========================================

def fetch_with_ccxt():
    if not CCXT_AVAILABLE:
        return None

    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']

    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': False,
            })

            ticker = exchange.fetch_ticker(f'{SYMBOL}/USDT')

            price = float(ticker['last'])

            print(f"Price fetched via CCXT ({exchange_id}): ${price:,.2f}")

            return price

        except Exception as e:
            print(f"CCXT {exchange_id} failed: {e}")

    return None


def fetch_with_coingecko():
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&ids=ethereum",
        timeout=10
    )

    price = float(r.json()[0]["current_price"])

    print(f"Price fetched via CoinGecko: ${price:,.2f}")

    return price


def fetch_with_bybit():
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers"
        f"?category=linear&symbol={SYMBOL}USDT",
        timeout=10
    )

    price = float(r.json()["result"]["list"][0]["lastPrice"])

    print(f"Price fetched via Bybit: ${price:,.2f}")

    return price


def fetch_price():

    try:
        price = fetch_with_ccxt()
        if price:
            return price
    except Exception as e:
        print(f"CCXT failed: {e}")

    try:
        return fetch_with_coingecko()
    except Exception as e:
        print(f"CoinGecko failed: {e}")

    try:
        return fetch_with_bybit()
    except Exception as e:
        print(f"Bybit failed: {e}")

    raise Exception("All price sources failed")


# ==========================================
# STORAGE
# ==========================================

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)

    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def send_telegram(message, chat_ids=None):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    success = True

    for chat_id in (chat_ids if chat_ids is not None else TELEGRAM_CHAT_IDS):

        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            r = requests.post(url, json=payload, timeout=10)

            if not r.ok:
                print(f"Failed to send to chat {chat_id}: {r.text}")
                success = False

        except Exception as e:
            print(f"Error sending to chat {chat_id}: {e}")
            success = False

    return success


# ==========================================
# CALCULATIONS
# ==========================================

def calc_running_pnl(order, current_price):

    side = order.get("side", "Buy")
    entry = order.get("entry_price", 0) or 0
    qty = order.get("qty", 0) or 0

    if side == "Buy":
        running_usd = (current_price - entry) * qty
    else:
        running_usd = (entry - current_price) * qty

    return running_usd, running_usd * USD_TO_INR


# ==========================================
# MESSAGE BUILDERS
# ==========================================

def build_report_msg(orders, current_price):

    total_usd = 0
    total_profit = 0
    total_loss = 0
    total_inr = 0

    profit_count = 0
    loss_count = 0

    buy_qty = 0
    sell_qty = 0

    lines = []

    order_pnls = []

    ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]

    active_accounts = {o.get("account") for o in orders}

    inactive_accounts = [
        a for a in ALL_ACCOUNTS
        if a not in active_accounts
    ]

    for o in orders:

        running_usd, running_inr = calc_running_pnl(
            o,
            current_price
        )

        total_usd += running_usd
        total_inr += running_inr

        if running_inr > 0:
            profit_count += 1
            total_profit += running_inr

        elif running_inr < 0:
            loss_count += 1
            total_loss += running_inr

        order_pnls.append((o, running_usd, running_inr))

        if o.get("side") == "Buy":
            buy_qty += o.get("qty", 0) or 0
        else:
            sell_qty += o.get("qty", 0) or 0

    order_pnls.sort(key=lambda x: x[2], reverse=True)

    for o, running_usd, running_inr in order_pnls:

        side_emoji = "🟢" if o.get("side") == "Buy" else "🔴"

        pnl_sign = "+" if running_inr >= 0 else ""

        lines.append(
            f"  {side_emoji} <b>{o.get('account')}</b> "
            f"@ ${o.get('entry_price', 0):,.1f} | "
            f"{btc_to_lots(o.get('qty', 0))} lots "
            f"→ <code>{pnl_sign}₹{running_inr:,.0f}</code>"
        )

    total_sign = "+" if total_inr >= 0 else ""

    msg = (
        f"ETH Report\n"
        f"<b>CP</b>: <code>${current_price:,.1f}</code>\n"
        f"P: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
        f"L: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
        f"<b>T</b>: <code>{total_sign}₹{total_inr:,.0f}</code>\n"
        f"BQ: {btc_to_lots(buy_qty)} lots\n"
        f"SQ: {btc_to_lots(sell_qty)} lots\n"
        f"\n"
    )

    msg += "\n".join(lines)

    msg += (
        f"\n\n"
        f"Total Orders: {len(orders)}\n"
        f"Idle Accounts ({len(inactive_accounts)}): "
        f"{', '.join(inactive_accounts) if inactive_accounts else 'None'}"
    )

    return msg


# ==========================================
# MAIN
# ==========================================

def main():

    print("=" * 40)
    print("ETH Position Alert Check")
    print("=" * 40)

    current_price = fetch_price()

    orders = load_json(ORDERS_DB, [])

    orders = [
        o for o in orders
        if get_symbol(o) == SYMBOL
    ]

    if not orders:
        print("No ETH positions found.")
        return

    alert_state = load_json(ALERT_STATE_DB, {})

    now = datetime.datetime.utcnow()

    last_report_str = alert_state.get("last_report_time")

    send_report = False

    if last_report_str:

        last_report = datetime.datetime.fromisoformat(
            last_report_str
        )

        minutes_since = (
            now - last_report
        ).total_seconds() / 60

        if minutes_since >= REPORT_INTERVAL_MINUTES:
            send_report = True

    else:
        send_report = True

    if send_report:

        msg = build_report_msg(
            orders,
            current_price
        )

        if send_telegram(msg):

            print("ETH report sent")

            alert_state["last_report_time"] = now.isoformat()

            save_json(ALERT_STATE_DB, alert_state)


if __name__ == "__main__":
    main()