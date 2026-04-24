"""
alert_check.py
Runs via GitHub Actions cron every 15 minutes.

Sends alerts for:
1. Price moves >= threshold% against entry direction (per position)
2. Price reaches liquidation level (per position, if set)
3. Overall portfolio report every 15 minutes
"""

import json
import os
import time
import datetime
import requests

# ccxt for price fetching — same as monitor.py
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# ==========================================
# CONFIGURATION
# ==========================================

# CONFIGURATION — replace the chat ID line with:
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [
    os.environ["TELEGRAM_CHAT_ID"],
    os.environ.get("TELEGRAM_CHAT_ID_2", ""),  # optional — empty string if not set
]
TELEGRAM_CHAT_IDS = [cid for cid in TELEGRAM_CHAT_IDS if cid]  # filter empty
ORDERS_DB = "running_orders.json"
ALERT_STATE_DB = "alert_state.json"
DEFAULT_THRESHOLD_PCT = 3.0
USD_TO_INR = 85.0
LOT_SIZE = 0.001  # 1 lot = 0.001 BTC

def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)

REPORT_INTERVAL_MINUTES = 13

# ==========================================
# PRICE FETCHING — CCXT + REST fallbacks
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
    # 1. CCXT (OKX / KuCoin / Gate.io / HTX)
    try:
        price = fetch_with_ccxt()
        if price:
            return price
    except Exception as e:
        print(f"CCXT failed: {e}")

    # 2. CoinGecko
    try:
        return fetch_with_coingecko()
    except Exception as e:
        print(f"CoinGecko failed: {e}")

    # 3. Bybit
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
    """Send to all TELEGRAM_CHAT_IDS, or specific chat_ids if provided."""
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

def check_pct_move(order, current_price):
    """Returns (should_alert, move_pct, direction)"""
    entry = order.get("entry_price", 0) or 0
    side = order.get("side", "Buy")
    threshold = order.get("alert_threshold", DEFAULT_THRESHOLD_PCT)
    if entry <= 0:
        return False, 0, ""
    if side == "Buy":
        move_pct = ((entry - current_price) / entry) * 100
        direction = "dropped"
    else:
        move_pct = ((current_price - entry) / entry) * 100
        direction = "risen"
    return move_pct >= threshold, move_pct, direction

def check_liquidation(order, current_price):
    """Returns True if price has reached liquidation level"""
    liq = order.get("liquidation")
    if not liq:
        return False
    side = order.get("side", "Buy")
    if side == "Buy":
        return current_price <= liq
    else:
        return current_price >= liq

# ==========================================
# MESSAGE BUILDERS
# ==========================================

def build_pct_alert_msg(order, current_price, move_pct, direction):
    entry = order.get("entry_price", 0)
    qty = order.get("qty", 0)
    side = order.get("side", "Buy")
    account = order.get("account", "?")
    threshold = order.get("alert_threshold", DEFAULT_THRESHOLD_PCT)
    running_usd, running_inr = calc_running_pnl(order, current_price)
    pnl_sign = "+" if running_inr >= 0 else ""
    side_emoji = "🟢" if side == "Buy" else "🔴"
    alert_emoji = "⚠️" if move_pct < (threshold * 1.5) else "🚨"

    msg = (
        f"{alert_emoji} <b>PRICE ALERT — {account}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{side_emoji} <b>{side.upper()} / {'LONG' if side == 'Buy' else 'SHORT'}</b>\n"
        f"📍 Entry Price:   <code>${entry:,.1f}</code>\n"
        f"⚖️ Quantity:      <code>{btc_to_lots(qty)}</code>\n"
        f"📊 Current Price: <code>${current_price:,.1f}</code>\n"
        f"📉 Move Against:  <code>{move_pct:.2f}%</code> (threshold: {threshold}%)\n"
        f"💰 Running P&L:   <code>{pnl_sign}₹{running_inr:,.0f}</code> "
        f"(<code>{pnl_sign}${running_usd:,.2f}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Price has <b>{direction} {move_pct:.2f}%</b> against your {side.lower()} position."
    )
    extras = []
    if order.get("liquidation"):
        extras.append(f"💀 Liq: <code>${order['liquidation']:,.1f}</code>")
    if order.get("stop_loss"):
        extras.append(f"🛑 SL:  <code>${order['stop_loss']:,.1f}</code>")
    if order.get("target"):
        extras.append(f"🎯 TG:  <code>${order['target']:,.1f}</code>")
    if extras:
        msg += "\n" + " | ".join(extras)
    return msg

