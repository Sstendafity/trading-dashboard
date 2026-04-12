"""
alert_check.py
Runs via GitHub Actions cron. Checks all open positions against live BTC price,
sends Telegram alert if price moves >= threshold% against the entry direction.
"""

import json
import os
import requests

# ==========================================
# CONFIGURATION
# ==========================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ORDERS_DB = "running_orders.json"
ALERT_STATE_DB = "alert_state.json"
DEFAULT_THRESHOLD_PCT = 3.0

# ==========================================
# HELPERS
# ==========================================

def fetch_btc_price():
    # Try CoinGecko first
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&ids=bitcoin",
            timeout=10
        )
        return float(r.json()[0]["current_price"])
    except Exception:
        pass

    # Fallback: Bybit
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers"
        "?category=linear&symbol=BTCUSDT",
        timeout=10
    )
    return float(r.json()["result"]["list"][0]["lastPrice"])

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload, timeout=10)
    return r.ok

# ==========================================
# ALERT LOGIC
# ==========================================

def check_position(order, current_price):
    """
    Returns (should_alert, move_pct, direction_label) for a position.
    For Buy/Long:  alert if price dropped >= threshold% below entry
    For Sell/Short: alert if price rose >= threshold% above entry
    """
    entry = order.get("entry_price", 0) or 0
    side = order.get("side", "Buy")
    threshold = order.get("alert_threshold", DEFAULT_THRESHOLD_PCT)

    if entry <= 0:
        return False, 0, ""

    if side == "Buy":
        move_pct = ((entry - current_price) / entry) * 100  # positive = price dropped
        direction = "dropped"
    else:
        move_pct = ((current_price - entry) / entry) * 100  # positive = price rose
        direction = "risen"

    should_alert = move_pct >= threshold
    return should_alert, move_pct, direction


def build_alert_message(order, current_price, move_pct, direction):
    entry = order.get("entry_price", 0)
    qty = order.get("qty", 0)
    side = order.get("side", "Buy")
    account = order.get("account", "?")
    threshold = order.get("alert_threshold", DEFAULT_THRESHOLD_PCT)

    # Running P&L
    if side == "Buy":
        running_usd = (current_price - entry) * qty
    else:
        running_usd = (entry - current_price) * qty
    running_inr = running_usd * 85

    pnl_sign = "+" if running_inr >= 0 else ""
    side_emoji = "🟢" if side == "Buy" else "🔴"
    alert_emoji = "⚠️" if move_pct < (threshold * 1.5) else "🚨"

    msg = (
        f"{alert_emoji} <b>PRICE ALERT — {account}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{side_emoji} <b>{side.upper()} / {'LONG' if side == 'Buy' else 'SHORT'}</b>\n"
        f"📍 Entry Price:  <code>${entry:,.1f}</code>\n"
        f"📊 Current Price: <code>${current_price:,.1f}</code>\n"
        f"📉 Move Against: <code>{move_pct:.2f}%</code> (threshold: {threshold}%)\n"
        f"💰 Running P&L:  <code>{pnl_sign}₹{running_inr:,.0f}</code> "
        f"(<code>{pnl_sign}${running_usd:,.2f}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Price has <b>{direction} {move_pct:.2f}%</b> against your {side.lower()} position."
    )

    # Add liq/SL/TG if available
    extras = []
    if order.get("liquidation"):
        extras.append(f"💀 Liq: <code>${order['liquidation']:,.1f}</code>")
    if order.get("stop_loss"):
        extras.append(f"🛑 SL: <code>${order['stop_loss']:,.1f}</code>")
    if order.get("target"):
        extras.append(f"🎯 TG: <code>${order['target']:,.1f}</code>")
    if extras:
        msg += "\n" + " | ".join(extras)

    return msg


# ==========================================
# MAIN
# ==========================================

def main():
    print("Fetching BTC price...")
    try:
        current_price = fetch_btc_price()
        print(f"BTC Price: ${current_price:,.2f}")
    except Exception as e:
        print(f"Failed to fetch price: {e}")
        return

    orders = load_json(ORDERS_DB, [])
    if not orders:
        print("No open positions found.")
        return

    alert_state = load_json(ALERT_STATE_DB, {})
    state_changed = False
    alerts_sent = 0
    alerts_recovered = 0

    for order in orders:
        key = f"{order.get('account')}_{order.get('side')}_{order.get('entry_price')}_{order.get('qty')}"

        should_alert, move_pct, direction = check_position(order, current_price)
        already_alerted = alert_state.get(key, False)

        if should_alert and not already_alerted:
            msg = build_alert_message(order, current_price, move_pct, direction)
            success = send_telegram(msg)
            if success:
                print(f"✅ Alert sent for {order.get('account')} ({order.get('side')}): {move_pct:.2f}% move")
                alert_state[key] = True
                state_changed = True
                alerts_sent += 1
            else:
                print(f"❌ Failed to send alert for {order.get('account')}")

        elif not should_alert and already_alerted:
            alert_state[key] = False
            state_changed = True
            alerts_recovered += 1
            print(f"↩️  {order.get('account')} recovered — alert reset")

        else:
            status = f"⚠️ {move_pct:.2f}% (already alerted)" if already_alerted else f"✅ {move_pct:.2f}% (safe)"
            print(f"   {order.get('account')} {order.get('side')}: {status}")

    if state_changed:
        save_json(ALERT_STATE_DB, alert_state)

    print(f"\nDone. Alerts sent: {alerts_sent} | Recovered: {alerts_recovered}")


if __name__ == "__main__":
    main()
