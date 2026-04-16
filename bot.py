"""
bot.py
Standalone Telegram bot — runs 24/7 on Render free tier.
Responds to /report command instantly, independent of Streamlit and GitHub Actions.

Deploy on Render as a Background Worker:
  Build command: pip install requests ccxt
  Start command: python bot.py
  Environment vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_CHAT_ID_2, GITHUB_TOKEN
"""

import os
import time
import json
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
POLL_INTERVAL = 3  # seconds between getUpdates calls
ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]

def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)

# ==========================================
# PRICE FETCHING — same as alert_check.py
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
# STORAGE — fetch from GitHub
# (Render has ephemeral filesystem)
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

# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message, chat_id):
    """Send message to a specific chat."""
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
    """Poll Telegram for new messages."""
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
# Matches exact structure from monitor.py
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

    # Sort highest profit to lowest loss
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
# MAIN POLLING LOOP
# ==========================================

def main():
    print("=" * 40)
    print("🤖 BTC Bot started")
    print(f"Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Polling every {POLL_INTERVAL}s for /report commands...")
    print("=" * 40)

    last_update_id = None

    while True:
        try:
            offset = (last_update_id + 1) if last_update_id is not None else None
            updates = get_updates(offset=offset)

            for update in updates:
                update_id = update.get("update_id", 0)
                last_update_id = max(last_update_id or 0, update_id)

                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                chat_id = str(message.get("chat", {}).get("id", ""))

                if not chat_id:
                    continue

                if text.startswith("/report"):
                    print(f"📲 /report from chat {chat_id}")
                    orders = load_orders()

                    if not orders:
                        send_telegram("⚪ No open positions at the moment.", chat_id)
                        print("↩️  No orders — sent empty notice")
                    else:
                        try:
                            price = fetch_btc_price()
                            msg = build_report(orders, price)
                            if send_telegram(msg, chat_id):
                                print(f"✅ Report sent to {chat_id} — BTC ${price:,.1f}")
                            else:
                                print(f"❌ Failed to send to {chat_id}")
                        except Exception as e:
                            error_msg = f"❌ Error fetching price: {e}"
                            send_telegram(error_msg, chat_id)
                            print(error_msg)

        except Exception as e:
            print(f"Polling error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()