def build_liq_alert_msg(order, current_price):
    entry = order.get("entry_price", 0)
    qty = order.get("qty", 0)
    side = order.get("side", "Buy")
    account = order.get("account", "?")
    liq = order.get("liquidation", 0)
    running_usd, running_inr = calc_running_pnl(order, current_price)
    side_emoji = "🟢" if side == "Buy" else "🔴"

    msg = (
        f"💀 <b>LIQUIDATION ALERT — {account}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{side_emoji} <b>{side.upper()} / {'LONG' if side == 'Buy' else 'SHORT'}</b>\n"
        f"📍 Entry Price:   <code>${entry:,.1f}</code>\n"
        f"⚖️ Quantity:      <code>{btc_to_lots(qty)}</code>\n"
        f"📊 Current Price: <code>${current_price:,.1f}</code>\n"
        f"💀 Liq Price:     <code>${liq:,.1f}</code>\n"
        f"💸 Est. Loss:     <code>-₹{abs(running_inr):,.0f}</code> "
        f"(<code>-${abs(running_usd):,.2f}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Price has reached the liquidation level!"
    )
    return msg

def build_report_msg(orders, current_price):
    """Overall portfolio report sent every 15 minutes."""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    total_usd = 0
    total_profit = 0
    total_loss = 0
    total_inr = 0
    profit_count = 0
    loss_count = 0
    buy_qty = 0
    sell_qty = 0
    lines = []

    # Calculate P&L for all orders first
    order_pnls = []
    # Add this after order_pnls is built, before the msg assembly

    ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
    active_accounts = {o.get("account") for o in orders}
    inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]

    for o in orders:
        running_usd, running_inr = calc_running_pnl(o, current_price)
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

    # Sort highest profit to lowest loss
    order_pnls.sort(key=lambda x: x[2], reverse=True)

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
        f"<b>CP</b>: <code>${cp:,.1f}</code>\n"
        f"P: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
        f"L: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
        f"<b>T</b>: <code>{total_sign}₹{total_inr:,.0f}</code>\n"
        f"BQ: {btc_to_lots(buy_qty)} lots\n"
        f"SQ: {btc_to_lots(sell_qty)} lots\n"
        f"\n"
    )
    msg += "\n".join(lines)
    msg += (
        f"\n"
        f"\n"
        f"Total Orders: {len(orders)}\n"
        f"Idle Accounts ({len(inactive_accounts)}): {', '.join(inactive_accounts) if inactive_accounts else 'None'}"
    )
    return msg

# ==========================================
# /report COMMAND HANDLER
# ==========================================

