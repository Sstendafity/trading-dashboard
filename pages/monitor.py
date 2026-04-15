import streamlit as st
import pandas as pd
import requests
import json
import os
import datetime
import time
import ccxt
from github import Github
import sys
sys.path.insert(0, os.getcwd())
from auth import check_password

# if not check_password():
#     st.stop()

# ==========================================
# CONFIGURATION
# ==========================================

ORDERS_DB = "running_orders.json"
USD_TO_INR = 85.0
LOT_SIZE = 0.001  # 1 lot = 0.001 BTC

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard"

ACCOUNTS = [f"A-{i}" for i in range(1, 16)]
ACCOUNT_GROUP = {
    "A-1": "Delta", "A-2": "Delta", "A-3": "Delta", "A-4": "Delta", "A-5": "Delta", "A-6": "Delta",
    "A-7": "CS", "A-8": "CS", "A-9": "CS", "A-10": "CS", "A-11": "CS",
    "A-12": "Pi42", "A-13": "CDX", "A-14": "MDX", "A-15": "ZEP"
}

# ==========================================
# CUSTOM CSS
# ==========================================

st.markdown("""
<style>
.monitor-card {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 10px;
}
.price-display {
    font-size: 2.2rem;
    font-weight: 800;
    font-family: 'Courier New', monospace;
    letter-spacing: -1px;
}
.price-up { color: #00e676; }
.price-down { color: #ff1744; }
.price-neutral { color: #ffffff; }
.stat-label {
    font-size: 11px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 2px;
}
.stat-value {
    font-size: 18px;
    font-weight: 700;
    font-family: 'Courier New', monospace;
}
.badge-buy {
    background: rgba(0, 230, 118, 0.15);
    color: #00e676;
    border: 1px solid #00e676;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
.badge-sell {
    background: rgba(255, 23, 68, 0.15);
    color: #ff1744;
    border: 1px solid #ff1744;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
.danger-zone {
    background: rgba(255, 23, 68, 0.08);
    border: 1px solid rgba(255, 23, 68, 0.3);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: #ff6b6b;
}
.summary-box {
    background: #0f0f23;
    border-radius: 10px;
    padding: 14px;
    text-align: center;
}
.divider { border-top: 1px solid #2a2a4a; margin: 8px 0; }
div.stButton > button {
    white-space: nowrap;
    padding-left: 16px;
    padding-right: 16px;
    height: auto;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# LOT HELPERS
# ==========================================

def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)

def lots_to_btc(lots):
    return lots * LOT_SIZE

def fmt_lots(btc_qty):
    return f"{btc_to_lots(btc_qty)} lots"

# ==========================================
# PRICE FETCHING
# ==========================================

def fetch_with_ccxt():
    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']
    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': False,
            })
            ticker = exchange.fetch_ticker('BTC/USDT')
            return {
                "price": float(ticker['last']),
                "change_pct": float(ticker['percentage'] or 0),
                "high": float(ticker['high'] or 0),
                "low": float(ticker['low'] or 0),
                "ok": True,
                "source": exchange_id
            }
        except Exception:
            continue
    return None

def fetch_with_coingecko():
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin",
        timeout=10
    )
    data = r.json()[0]
    return {
        "price": float(data["current_price"]),
        "change_pct": float(data["price_change_percentage_24h"] or 0),
        "high": float(data["high_24h"]),
        "low": float(data["low_24h"]),
        "ok": True,
        "source": "coingecko"
    }

def fetch_with_bybit():
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT",
        timeout=10
    )
    data = r.json()["result"]["list"][0]
    return {
        "price": float(data["lastPrice"]),
        "change_pct": float(data["price24hPcnt"]) * 100,
        "high": float(data["highPrice24h"]),
        "low": float(data["lowPrice24h"]),
        "ok": True,
        "source": "bybit"
    }

def _do_fetch():
    try:
        result = fetch_with_ccxt()
        if result:
            return result
    except Exception:
        pass
    try:
        return fetch_with_coingecko()
    except Exception:
        pass
    try:
        return fetch_with_bybit()
    except Exception:
        pass
    return None

# ==========================================
# STORAGE
# ==========================================

def load_orders():
    if os.path.exists(ORDERS_DB):
        try:
            with open(ORDERS_DB, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_orders(orders):
    with open(ORDERS_DB, "w") as f:
        json.dump(orders, f, indent=2)
    if GITHUB_TOKEN:
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(REPO_NAME)
            content = json.dumps(orders, indent=2)
            try:
                existing = repo.get_contents(ORDERS_DB)
                repo.update_file(ORDERS_DB, "Update running orders", content, existing.sha)
            except Exception:
                repo.create_file(ORDERS_DB, "Create running orders", content)
        except Exception as e:
            st.warning(f"GitHub sync failed: {e}")

# ==========================================
# CALCULATIONS
# ==========================================

def calculate(order, current_price):
    side = order.get("side", "Buy")
    entry = order.get("entry_price", 0) or 0
    qty = order.get("qty", 0) or 0
    liq = order.get("liquidation", None)
    tg = order.get("target", None)
    sl = order.get("stop_loss", None)
    cp = current_price

    if side == "Buy":
        ep_cp_diff = cp - entry
        liq_danger = (cp - liq) if liq else None
        ep_liq_diff = (entry - liq) if liq else None
        ep_tg_diff = (tg - entry) if tg else None
        ep_sl_diff = (entry - sl) if sl else None
    else:
        ep_cp_diff = entry - cp
        liq_danger = (liq - cp) if liq else None
        ep_liq_diff = (liq - entry) if liq else None
        ep_tg_diff = (entry - tg) if tg else None
        ep_sl_diff = (sl - entry) if sl else None

    running_usd = ep_cp_diff * qty
    running_inr = running_usd * USD_TO_INR

    liq_loss_usd = (ep_liq_diff * qty) if ep_liq_diff is not None else None
    liq_loss_inr = (liq_loss_usd * USD_TO_INR) if liq_loss_usd is not None else None

    profit_usd = (ep_tg_diff * qty) if ep_tg_diff is not None else None
    profit_inr = (profit_usd * USD_TO_INR) if profit_usd is not None else None

    loss_usd = (ep_sl_diff * qty) if ep_sl_diff is not None else None
    loss_inr = (loss_usd * USD_TO_INR) if loss_usd is not None else None

    danger_pct = None
    if liq_danger is not None and ep_liq_diff and ep_liq_diff != 0:
        danger_pct = (1 - (liq_danger / ep_liq_diff)) * 100

    return {
        "ep_cp_diff": ep_cp_diff,
        "running_usd": running_usd,
        "running_inr": running_inr,
        "liq_danger": liq_danger,
        "ep_liq_diff": ep_liq_diff,
        "liq_loss_usd": liq_loss_usd,
        "liq_loss_inr": liq_loss_inr,
        "profit_usd": profit_usd,
        "profit_inr": profit_inr,
        "loss_usd": loss_usd,
        "loss_inr": loss_inr,
        "danger_pct": danger_pct,
    }

# ==========================================
# UI HELPERS
# ==========================================

def fmt_usd(v): return f"${v:+,.2f}" if v is not None else "—"
def fmt_inr(v): return f"₹{v:+,.0f}" if v is not None else "—"
def fmt_price(v): return f"{v:,.1f}" if v is not None else "—"
def color_val(v):
    if v is None: return "color:#888"
    return "color:#00e676" if v >= 0 else "color:#ff1744"

def summary_box(label, value, color="#fff"):
    return f'<div class="summary-box"><div class="stat-label">{label}</div><div class="stat-value" style="color:{color}">{value}</div></div>'

# ==========================================
# POPUP DIALOGS
# ==========================================

@st.dialog("➕ Add New Position", width="large")
def dialog_add_position(orders):
    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS, key="dlg_acc")
        side = st.selectbox("Side", ["Buy", "Sell"], key="dlg_side")
    with f2:
        entry = st.number_input("Entry Price (USD)", min_value=0.0, value=0.0, step=0.1, key="dlg_entry")
        lot_qty = st.number_input("Quantity (Lots)", min_value=1, value=1, step=1, key="dlg_qty",
                                  help="1 lot = 0.001 BTC")
        st.caption(f"= {lots_to_btc(lot_qty):.4f} BTC")
        threshold = st.number_input("Alert Threshold (%)", min_value=0.5, max_value=20.0,
                                    value=3.0, step=0.5, key="dlg_threshold")
    with f3:
        liq_input = st.number_input("Liquidation Price (optional)", min_value=0.0,
                                    value=0.0, step=0.1, key="dlg_liq")
        liq_val = liq_input if liq_input > 0 else None

    f4, f5 = st.columns(2)
    with f4:
        tg_input = st.number_input("Target / TG (optional)", min_value=0.0,
                                   value=0.0, step=0.1, key="dlg_tg")
        tg_val = tg_input if tg_input > 0 else None
    with f5:
        sl_input = st.number_input("Stop Loss / SL (optional)", min_value=0.0,
                                   value=0.0, step=0.1, key="dlg_sl")
        sl_val = sl_input if sl_input > 0 else None

    if st.button("✅ Add Position", use_container_width=True):
        if entry <= 0 or lot_qty <= 0:
            st.error("Entry Price and Quantity are required.")
        else:
            new_order = {
                "account": acc,
                "side": side,
                "entry_price": entry,
                "qty": lots_to_btc(lot_qty),
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "added_at": str(datetime.datetime.now()),
                "alert_threshold": threshold,
            }
            orders.append(new_order)
            save_orders(orders)
            st.success(f"✅ {acc} {side} — {lot_qty} lots added.")
            st.rerun()

@st.dialog("✏️ Edit Position", width="large")
def dialog_edit_position(orders, idx):
    default = orders[idx]
    default_lots = btc_to_lots(default.get("qty", 0) or 0)

    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS,
                           index=ACCOUNTS.index(default.get("account", "A-1")) if default.get("account") in ACCOUNTS else 0,
                           key="dlg_edit_acc")
        side = st.selectbox("Side", ["Buy", "Sell"],
                            index=0 if default.get("side", "Buy") == "Buy" else 1,
                            key="dlg_edit_side")
    with f2:
        entry = st.number_input("Entry Price (USD)", min_value=0.0,
                                value=float(default.get("entry_price", 0) or 0),
                                step=0.1, key="dlg_edit_entry")
        lot_qty = st.number_input("Quantity (Lots)", min_value=1,
                                  value=max(1, default_lots),
                                  step=1, key="dlg_edit_qty",
                                  help="1 lot = 0.001 BTC")
        st.caption(f"= {lots_to_btc(lot_qty):.4f} BTC")
        threshold = st.number_input("Alert Threshold (%)", min_value=0.5, max_value=20.0,
                                    value=float(default.get("alert_threshold", 3.0)),
                                    step=0.5, key="dlg_edit_threshold")
    with f3:
        liq_default = default.get("liquidation", None)
        liq_input = st.number_input("Liquidation Price (optional)", min_value=0.0,
                                    value=float(liq_default) if liq_default else 0.0,
                                    step=0.1, key="dlg_edit_liq")
        liq_val = liq_input if liq_input > 0 else None

    f4, f5 = st.columns(2)
    with f4:
        tg_default = default.get("target", None)
        tg_input = st.number_input("Target / TG (optional)", min_value=0.0,
                                   value=float(tg_default) if tg_default else 0.0,
                                   step=0.1, key="dlg_edit_tg")
        tg_val = tg_input if tg_input > 0 else None
    with f5:
        sl_default = default.get("stop_loss", None)
        sl_input = st.number_input("Stop Loss / SL (optional)", min_value=0.0,
                                   value=float(sl_default) if sl_default else 0.0,
                                   step=0.1, key="dlg_edit_sl")
        sl_val = sl_input if sl_input > 0 else None

    if st.button("💾 Update Position", use_container_width=True):
        if entry <= 0 or lot_qty <= 0:
            st.error("Entry Price and Quantity are required.")
        else:
            orders[idx] = {
                "account": acc,
                "side": side,
                "entry_price": entry,
                "qty": lots_to_btc(lot_qty),
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "added_at": default.get("added_at", str(datetime.datetime.now())),
                "alert_threshold": threshold,
            }
            save_orders(orders)
            st.success("✅ Position updated.")
            st.rerun()

# ==========================================
# LIVE FRAGMENT
# Covers: price bar + danger alerts +
#         summary boxes + analysis table
# Reruns every 30s independently —
# dialogs and position cards stay open
# ==========================================
@st.fragment(run_every=5)
def telegram_command_listener(orders, cp):
    """Polls Telegram every 5s for /report command. Runs inside Streamlit — instant response."""
    TELEGRAM_TOKEN_UI = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_IDS_UI = [
        st.secrets.get("TELEGRAM_CHAT_ID", ""),
        st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
    ]
    TELEGRAM_CHAT_IDS_UI = [c for c in TELEGRAM_CHAT_IDS_UI if c]

    if not TELEGRAM_TOKEN_UI:
        return

    # Get last processed update_id from session state
    offset = st.session_state.get("tg_last_update_id", None)
    params = {"timeout": 0, "limit": 10}
    if offset is not None:
        params["offset"] = offset + 1

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/getUpdates",
            params=params,
            timeout=5
        )
        if not r.ok:
            return
        updates = r.json().get("result", [])
    except Exception:
        return

    if not updates:
        return

    new_last_id = offset or 0
    for update in updates:
        update_id = update.get("update_id", 0)
        new_last_id = max(new_last_id, update_id)

        message = update.get("message", {})
        text = message.get("text", "").strip().lower()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not chat_id:
            continue

        if text.startswith("/report"):
            if not orders:
                msg = "⚪ No open positions at the moment."
            else:
                # Fetch fresh price at the moment /report is received
                fresh = _do_fetch()
                cp = fresh["price"] if fresh else st.session_state.get("current_cp", 0)

                # Build report
                total_inr, total_usd = 0, 0
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

                ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 16)]
                active_accounts = {o.get("account") for o in orders}
                inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]

                for o in orders:
                    running_usd = (cp - o.get("entry_price", 0)) * o.get("qty", 0) if o.get("side") == "Buy" else (o.get("entry_price", 0) - cp) * o.get("qty", 0)
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
                    f"📊 <b>INSTANT PORTFOLIO REPORT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🕐 {now}\n"
                    f"₿ BTC Price: <code>${cp:,.1f}</code>\n"
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

            # Reply only to the requester
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )

    st.session_state["tg_last_update_id"] = new_last_id

@st.fragment(run_every=30)
def live_dashboard(orders):
    # --- Fetch price ---
    result = _do_fetch()
    if result:
        st.session_state["price_cache"] = result

    price_data = st.session_state.get("price_cache",
        {"price": 0, "change_pct": 0, "high": 0, "low": 0, "ok": False, "source": "none"})
    cp = price_data["price"]

    if not price_data.get("ok"):
        st.error("⚠️ Could not fetch price. All sources failed.")

    # --- Price bar ---
    col_price, col_chg, col_high, col_low, col_refresh = st.columns([3, 2, 2, 2, 1])
    change_color = "price-up" if price_data["change_pct"] >= 0 else "price-down"
    change_arrow = "▲" if price_data["change_pct"] >= 0 else "▼"

    with col_price:
        st.markdown(f'<div class="price-display {change_color}">BTC ${cp:,.1f}</div>', unsafe_allow_html=True)
    with col_chg:
        st.markdown(f'<div class="stat-label">24h Change</div><div class="stat-value" style="{color_val(price_data["change_pct"])}">{change_arrow} {abs(price_data["change_pct"]):.2f}%</div>', unsafe_allow_html=True)
    with col_high:
        st.markdown(f'<div class="stat-label">24h High</div><div class="stat-value" style="color:#fff">${price_data["high"]:,.1f}</div>', unsafe_allow_html=True)
    with col_low:
        st.markdown(f'<div class="stat-label">24h Low</div><div class="stat-value" style="color:#fff">${price_data["low"]:,.1f}</div>', unsafe_allow_html=True)
    with col_refresh:
        if st.button("🔄", help="Force refresh price"):
            st.session_state.pop("price_cache", None)
            st.rerun(scope="fragment")

    # Send instant report button
    TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_IDS_UI = [
        st.secrets.get("TELEGRAM_CHAT_ID", ""),
        st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
    ]
    TELEGRAM_CHAT_IDS_UI = [c for c in TELEGRAM_CHAT_IDS_UI if c]

    if st.button("📊 Send Report Now", help="Send instant portfolio report to Telegram"):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS_UI:
            st.warning("Telegram not configured in secrets.")
        elif not orders:
            st.info("No open positions to report.")
        else:
            # Build report inline
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

            ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 16)]
            active_accounts = {o.get("account") for o in orders}
            inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]

            for o in orders:
                running_usd = (cp - o.get("entry_price", 0)) * o.get("qty", 0) if o.get("side") == "Buy" else (o.get("entry_price", 0) - cp) * o.get("qty", 0)
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
                f"📊 <b>INSTANT PORTFOLIO REPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🕐 {now}\n"
                f"₿ BTC Price: <code>${cp:,.1f}</code>\n"
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

            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            all_ok = True
            for chat_id in TELEGRAM_CHAT_IDS_UI:
                r = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
                if not r.ok:
                    all_ok = False
            if all_ok:
                st.success("✅ Report sent to Telegram!")
            else:
                st.error("❌ Failed to send to some chats.")

    st.caption(f"Source: {price_data.get('source', '—')} · {datetime.datetime.now().strftime('%H:%M:%S')}")
    st.markdown("---")

    if not orders:
        st.info("👋 No open positions. Add one below.")
        return

    calcs = [calculate(o, cp) for o in orders]

    # --- Danger alerts ---
    danger_orders = [
        (o, c) for o, c in zip(orders, calcs)
        if c["danger_pct"] is not None and c["danger_pct"] >= 70
    ]
    if danger_orders:
        for o, c in danger_orders:
            st.markdown(f"""
            <div class="danger-zone">
                🚨 <b>{o['account']}</b> ({o['side']}) is <b>{c['danger_pct']:.0f}%</b> toward liquidation!
                Current: ${cp:,.1f} | Liquidation: ${o['liquidation']:,.1f} | Distance: ${abs(c['liq_danger']):,.1f}
            </div>
            """, unsafe_allow_html=True)

    # --- Summary boxes ---
    total_running_inr = sum(c["running_inr"] for c in calcs)
    profit_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] > 0]
    loss_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] < 0]
    buy_qty = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Buy")
    sell_qty = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Sell")

    st.markdown("### 📊 Summary")
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    net_color = "#00e676" if total_running_inr >= 0 else "#ff1744"
    with s1: st.markdown(summary_box("Net Running P&L", fmt_inr(total_running_inr), net_color), unsafe_allow_html=True)
    with s2: st.markdown(summary_box("Profit Positions", len(profit_orders), "#00e676"), unsafe_allow_html=True)
    with s3: st.markdown(summary_box("Loss Positions", len(loss_orders), "#ff1744"), unsafe_allow_html=True)
    with s4: st.markdown(summary_box("Total Positions", len(orders), "#fff"), unsafe_allow_html=True)
    with s5: st.markdown(summary_box("Buy Lots", f"{btc_to_lots(buy_qty)}", "#00e676"), unsafe_allow_html=True)
    with s6: st.markdown(summary_box("Sell Lots", f"{btc_to_lots(sell_qty)}", "#ff1744"), unsafe_allow_html=True)

    st.markdown("---")

    # --- Analysis table ---
    st.markdown("### 📋 Position Analysis")

    sorted_pairs = sorted(zip(orders, calcs), key=lambda x: x[1]["running_inr"])
    table_rows = []
    for o, c in sorted_pairs:
        danger_str = f"{c['danger_pct']:.0f}% to Liq" if c["danger_pct"] is not None else "—"
        table_rows.append({
            "Account": o["account"],
            "Exchange": ACCOUNT_GROUP.get(o["account"], "—"),
            "Side": o["side"],
            "Entry": fmt_price(o.get("entry_price")),
            "Qty (Lots)": btc_to_lots(o.get("qty", 0) or 0),
            "EP×CP": fmt_price(c["ep_cp_diff"]),
            "Run P&L (USD)": fmt_usd(c["running_usd"]),
            "Run P&L (INR)": fmt_inr(c["running_inr"]),
            "Liq Price": fmt_price(o.get("liquidation")),
            "Liq Danger": danger_str,
            "Liq Loss (INR)": fmt_inr(c["liq_loss_inr"]),
            "TG": fmt_price(o.get("target")),
            "Profit (INR)": fmt_inr(c["profit_inr"]),
            "SL": fmt_price(o.get("stop_loss")),
            "Loss (INR)": fmt_inr(c["loss_inr"]),
        })

    table_df = pd.DataFrame(table_rows)

    def style_table(df):
        def color_cells(val):
            if isinstance(val, str):
                if val.startswith("₹+") or val.startswith("$+"): return "color: #00e676; font-weight: bold"
                if val.startswith("₹-") or val.startswith("$-"): return "color: #ff1744; font-weight: bold"
            return ""
        return df.style.map(color_cells, subset=["Run P&L (USD)", "Run P&L (INR)", "Profit (INR)", "Loss (INR)", "Liq Loss (INR)"])

    st.dataframe(style_table(table_df), use_container_width=True, hide_index=True)
    st.markdown("---")

    # Store current price for position cards below
    st.session_state["current_cp"] = cp

# ==========================================
# MAIN PAGE
# ==========================================

st.title("⚡ Live Order Monitor")

orders = load_orders()
cp = st.session_state.get("current_cp", 0)

telegram_command_listener(orders, cp)
live_dashboard(orders)

# ==========================================
# ADD POSITION BUTTON
# ==========================================

if st.button("➕ Add New Position"):
    dialog_add_position(orders)

st.markdown("---")

# ==========================================
# POSITION CARDS
# Static section — not in fragment
# so Edit/Delete dialogs stay open
# ==========================================

if orders:
    st.markdown("### 🗂️ Position Cards")

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        filter_side = st.selectbox("Filter Side", ["All", "Buy", "Sell"])
    with filter_col2:
        filter_acc = st.multiselect("Filter Account", ACCOUNTS, default=[])
    with filter_col3:
        filter_danger = st.checkbox("⚠️ Show danger only (≥70% to Liq)")

    filtered = [
        (o, calculate(o, cp)) for o in orders
        if (filter_side == "All" or o["side"] == filter_side)
        and (not filter_acc or o["account"] in filter_acc)
        and (not filter_danger or (calculate(o, cp)["danger_pct"] or 0) >= 70)
    ]

    if not filtered:
        st.info("No positions match the filter.")

    for i, (o, c) in enumerate(filtered):
        side_label = "BUY / LONG" if o["side"] == "Buy" else "SELL / SHORT"
        danger_pct = c["danger_pct"] or 0

        with st.expander(
            f"{o['account']} ({ACCOUNT_GROUP.get(o['account'], '?')}) — {side_label} — "
            f"Running: {fmt_inr(c['running_inr'])}",
            expanded=(danger_pct >= 70)
        ):
            c1, c2, c3, c4 = st.columns(4)

            with c1:
                st.markdown(f'<div class="stat-label">Entry Price</div><div class="stat-value">${o.get("entry_price", 0):,.1f}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Quantity</div><div class="stat-value">{fmt_lots(o.get("qty", 0) or 0)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">EP × CP Diff</div><div class="stat-value" style="{color_val(c["ep_cp_diff"])}">{fmt_price(c["ep_cp_diff"])}</div>', unsafe_allow_html=True)

            with c2:
                st.markdown(f'<div class="stat-label">Running P&L (USD)</div><div class="stat-value" style="{color_val(c["running_usd"])}">{fmt_usd(c["running_usd"])}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Running P&L (INR)</div><div class="stat-value" style="{color_val(c["running_inr"])}">{fmt_inr(c["running_inr"])}</div>', unsafe_allow_html=True)

            with c3:
                liq = o.get("liquidation")
                if liq:
                    st.markdown(f'<div class="stat-label">Liquidation Price</div><div class="stat-value" style="color:#ff6b6b">${liq:,.1f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">CP × Liq Distance</div><div class="stat-value">${abs(c["liq_danger"]):,.1f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">Liq Loss (INR)</div><div class="stat-value" style="color:#ff1744">{fmt_inr(c["liq_loss_inr"])}</div>', unsafe_allow_html=True)
                    bar_pct = min(danger_pct, 100)
                    bar_color = "#ff1744" if bar_pct >= 70 else ("#ffa726" if bar_pct >= 40 else "#00e676")
                    st.markdown(f"""
                    <div style="margin-top:8px">
                        <div class="stat-label">Liquidation Risk</div>
                        <div style="background:#2a2a4a;border-radius:4px;height:8px;overflow:hidden">
                            <div style="width:{bar_pct}%;background:{bar_color};height:100%;border-radius:4px;transition:width 0.3s"></div>
                        </div>
                        <div style="font-size:11px;color:{bar_color};margin-top:3px">{bar_pct:.0f}% toward liquidation</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown('<div class="stat-label">Liquidation</div><div class="stat-value" style="color:#888">Not set</div>', unsafe_allow_html=True)

            with c4:
                tg = o.get("target")
                sl = o.get("stop_loss")
                if tg:
                    st.markdown(f'<div class="stat-label">Target (TG)</div><div class="stat-value" style="color:#69f0ae">${tg:,.1f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">Profit at TG (INR)</div><div class="stat-value" style="color:#00e676">{fmt_inr(c["profit_inr"])}</div>', unsafe_allow_html=True)
                if sl:
                    st.markdown(f'<div class="stat-label">Stop Loss (SL)</div><div class="stat-value" style="color:#ffa726">${sl:,.1f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">Loss at SL (INR)</div><div class="stat-value" style="color:#ff1744">{fmt_inr(c["loss_inr"])}</div>', unsafe_allow_html=True)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            btn1, btn2, _ = st.columns([2, 2, 5])
            with btn1:
                if st.button("✏️ Edit", key=f"edit_{i}"):
                    dialog_edit_position(orders, orders.index(o))
            with btn2:
                if st.button("🗑️ Close Position", key=f"del_{i}"):
                    orders.remove(o)
                    save_orders(orders)
                    st.success(f"Position {o['account']} removed.")
                    st.rerun()

# =========================================
# PROJECTION FEATURE
# =========================================
# ==========================================
# PROJECTION FEATURE
# ==========================================

st.markdown("---")
st.markdown("### 🔮 Position Projection")
st.caption("Simulate how your positions would look at a different BTC price.")

proj_col1, proj_col2 = st.columns([2, 5])
with proj_col1:
    projected_price = st.number_input(
        "Projected BTC Price (USD)",
        min_value=0.0,
        value=float(cp) if cp > 0 else 0.0,
        step=100.0,
        key="proj_price"
    )

if projected_price > 0 and orders:
    proj_calcs = [calculate(o, projected_price) for o in orders]

    # Summary
    proj_total_inr = sum(c["running_inr"] for c in proj_calcs)
    proj_profit = [o for o, c in zip(orders, proj_calcs) if c["running_inr"] > 0]
    proj_loss = [o for o, c in zip(orders, proj_calcs) if c["running_inr"] < 0]
    proj_liquidated = [
        o for o, c in zip(orders, proj_calcs)
        if o.get("liquidation") and (
            (o["side"] == "Buy" and projected_price <= o["liquidation"]) or
            (o["side"] == "Sell" and projected_price >= o["liquidation"])
        )
    ]

    # Difference from current price
    price_diff = projected_price - cp
    price_diff_pct = ((projected_price - cp) / cp * 100) if cp > 0 else 0
    diff_color = "#00e676" if price_diff >= 0 else "#ff1744"
    diff_arrow = "▲" if price_diff >= 0 else "▼"

    st.markdown(
        f'<div style="margin-bottom:12px;font-size:13px;color:{diff_color}">'
        f'{diff_arrow} ${abs(price_diff):,.1f} ({abs(price_diff_pct):.2f}%) '
        f'{"above" if price_diff >= 0 else "below"} current price (${cp:,.1f})'
        f'</div>',
        unsafe_allow_html=True
    )

    # Liquidation warning
    if proj_liquidated:
        liq_accounts = ", ".join(o["account"] for o in proj_liquidated)
        st.markdown(f"""
        <div class="danger-zone">
            💀 At ${projected_price:,.1f}, these positions would be <b>liquidated</b>: <b>{liq_accounts}</b>
        </div>
        """, unsafe_allow_html=True)

    # Summary boxes
    st.markdown("#### 📊 Projected Summary")
    ps1, ps2, ps3, ps4, ps5 = st.columns(5)
    net_color = "#00e676" if proj_total_inr >= 0 else "#ff1744"
    with ps1: st.markdown(summary_box("Net P&L", fmt_inr(proj_total_inr), net_color), unsafe_allow_html=True)
    with ps2: st.markdown(summary_box("Profit Positions", len(proj_profit), "#00e676"), unsafe_allow_html=True)
    with ps3: st.markdown(summary_box("Loss Positions", len(proj_loss), "#ff1744"), unsafe_allow_html=True)
    with ps4: st.markdown(summary_box("Liquidated", len(proj_liquidated), "#ff1744" if proj_liquidated else "#888"), unsafe_allow_html=True)
    with ps5: st.markdown(summary_box("Total Positions", len(orders), "#fff"), unsafe_allow_html=True)

    # Projection table
    st.markdown("#### 📋 Projected Analysis")
    proj_sorted = sorted(zip(orders, proj_calcs), key=lambda x: x[1]["running_inr"])
    proj_rows = []
    for o, c in proj_sorted:
        liq = o.get("liquidation")
        is_liquidated = liq and (
            (o["side"] == "Buy" and projected_price <= liq) or
            (o["side"] == "Sell" and projected_price >= liq)
        )
        danger_str = "💀 LIQUIDATED" if is_liquidated else (
            f"{c['danger_pct']:.0f}% to Liq" if c["danger_pct"] is not None else "—"
        )
        proj_rows.append({
            "Account": o["account"],
            "Exchange": ACCOUNT_GROUP.get(o["account"], "—"),
            "Side": o["side"],
            "Entry": fmt_price(o.get("entry_price")),
            "Qty (Lots)": btc_to_lots(o.get("qty", 0) or 0),
            "EP×Proj": fmt_price(c["ep_cp_diff"]),
            "Proj P&L (USD)": fmt_usd(c["running_usd"]),
            "Proj P&L (INR)": fmt_inr(c["running_inr"]),
            "Liq Price": fmt_price(o.get("liquidation")),
            "Liq Status": danger_str,
            "TG": fmt_price(o.get("target")),
            "Profit at TG (INR)": fmt_inr(c["profit_inr"]),
            "SL": fmt_price(o.get("stop_loss")),
            "Loss at SL (INR)": fmt_inr(c["loss_inr"]),
        })

    proj_df = pd.DataFrame(proj_rows)

    def style_proj_table(df):
        def color_cells(val):
            if isinstance(val, str):
                if val.startswith("₹+") or val.startswith("$+"): return "color: #00e676; font-weight: bold"
                if val.startswith("₹-") or val.startswith("$-"): return "color: #ff1744; font-weight: bold"
                if val == "💀 LIQUIDATED": return "color: #ff1744; font-weight: bold"
            return ""
        return df.style.map(color_cells, subset=["Proj P&L (USD)", "Proj P&L (INR)", "Profit at TG (INR)", "Loss at SL (INR)", "Liq Status"])

    st.dataframe(style_proj_table(proj_df), use_container_width=True, hide_index=True)

elif projected_price > 0 and not orders:
    st.info("No open positions to project.")
    
# ==========================================
# SIDEBAR INFO
# ==========================================

price_data = st.session_state.get("price_cache", {})
st.sidebar.markdown("---")
st.sidebar.markdown(f"**BTC Price:** ${price_data.get('price', 0):,.1f}")
st.sidebar.markdown(f"**Source:** {price_data.get('source', '—')}")
st.sidebar.markdown(f"**Open Positions:** {len(orders)}")