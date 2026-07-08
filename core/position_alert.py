"""
core.position_alert — the shared cron alert runner (BTC + ETH).

alert_check.py and alert_check_ETH.py were ~95% identical; the only differences
were the symbol, the lot size, and the alert-state filename. Both are now thin
wrappers that call `run_alert_check(...)` with those three values.

Behaviour is preserved exactly, including the 13-minute periodic report cadence
and the per-symbol order filtering.

Only depends on requests/ccxt (via core.price_feed) and stdlib — safe for the
`pip install requests ccxt` cron workflow.
"""

import os
import json
import datetime

from core.price_feed import fetch_price
from core.telegram import send_message_to_all
from core.pnl_report import build_report_msg

ORDERS_DB = "running_orders.json"
REPORT_INTERVAL_MINUTES = 13

# Account universe used for the "Idle Accounts" line (A-1 .. A-17).
ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]


def get_symbol(order):
    """Resolve an order's symbol, falling back to hints in the account name."""
    symbol = str(order.get("symbol", "")).upper()
    if "ETH" in symbol:
        return "ETH"
    if "BTC" in symbol:
        return "BTC"

    account = str(order.get("account", "")).upper()
    if "ETH" in account:
        return "ETH"
    return "BTC"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _telegram_credentials():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_ids = [
        os.environ["TELEGRAM_CHAT_ID"],
        os.environ.get("TELEGRAM_CHAT_ID_2", ""),
    ]
    return token, [cid for cid in chat_ids if cid]


def run_alert_check(symbol, lot_size, alert_state_db):
    """Run one alert-check pass for `symbol`, sending a report when due."""
    print("=" * 40)
    print(f"{symbol} Position Alert Check")
    print("=" * 40)

    token, chat_ids = _telegram_credentials()

    current_price = fetch_price(symbol)

    orders = load_json(ORDERS_DB, [])
    orders = [o for o in orders if get_symbol(o) == symbol]

    if not orders:
        print(f"No {symbol} positions found.")
        return

    alert_state = load_json(alert_state_db, {})
    now = datetime.datetime.utcnow()
    last_report_str = alert_state.get("last_report_time")

    send_report = False
    if last_report_str:
        last_report = datetime.datetime.fromisoformat(last_report_str)
        minutes_since = (now - last_report).total_seconds() / 60
        if minutes_since >= REPORT_INTERVAL_MINUTES:
            send_report = True
    else:
        send_report = True

    if send_report:
        msg = build_report_msg(
            orders, current_price,
            all_accounts=ALL_ACCOUNTS,
            lot_size=lot_size,
            header=f"{symbol} Report",
        )
        if send_message_to_all(token, chat_ids, msg):
            print(f"{symbol} report sent")
            alert_state["last_report_time"] = now.isoformat()
            save_json(alert_state_db, alert_state)
