"""
bot.py
Standalone Telegram bot — runs 24/7 on Railway.
Commands:
  /report           — instant portfolio report
  /setuppricealert  — set up price interval alerts
  /stoppricealert   — stop price interval alerts
"""

import os
import time
import json
import math
import datetime
import requests

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# ==========================================
# CONFIGURATION
# ==========================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [
    os.environ["TELEGRAM_CHAT_ID"],
    os.environ.get("TELEGRAM_CHAT_ID_2", ""),
]
TELEGRAM_CHAT_IDS = [c for c in TELEGRAM_CHAT_IDS if c]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "Sstendafity/trading-dashboard"

USD_TO_INR = 85.0
LOT_SIZE = 0.001
POLL_INTERVAL = 3
PRICE_CHECK_INTERVAL = 10

ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 16)]

def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)

# ==========================================
# PRICE INTERVAL ALERT STATE
# ==========================================

price_alert_configs = {}
awaiting_interval = {}

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
            ticker = exchange.fetch_ticker('BTC/USDT')
            price = float(ticker['last'])
            print(f"Price fetched via CCXT ({exchange_id}): ${price:,.2f}")
            return price
        except Exception as e:
            print(f"CCXT {exchange_id} failed: {e}")
            continue
    return None

def fetch_with_coingecko():
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&ids=bitcoin",
        timeout=10
    )
    price = float(r.json()[0]["current_price"])
    print(f"Price fetched via CoinGecko: ${price:,.2f}")
    return price

def fetch_with_bybit():
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers"
        "?category=linear&symbol=BTCUSDT",
        timeout=10
    )
    price = float(r.json()["result"]["list"][0]["lastPrice"])
    print(f"Price fetched via Bybit: ${price:,.2f}")
    return price

def fetch_btc_price():
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

def load_orders():
    """Fetch running_orders.json directly from GitHub repo."""
    if GITHUB_TOKEN:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{REPO}/contents/running_orders.json",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3.raw"
                },
                timeout=10
            )
            if r.ok:
                return r.json()
        except Exception as e:
            print(f"GitHub fetch failed: {e}")
    return []

ALERT_CONFIG_FILE = "price_alert_configs.json"

def save_alert_configs():
    """Persist alert configs to disk so they survive restarts."""
    try:
        with open(ALERT_CONFIG_FILE, "w") as f:
            json.dump(price_alert_configs, f, indent=2)
    except Exception as e:
        print(f"Failed to save alert configs: {e}")

def load_alert_configs():
    """Load alert configs from disk on startup."""
    if os.path.exists(ALERT_CONFIG_FILE):
        try:
            with open(ALERT_CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message, chat_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.ok
    except Exception as e:
        print(f"Send failed: {e}")
        return False

def get_updates(offset=None):
    params = {"timeout": 0, "limit": 10}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params=params,
            timeout=10
        )
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        print(f"getUpdates failed: {e}")
    return []

# ==========================================
# REPORT BUILDER
# ==========================================