def get_bot_updates(offset=None):
    """Poll Telegram for new messages sent to the bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 0, "limit": 10}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        print(f"getUpdates failed: {e}")
    return []

def handle_bot_commands(orders, current_price, alert_state):
    """
    Check for /report commands sent to the bot since last run.
    Replies only to the requester's chat — does NOT affect the 15-min timer.
    Returns (updated alert_state, state_changed).
    """
    last_update_id = alert_state.get("last_update_id", None)
    offset = (last_update_id + 1) if last_update_id is not None else None
    updates = get_bot_updates(offset=offset)

    if not updates:
        return alert_state, False

    state_changed = False
    new_last_id = last_update_id or 0

    for update in updates:
        update_id = update.get("update_id", 0)
        new_last_id = max(new_last_id, update_id)

        message = update.get("message", {})
        text = message.get("text", "").strip().lower()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not chat_id:
            continue

        if text.startswith("/report"):
            print(f"📲 /report command from chat {chat_id}")
            if not orders:
                send_telegram("⚪ No open positions at the moment.", chat_ids=[chat_id])
            else:
                msg = build_report_msg(orders, current_price)
                send_telegram(msg, chat_ids=[chat_id])
                print(f"✅ Instant /report sent to chat {chat_id}")

    if new_last_id != (last_update_id or 0):
        alert_state["last_update_id"] = new_last_id
        state_changed = True

    return alert_state, state_changed

# ==========================================
# MAIN
# ==========================================

def main():
    print("=" * 40)
    print("BTC Position Alert Check")
    print(f"Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 40)

    # Fetch price
    try:
        current_price = fetch_btc_price()
    except Exception as e:
        print(f"❌ Failed to fetch price: {e}")
        return

    # Load orders
    orders = load_json(ORDERS_DB, [])

    alert_state = load_json(ALERT_STATE_DB, {})
    state_changed = False

    # /report command check — always runs, even with no positions
    alert_state, cmd_changed = handle_bot_commands(orders, current_price, alert_state)
    if cmd_changed:
        state_changed = True

    if not orders:
        print("No open positions found.")
        if state_changed:
            save_json(ALERT_STATE_DB, alert_state)
        return

    print(f"Checking {len(orders)} position(s) at ${current_price:,.2f}...\n")

    alerts_sent = 0
    alerts_recovered = 0

    # ==========================================
    # PER-POSITION ALERTS
    # ==========================================

    for order in orders:
        key = f"{order.get('account')}_{order.get('side')}_{order.get('entry_price')}_{order.get('qty')}"
        liq_key = f"{key}_liq"

        # --- 1. % Move alert ---
        should_alert, move_pct, direction = check_pct_move(order, current_price)
        already_alerted = alert_state.get(key, False)

        if should_alert and not already_alerted:
            msg = build_pct_alert_msg(order, current_price, move_pct, direction)
            if send_telegram(msg):
                print(f"✅ % Alert sent — {order.get('account')} ({order.get('side')}): {move_pct:.2f}% move")
                alert_state[key] = True
                state_changed = True
                alerts_sent += 1
            else:
                print(f"❌ Telegram failed for {order.get('account')}")

        elif not should_alert and already_alerted:
            alert_state[key] = False
            state_changed = True
            alerts_recovered += 1
            print(f"↩️  {order.get('account')} % alert reset (recovered)")

        else:
            status = f"⚠️ {move_pct:.2f}% (already alerted)" if already_alerted else f"✅ {move_pct:.2f}% (safe)"
            print(f"   {order.get('account')} {order.get('side')}: {status}")

        # --- 2. Liquidation alert ---
        if order.get("liquidation"):
            liq_breached = check_liquidation(order, current_price)
            already_liq_alerted = alert_state.get(liq_key, False)

            if liq_breached and not already_liq_alerted:
                msg = build_liq_alert_msg(order, current_price)
                if send_telegram(msg):
                    print(f"💀 Liq alert sent — {order.get('account')}")
                    alert_state[liq_key] = True
                    state_changed = True
                    alerts_sent += 1
                else:
                    print(f"❌ Telegram liq alert failed for {order.get('account')}")

            elif not liq_breached and already_liq_alerted:
                alert_state[liq_key] = False
                state_changed = True
                print(f"↩️  {order.get('account')} liq alert reset")

    # ==========================================
    # 15-MIN PORTFOLIO REPORT
    # ==========================================

    now = datetime.datetime.utcnow()
    last_report_str = alert_state.get("last_report_time")
    send_report = False

    if last_report_str:
        last_report = datetime.datetime.fromisoformat(last_report_str)
        minutes_since = (now - last_report).total_seconds() / 60
        if minutes_since >= REPORT_INTERVAL_MINUTES:
            send_report = True
    else:
        # First run — send report immediately
        send_report = True

    if send_report:
        msg = build_report_msg(orders, current_price)
        if send_telegram(msg):
            print(f"📊 15-min report sent")
            alert_state["last_report_time"] = now.isoformat()
            state_changed = True
        else:
            print(f"❌ Telegram report failed")

    # Save state
    if state_changed:
        save_json(ALERT_STATE_DB, alert_state)

    print(f"\nDone — Alerts sent: {alerts_sent} | Recovered: {alerts_recovered}")


if __name__ == "__main__":
    main()