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
import datetime
import requests

from core.price_feed import fetch_price, fetch_ohlcv
from core.telegram import send_message, get_updates as _core_get_updates
from core.pnl_report import build_report_msg

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

# Open price cache — recorded once per UTC day
cached_open_price = None
cached_open_date = None

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

def fetch_btc_price():
    return fetch_price('BTC')

def fetch_btc_ticker():
    """
    Fetch current price and today's true UTC midnight open price.
    Uses OHLCV daily candle (1d timeframe) to get the exact 00:00 UTC open.
    """
    global cached_open_price, cached_open_date

    today = datetime.datetime.now(datetime.timezone.utc).date()
    current_price = fetch_btc_price()

    # Same day and already cached — return as-is
    if cached_open_price is not None and cached_open_date == today:
        return current_price, cached_open_price

    # New day or first run — fetch today's daily candle open
    ohlcv = fetch_ohlcv('BTC', timeframe='1d', limit=2)
    if ohlcv and len(ohlcv) >= 1:
        cached_open_price = float(ohlcv[-1][1])
        cached_open_date = today
        print(f"Daily open cached: ${cached_open_price:,.2f} ({today})")
        return current_price, cached_open_price

    # No candle available — fall back to current price
    cached_open_price = current_price
    cached_open_date = today
    print(f"Open price fallback: ${cached_open_price:,.2f} ({today})")
    return current_price, cached_open_price

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
    return send_message(TELEGRAM_TOKEN, chat_id, message)

def get_updates(offset=None):
    return _core_get_updates(TELEGRAM_TOKEN, offset=offset)

# ==========================================
# REPORT BUILDER
# ==========================================

def build_report(orders, current_price):
    return build_report_msg(orders, current_price, ALL_ACCOUNTS, LOT_SIZE)

# ==========================================
# PRICE INTERVAL ALERT LOGIC
# ==========================================

def get_current_level(price, base_price, interval):
    steps = round((price - base_price) / interval)
    return base_price + steps * interval

def check_price_alerts(current_price, open_price):
    """
    Check all active price interval alerts.
    Alert message shows today's open price and diff from open — UI only.
    The alert trigger logic is unchanged.
    """
    for chat_id, config in list(price_alert_configs.items()):
        if not config.get("active"):
            continue

        interval = config["interval"]
        base_price = config["base_price"]
        last_level = config["last_level"]

        current_level = get_current_level(current_price, base_price, interval)

        if current_level != last_level:
            levels_crossed = abs(int((current_level - last_level) / interval))
            rounded_price = round(current_price / 100) * 100

            if open_price:
                diff = current_price - open_price
                diff_sign = "+" if diff >= 0 else ""
                open_line = (
                    f"Open: <code>${open_price:,.1f}</code> | "
                    f"Diff: <code>{diff_sign}${diff:,.1f}</code>"
                )
            else:
                open_line = None

            msg = f"<b>BTC ${rounded_price:,.0f}</b>\n"
            if open_line:
                msg += f"{open_line}\n"
            msg += f"Interval: <code>${interval:,.0f}</code>"
            if levels_crossed > 1:
                msg += f"\nSkipped {levels_crossed - 1} level(s)"

            send_telegram(msg, chat_id)
            price_alert_configs[chat_id]["last_level"] = current_level
            save_alert_configs()
            print(f"Price alert sent to {chat_id} — level ${current_level:,.1f}")

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
    print(f"/setuppricealert from {chat_id} — awaiting interval")

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
        save_alert_configs()

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
        print(f"Price alert set for {chat_id} — interval ${interval:,.0f} base ${current_price:,.1f}")

    except ValueError:
        send_telegram(
            f"❌ Invalid interval. Please send a number, e.g. <code>500</code>",
            chat_id
        )
        print(f"Invalid interval input from {chat_id}: '{text}'")

def handle_stop_price_alert(chat_id):
    if chat_id in price_alert_configs and price_alert_configs[chat_id].get("active"):
        config = price_alert_configs[chat_id]
        price_alert_configs[chat_id]["active"] = False
        awaiting_interval.pop(chat_id, None)
        save_alert_configs()

        send_telegram(
            f"🛑 <b>Price Alert Stopped</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Interval <code>${config['interval']:,.0f}</code> alert has been deactivated.\n"
            f"Use /setuppricealert to start a new one.",
            chat_id
        )
        print(f"Price alert stopped for {chat_id}")
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
        print(f"Loaded {len(price_alert_configs)} alert config(s), {len(active)} active")

    print("=" * 40)
    print("BTC Bot started")
    print(f"Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
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
                    print(f"/report from {chat_id}")
                    orders = load_orders()
                    if not orders:
                        send_telegram("⚪ No open positions at the moment.", chat_id)
                    else:
                        try:
                            price = fetch_btc_price()
                            msg = build_report(orders, price)
                            if send_telegram(msg, chat_id):
                                print(f"Report sent to {chat_id} — BTC ${price:,.1f}")
                            else:
                                print(f"Failed to send to {chat_id}")
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
                        current_price, open_price = fetch_btc_ticker()
                        check_price_alerts(current_price, open_price)
                        last_price_check = now
                    except Exception as e:
                        print(f"Price check error: {e}")

        except Exception as e:
            print(f"Polling error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()