def build_report(orders, current_price):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    total_usd = 0
    total_profit = 0
    total_loss = 0
    total_inr = 0
    profit_count = 0
    loss_count = 0
    buy_qty = 0
    sell_qty = 0
    order_pnls = []

    active_accounts = {o.get("account") for o in orders}
    inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]

    for o in orders:
        side = o.get("side", "Buy")
        entry = o.get("entry_price", 0) or 0
        qty = o.get("qty", 0) or 0
        running_usd = (current_price - entry) * qty if side == "Buy" else (entry - current_price) * qty
        running_inr = running_usd * USD_TO_INR
        total_usd += running_usd
        total_inr += running_inr
        if running_inr > 0:
            profit_count += 1
            total_profit += running_inr
        elif running_inr < 0:
            loss_count += 1
            total_loss += running_inr
        order_pnls.append((o, running_usd, running_inr))
        if side == "Buy":
            buy_qty += qty
        else:
            sell_qty += qty

    order_pnls.sort(key=lambda x: x[2], reverse=True)

    lines = []
    for o, running_usd, running_inr in order_pnls:
        side_emoji = "🟢" if o.get("side") == "Buy" else "🔴"
        pnl_sign = "+" if running_inr >= 0 else ""
        lines.append(
            f"  {side_emoji} <b>{o.get('account')}</b> "
            f"@ ${o.get('entry_price', 0):,.1f} | {btc_to_lots(o.get('qty', 0))} lots "
            f"→ <code>{pnl_sign}₹{running_inr:,.0f}</code>"
        )

    total_sign = "+" if total_inr >= 0 else ""
    total_emoji = "📈" if total_inr >= 0 else "📉"

    msg = (
        f"📊 <b>INSTANT PORTFOLIO REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"₿ BTC Price: <code>${current_price:,.1f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    msg += "\n".join(lines)
    msg += (
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"{total_emoji} <b>Net Running P&L</b>: "
        f"<code>{total_sign}₹{total_inr:,.0f}</code> "
        f"(<code>{total_sign}${total_usd:,.2f}</code>)\n"
        f"✅ Profit: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
        f"❌ Loss: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
        f"📋 Total Orders: {len(orders)}\n"
        f"📦 Buy Qty: {btc_to_lots(buy_qty)} lots\n"
        f"📦 Sell Qty: {btc_to_lots(sell_qty)} lots\n"
        f"⚪ Idle Accounts ({len(inactive_accounts)}): {', '.join(inactive_accounts) if inactive_accounts else 'None'}"
    )
    return msg

# ==========================================
# PRICE INTERVAL ALERT LOGIC
# ==========================================

def get_current_level(price, base_price, interval):
    steps = round((price - base_price) / interval)
    return base_price + steps * interval

def check_price_alerts(current_price):
    for chat_id, config in list(price_alert_configs.items()):
        if not config.get("active"):
            continue

        interval = config["interval"]
        base_price = config["base_price"]
        last_level = config["last_level"]

        current_level = get_current_level(current_price, base_price, interval)

        if current_level != last_level:
            direction = "📈" if current_level > last_level else "📉"
            levels_crossed = abs(int((current_level - last_level) / interval))

            msg = (
                f"{direction} <b>BTC ${round(current_price, -2)}</b>\n"
                f"Level: <code>${current_level:,.0f}</code> | Interval: <code>${interval:,.0f}</code>"
            )
            if levels_crossed > 1:
                msg += f"\n⚡ Skipped {levels_crossed - 1} level(s)"

            send_telegram(msg, chat_id)
            price_alert_configs[chat_id]["last_level"] = current_level
            save_alert_configs()
            print(f"🔔 Price alert sent to {chat_id} — level ${current_level:,.1f}")

# ==========================================
# COMMAND HANDLERS
# ==========================================

def handle_setup_price_alert(chat_id):
    awaiting_interval[chat_id] = True
    send_telegram(
        f"🔔 <b>Price Interval Alert Setup</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Please send the price interval you want to be alerted at.\n\n"
        f"<b>Example:</b> Send <code>500</code> to get alerted every $500 move.\n\n"
        f"If BTC is currently at $75,000:\n"
        f"→ You'll get alerts at $75,500 · $76,000 · $76,500 · etc.\n"
        f"→ And at $74,500 · $74,000 · $73,500 · etc.",
        chat_id
    )
    print(f"📲 /setuppricealert from {chat_id} — awaiting interval")

def handle_interval_input(chat_id, text, current_price):
    try:
        interval = float(text.replace(",", "").strip())
        if interval <= 0:
            raise ValueError("Interval must be positive")

        price_alert_configs[chat_id] = {
            "active": True,
            "interval": interval,
            "base_price": current_price,
            "last_level": get_current_level(current_price, current_price, interval),
        }
        awaiting_interval.pop(chat_id, None)
        save_alert_configs()  # persist immediately

        send_telegram(
            f"✅ <b>Price Alert Activated!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📏 Interval: <code>${interval:,.0f}</code>\n"
            f"📍 Base Price: <code>${current_price:,.1f}</code>\n"
            f"🎯 First alerts at:\n"
            f"   ↑ <code>${current_price + interval:,.1f}</code>\n"
            f"   ↓ <code>${current_price - interval:,.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Use /stoppricealert to stop.",
            chat_id
        )
        print(f"✅ Price alert set for {chat_id} — interval ${interval:,.0f} base ${current_price:,.1f}")

    except ValueError:
        send_telegram(
            f"❌ Invalid interval. Please send a number, e.g. <code>500</code>",
            chat_id
        )
        print(f"❌ Invalid interval input from {chat_id}: '{text}'")

def handle_stop_price_alert(chat_id):
    if chat_id in price_alert_configs and price_alert_configs[chat_id].get("active"):
        config = price_alert_configs[chat_id]
        price_alert_configs[chat_id]["active"] = False
        awaiting_interval.pop(chat_id, None)
        save_alert_configs()  # persist immediately

        send_telegram(
            f"🛑 <b>Price Alert Stopped</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Interval <code>${config['interval']:,.0f}</code> alert has been deactivated.\n"
            f"Use /setuppricealert to start a new one.",
            chat_id
        )
        print(f"🛑 Price alert stopped for {chat_id}")
    else:
        send_telegram(
            "⚪ No active price interval alert to stop.",
            chat_id
        )

# ==========================================
# MAIN POLLING LOOP
# ==========================================

def main():
    global price_alert_configs
    price_alert_configs = load_alert_configs()
    if price_alert_configs:
        active = [c for c, v in price_alert_configs.items() if v.get("active")]
        print(f"📂 Loaded {len(price_alert_configs)} alert config(s), {len(active)} active")

    print("=" * 40)
    print("🤖 BTC Bot started")
    print(f"Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Polling every {POLL_INTERVAL}s for commands...")
    print("=" * 40)

    last_update_id = None
    last_price_check = 0

    while True:
        try:
            # ==========================================
            # 1. HANDLE TELEGRAM COMMANDS
            # ==========================================
            offset = (last_update_id + 1) if last_update_id is not None else None
            updates = get_updates(offset=offset)

            for update in updates:
                update_id = update.get("update_id", 0)
                last_update_id = max(last_update_id or 0, update_id)

                message = update.get("message", {})
                raw_text = message.get("text", "").strip()
                text = raw_text.lower()
                chat_id = str(message.get("chat", {}).get("id", ""))

                if not chat_id:
                    continue

                # /report
                if text.startswith("/report"):
                    print(f"📲 /report from {chat_id}")
                    orders = load_orders()
                    if not orders:
                        send_telegram("⚪ No open positions at the moment.", chat_id)
                    else:
                        try:
                            price = fetch_btc_price()
                            msg = build_report(orders, price)
                            if send_telegram(msg, chat_id):
                                print(f"✅ Report sent to {chat_id} — BTC ${price:,.1f}")
                            else:
                                print(f"❌ Failed to send to {chat_id}")
                        except Exception as e:
                            send_telegram(f"❌ Error fetching price: {e}", chat_id)

                # /setuppricealert
                elif text.startswith("/setuppricealert"):
                    handle_setup_price_alert(chat_id)

                # /stoppricealert
                elif text.startswith("/stoppricealert"):
                    handle_stop_price_alert(chat_id)

                # Interval number input (awaiting after /setuppricealert)
                elif awaiting_interval.get(chat_id):
                    try:
                        current_price = fetch_btc_price()
                        handle_interval_input(chat_id, raw_text, current_price)
                    except Exception as e:
                        send_telegram(f"❌ Could not fetch current price: {e}", chat_id)

            # ==========================================
            # 2. CHECK PRICE INTERVAL ALERTS
            # ==========================================
            active_alerts = [c for c in price_alert_configs.values() if c.get("active")]
            if active_alerts:
                now = time.time()
                if now - last_price_check >= PRICE_CHECK_INTERVAL:
                    try:
                        current_price = fetch_btc_price()
                        check_price_alerts(current_price)
                        last_price_check = now
                    except Exception as e:
                        print(f"Price check error: {e}")

        except Exception as e:
            print(f"Polling error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()