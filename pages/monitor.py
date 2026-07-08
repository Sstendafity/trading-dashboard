import streamlit as st
import pandas as pd
import requests
import json
import os
import datetime
import time
from github import Github
import sys
sys.path.insert(0, os.getcwd())
from auth import check_password

from core.price_feed import fetch_ticker, fetch_ohlcv as core_fetch_ohlcv
from core.charts import build_candlestick_chart, fmt_volume

# if not check_password():
#     st.stop()

# ==========================================
# CONFIGURATION
# ==========================================

ORDERS_DB = "running_orders.json"
STOP_ORDERS_DB = "stop_orders.json"
PRE_ORDERS_DB = "pre_orders.json"

USD_TO_INR = 85.0
LOT_SIZE = 0.001      # 1 lot = 0.001 BTC
ETH_LOT_SIZE = 0.01   # 1 lot = 0.01 ETH

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard"

ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
ACCOUNT_GROUP = {
    "A-1": "Delta", "A-2": "Delta", "A-3": "Delta", "A-4": "Delta", "A-5": "Delta", "A-6": "Delta",
    "A-7": "CS", "A-8": "CS", "A-9": "CS", "A-10": "CS", "A-11": "CS",
    "A-12": "Pi42", "A-13": "CDX", "A-14": "MDX", "A-15": "ZEP", "A-16": "GTS", "A-17": "BN", "A-18": "BYT"
}

SYMBOLS = ["BTC", "ETH"]

# ==========================================
# CUSTOM CSS
# ==========================================

st.markdown("""
<style>
.monitor-card {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,0.2);
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
.price-display-eth {
    font-size: 1.5rem;
    font-weight: 800;
    font-family: 'Courier New', monospace;
    letter-spacing: -1px;
}
.price-up { color: #00c853; }
.price-down { color: #ff1744; }
.price-neutral { color: var(--text-color); }
.stat-label {
    font-size: 10px;
    color: var(--text-color);
    opacity: 0.6;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    text-align: center;
    line-height: 1.3;
}
.stat-value {
    font-size: 16px;
    font-weight: 700;
    font-family: 'Courier New', monospace;
    color: var(--text-color);
    word-break: break-word;
    text-align: center;
}
.badge-buy {
    background: rgba(0, 200, 83, 0.15);
    color: #00c853;
    border: 1px solid #00c853;
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
    color: #ff1744;
}
.summary-box {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,0.15);
    border-radius: 10px;
    padding: 14px 8px;
    text-align: center;
    min-height: 90px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}
.divider {
    border-top: 1px solid rgba(128,128,128,0.2);
    margin: 8px 0;
}
div.stButton > button {
    white-space: nowrap;
    padding-left: 16px;
    padding-right: 16px;
    height: auto;
}
/* Offset so quick-nav jumps don't land under the top toolbar */
h1, h2, h3 { scroll-margin-top: 3.5rem; }
/* Quick-nav pill links */
.quicknav { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:2px 0 12px 0; }
.quicknav .label {
    font-size:11px; color:#888; text-transform:uppercase;
    letter-spacing:1px; margin-right:2px;
}
.quicknav a {
    text-decoration:none;
    background: var(--secondary-background-color);
    border:1px solid rgba(128,128,128,0.25);
    border-radius:20px; padding:5px 14px;
    font-size:13px; font-weight:600;
    color: var(--text-color); white-space:nowrap;
}
.quicknav a:hover { border-color:#00c853; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# LOT HELPERS
# ==========================================

def get_lot_size(symbol):
    return ETH_LOT_SIZE if symbol == "ETH" else LOT_SIZE

def qty_to_lots(qty, symbol="BTC"):
    ls = get_lot_size(symbol)
    return round((qty or 0) / ls)

def lots_to_qty(lots, symbol="BTC"):
    return lots * get_lot_size(symbol)

def btc_to_lots(btc_qty):
    return round((btc_qty or 0) / LOT_SIZE)

def lots_to_btc(lots):
    return lots * LOT_SIZE

def fmt_lots(qty, symbol="BTC"):
    return f"{qty_to_lots(qty, symbol)} lots"

# ==========================================
# PRICE FETCHING
# ==========================================

# Price fetching (rich ticker dict) now lives in core.price_feed.
# `_do_fetch` is kept as a local alias so existing call sites stay unchanged.
_do_fetch = fetch_ticker

# fmt_volume is imported from core.charts.

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
            
def load_stop_orders():
    if os.path.exists(STOP_ORDERS_DB):
        try:
            with open(STOP_ORDERS_DB, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_stop_orders(stop_orders):
    with open(STOP_ORDERS_DB, "w") as f:
        json.dump(stop_orders, f, indent=2)
    if GITHUB_TOKEN:
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(REPO_NAME)
            content = json.dumps(stop_orders, indent=2)
            try:
                existing = repo.get_contents(STOP_ORDERS_DB)
                repo.update_file(STOP_ORDERS_DB, "Update stop orders", content, existing.sha)
            except Exception:
                repo.create_file(STOP_ORDERS_DB, "Create stop orders", content)
        except Exception as e:
            st.warning(f"GitHub sync failed: {e}")

def load_pre_orders():
    if os.path.exists(PRE_ORDERS_DB):
        try:
            with open(PRE_ORDERS_DB, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_pre_orders(pre_orders):
    with open(PRE_ORDERS_DB, "w") as f:
        json.dump(pre_orders, f, indent=2)
    if GITHUB_TOKEN:
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(REPO_NAME)
            content = json.dumps(pre_orders, indent=2)
            try:
                existing = repo.get_contents(PRE_ORDERS_DB)
                repo.update_file(PRE_ORDERS_DB, "Update pre orders", content, existing.sha)
            except Exception:
                repo.create_file(PRE_ORDERS_DB, "Create pre orders", content)
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

def summary_box(label, value, color=None):
    color_style = f"color:{color}" if color else "color:var(--text-color)"
    return (
        f'<div class="summary-box">'
        f'<div class="stat-label">{label}</div>'
        f'<div class="stat-value" style="{color_style}">{value}</div>'
        f'</div>'
    )

def get_order_cp(order):
    """Return correct current price for this order's symbol."""
    sym = order.get("symbol", "BTC")
    if sym == "ETH":
        return st.session_state.get("price_cache_eth", {}).get("price", 0)
    return st.session_state.get("price_cache", {}).get("price", 0)

# ==========================================
# QUICK NAV
# ==========================================

def _has_hedge(orders):
    """True if any account holds both a BTC and an ETH position.

    Matches the visibility condition of the Cross-Pair Hedge section (its
    `is_hedge` check is satisfied whenever both symbols are present).
    """
    by_acc = {}
    for o in orders:
        by_acc.setdefault(o["account"], set()).add(o.get("symbol", "BTC"))
    return any("BTC" in syms and "ETH" in syms for syms in by_acc.values())


def render_quick_nav(orders, pre_orders, stop_orders):
    """Render a compact 'Jump to' bar linking to each on-page section.

    Only sections that will actually render (based on current data) are shown,
    so every link points at a real anchor.
    """
    items = []
    if orders:
        items.append(("summary", "📊 Summary"))
        items.append(("position-analysis", "📋 Analysis"))
        if _has_hedge(orders):
            items.append(("cross-pair-hedge", "🔀 Hedge"))
    if pre_orders:
        items.append(("pre-orders", "⏳ Pre-Orders"))
    if stop_orders:
        items.append(("stop-orders", "🛑 Stop-Orders"))
    if orders:
        items.append(("position-cards", "🗂️ Positions"))
    items.append(("projection", "🔮 Projection"))

    pills = "".join(f'<a href="#{aid}">{label}</a>' for aid, label in items)
    st.markdown(
        f'<div class="quicknav"><span class="label">Jump to</span>{pills}</div>',
        unsafe_allow_html=True,
    )

# ==========================================
# CHART BUILDER
# ==========================================
# build_candlestick_chart is imported from core.charts.

def send_chart_telegram(symbol, TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS_UI):
    """Fetch OHLCV, build chart, send to Telegram. Used by both BTC and ETH buttons."""
    ohlcv = core_fetch_ohlcv(symbol)
    if not ohlcv:
        st.error(f"❌ Could not fetch {symbol} OHLCV data.")
        return

    df_full = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_full['timestamp'] = pd.to_datetime(df_full['timestamp'], unit='ms')
    df_full.set_index('timestamp', inplace=True)

    current = df_full.iloc[-2]
    candle_time = df_full.index[-2].strftime('%Y-%m-%d %H:00 UTC')
    o = current['open']
    h = current['high']
    l = current['low']
    c = current['close']
    vol = current['volume']
    vol_str = fmt_volume(vol, c)
    change = c - o
    change_hl = h - l
    change_pct = (change / o) * 100
    change_sign = "+" if change >= 0 else ""

    text_msg = (
        f"O <code>{o:,.2f}</code>  "
        f"H <code>{h:,.2f}</code>  "
        f"L <code>{l:,.2f}</code>  "
        f"C <code>{c:,.2f}</code>\n"
        f"Vol <code>{vol_str}</code>  ·  "
        f"Change OC <code>{change_sign}{change:,.2f} ({change_sign}{change_pct:.2f}%)</code>\n"
        f"Change HL <code>{change_hl:,.2f}</code>\n"
        f"<b>{symbol}/USDT · 1H · {candle_time}</b>"
    )

    df_chart = df_full.iloc[:-1].tail(24).copy()
    chart_title = (
        f"{symbol}/USDT · 1H   "
        f"O {o:,.2f}  H {h:,.2f}  L {l:,.2f}  C {c:,.2f}  "
        f"Change {change_sign}{change:,.2f} ({change_sign}{change_pct:.2f}%)  "
        f"Vol {vol_str}"
    )
    image_bytes = build_candlestick_chart(df_chart, chart_title)

    tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    tg_photo_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    all_ok = True
    for cid in TELEGRAM_CHAT_IDS_UI:
        r1 = requests.post(tg_photo_url, data={"chat_id": cid}, files={
            "photo": (f"{symbol.lower()}_chart.png", image_bytes, "image/png")
        }, timeout=30)
        r2 = requests.post(tg_url, json={
            "chat_id": cid, "text": text_msg, "parse_mode": "HTML"
        }, timeout=10)
        if not r1.ok or not r2.ok:
            all_ok = False
    if all_ok:
        st.success(f"✅ {symbol} chart sent to Telegram!")
    else:
        st.error(f"❌ Failed to send {symbol} chart to some chats.")

# ==========================================
# POPUP DIALOGS
# ==========================================

@st.dialog("➕ Add New Position", width="large")
def dialog_add_position(orders):
    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS, key="dlg_acc")
        symbol = st.selectbox("Symbol", SYMBOLS, key="dlg_symbol")
        side = st.selectbox("Side", ["Buy", "Sell"], key="dlg_side")
    with f2:
        entry = st.number_input("Entry Price (USD)", min_value=0.0, value=0.0, step=0.1, key="dlg_entry")
        ls = get_lot_size(symbol)
        lot_qty = st.number_input("Quantity (Lots)", min_value=1, value=1, step=1, key="dlg_qty",
                                  help=f"1 lot = {ls} {symbol}")
        st.caption(f"= {lot_qty * ls:.4f} {symbol}")
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
        elif liq_val and side == "Buy" and liq_val >= entry:
            st.error("❌ Liquidation price for a Buy position must be below entry price.")
        elif liq_val and side == "Sell" and liq_val <= entry:
            st.error("❌ Liquidation price for a Sell position must be above entry price.")
        else:
            new_order = {
                "account": acc,
                "symbol": symbol,
                "side": side,
                "entry_price": entry,
                "qty": lot_qty * ls,
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "added_at": str(datetime.datetime.now()),
                "alert_threshold": threshold,
            }
            orders.append(new_order)
            save_orders(orders)
            st.success(f"✅ {acc} {symbol} {side} — {lot_qty} lots added.")
            st.rerun()

@st.dialog("✏️ Edit Position", width="large")
def dialog_edit_position(orders, idx):
    default = orders[idx]
    default_sym = default.get("symbol", "BTC")
    default_lots = qty_to_lots(default.get("qty", 0) or 0, default_sym)

    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS,
                           index=ACCOUNTS.index(default.get("account", "A-1")) if default.get("account") in ACCOUNTS else 0,
                           key="dlg_edit_acc")
        symbol = st.selectbox("Symbol", SYMBOLS,
                              index=SYMBOLS.index(default_sym) if default_sym in SYMBOLS else 0,
                              key="dlg_edit_symbol")
        side = st.selectbox("Side", ["Buy", "Sell"],
                            index=0 if default.get("side", "Buy") == "Buy" else 1,
                            key="dlg_edit_side")
    with f2:
        entry = st.number_input("Entry Price (USD)", min_value=0.0,
                                value=float(default.get("entry_price", 0) or 0),
                                step=0.1, key="dlg_edit_entry")
        ls = get_lot_size(symbol)
        lot_qty = st.number_input("Quantity (Lots)", min_value=1,
                                  value=max(1, default_lots),
                                  step=1, key="dlg_edit_qty",
                                  help=f"1 lot = {ls} {symbol}")
        st.caption(f"= {lot_qty * ls:.4f} {symbol}")
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
        elif liq_val and side == "Buy" and liq_val >= entry:
            st.error("❌ Liquidation price for a Buy position must be below entry price.")
        elif liq_val and side == "Sell" and liq_val <= entry:
            st.error("❌ Liquidation price for a Sell position must be above entry price.")
        else:
            orders[idx] = {
                "account": acc,
                "symbol": symbol,
                "side": side,
                "entry_price": entry,
                "qty": lot_qty * ls,
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "added_at": default.get("added_at", str(datetime.datetime.now())),
                "alert_threshold": threshold,
            }
            save_orders(orders)
            st.success("✅ Position updated.")
            st.rerun()

@st.dialog("🛑 Add Stop-Order (Partial Close)", width="large")
def dialog_add_stop_order(orders, stop_orders):
    if not orders:
        st.info("No running positions to attach a stop-order to.")
        return

    # Build selectable list of running positions
    position_labels = []
    for idx, o in enumerate(orders):
        sym = o.get("symbol", "BTC")
        lots = qty_to_lots(o.get("qty", 0) or 0, sym)
        label = (
            f"{o['account']} [{sym}] {o['side']} @ ${o.get('entry_price',0):,.2f} "
            f"— {lots} lots"
        )
        position_labels.append(label)

    selected_label = st.selectbox("Attach to Running Position", position_labels, key="so_target_pos")
    selected_idx = position_labels.index(selected_label)
    target_order = orders[selected_idx]
    sym = target_order.get("symbol", "BTC")
    current_lots = qty_to_lots(target_order.get("qty", 0) or 0, sym)

    st.caption(f"Current position: {current_lots} lots @ ${target_order.get('entry_price',0):,.2f}")

    f1, f2 = st.columns(2)
    with f1:
        direction = st.selectbox(
            "Trigger When Price",
            ["Drops to or below", "Rises to or above"],
            key="so_direction"
        )
        trigger_price = st.number_input(
            "Trigger Price (USD)", min_value=0.0, value=0.0, step=0.1, key="so_price"
        )
    with f2:
        ls = get_lot_size(sym)
        partial_lots = st.number_input(
            "Partial Close Quantity (Lots)",
            min_value=1, max_value=max(1, current_lots), value=1, step=1,
            key="so_qty", help=f"Must be ≤ {current_lots} lots (current position size)"
        )
        st.caption(f"= {partial_lots * ls:.4f} {sym}  ·  Remaining after trigger: {current_lots - partial_lots} lots")

    if st.button("✅ Add Stop-Order", use_container_width=True):
        if trigger_price <= 0:
            st.error("Trigger price is required.")
        elif partial_lots > current_lots:
            st.error(f"Cannot close more than current position size ({current_lots} lots).")
        else:
            stop_orders.append({
                "target_account": target_order["account"],
                "target_symbol": sym,
                "target_side": target_order["side"],
                "target_entry_price": target_order.get("entry_price", 0),
                "trigger_direction": "at_or_below" if direction == "Drops to or below" else "at_or_above",
                "trigger_price": trigger_price,
                "qty": partial_lots * ls,
                "created_at": str(datetime.datetime.now()),
            })
            save_stop_orders(stop_orders)
            st.success(f"✅ Stop-order added — closes {partial_lots} lots @ ${trigger_price:,.2f}")
            st.rerun()

@st.dialog("✏️ Edit Stop-Order", width="large")
def dialog_edit_stop_order(stop_orders, idx, orders):
    default = stop_orders[idx]
    sym = default.get("target_symbol", "BTC")
    current_lots_max = 999
    for o in orders:
        if (o["account"] == default["target_account"] and
            o.get("symbol", "BTC") == sym and
            o["side"] == default["target_side"]):
            current_lots_max = qty_to_lots(o.get("qty", 0) or 0, sym)
            break

    st.caption(f"Attached to: {default['target_account']} [{sym}] {default['target_side']}")

    f1, f2 = st.columns(2)
    with f1:
        direction = st.selectbox(
            "Trigger When Price",
            ["Drops to or below", "Rises to or above"],
            index=0 if default.get("trigger_direction") == "at_or_below" else 1,
            key="so_edit_direction"
        )
        trigger_price = st.number_input(
            "Trigger Price (USD)", min_value=0.0,
            value=float(default.get("trigger_price", 0)), step=0.1, key="so_edit_price"
        )
    with f2:
        ls = get_lot_size(sym)
        current_lots = qty_to_lots(default.get("qty", 0) or 0, sym)
        partial_lots = st.number_input(
            "Partial Close Quantity (Lots)",
            min_value=1, max_value=max(1, current_lots_max), value=current_lots,
            step=1, key="so_edit_qty"
        )
        st.caption(f"= {partial_lots * ls:.4f} {sym}")

    if st.button("💾 Update Stop-Order", use_container_width=True):
        if trigger_price <= 0:
            st.error("Trigger price is required.")
        else:
            stop_orders[idx]["trigger_direction"] = "at_or_below" if direction == "Drops to or below" else "at_or_above"
            stop_orders[idx]["trigger_price"] = trigger_price
            stop_orders[idx]["qty"] = partial_lots * ls
            save_stop_orders(stop_orders)
            st.success("✅ Stop-order updated.")
            st.rerun()

@st.dialog("⏳ Add Pre-Order", width="large")
def dialog_add_pre_order(pre_orders, orders):
    st.caption(
        "If no running position exists for this account+symbol+side at trigger time, "
        "it opens as a new position. If one already exists, it pyramids (averages entry)."
    )

    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS, key="pre_acc")
        symbol = st.selectbox("Symbol", SYMBOLS, key="pre_symbol")
        side = st.selectbox("Side", ["Buy", "Sell"], key="pre_side")
    with f2:
        target_entry = st.number_input(
            "Target Entry Price (USD)", min_value=0.0, value=0.0, step=0.1, key="pre_entry",
            help="Buy: triggers when CP ≥ this price. Sell: triggers when CP ≤ this price."
        )
        ls = get_lot_size(symbol)
        lot_qty = st.number_input("Quantity (Lots)", min_value=1, value=1,
                                  step=1, key="pre_qty", help=f"1 lot = {ls} {symbol}")
        st.caption(f"= {lot_qty * ls:.4f} {symbol}")
        threshold = st.number_input("Alert Threshold (%)", min_value=0.5,
                                    max_value=20.0, value=3.0, step=0.5, key="pre_threshold")
    with f3:
        liq_input = st.number_input("Liquidation Price (optional)",
                                    min_value=0.0, value=0.0, step=0.1, key="pre_liq")
        liq_val = liq_input if liq_input > 0 else None

    f4, f5 = st.columns(2)
    with f4:
        tg_input = st.number_input("Target / TG (optional)",
                                   min_value=0.0, value=0.0, step=0.1, key="pre_tg")
        tg_val = tg_input if tg_input > 0 else None
    with f5:
        sl_input = st.number_input("Stop Loss / SL (optional)",
                                   min_value=0.0, value=0.0, step=0.1, key="pre_sl")
        sl_val = sl_input if sl_input > 0 else None

    # Live preview of fixed vs pyramid based on CURRENT state
    existing_match = [
        o for o in orders
        if o["account"] == acc and o.get("symbol", "BTC") == symbol and o["side"] == side
    ]
    if existing_match:
        ex = existing_match[0]
        ex_lots = qty_to_lots(ex.get("qty", 0) or 0, symbol)
        st.warning(
            f"📐 PYRAMID mode (as of now): existing {ex_lots} lots @ ${ex.get('entry_price',0):,.2f} "
            f"will be averaged with this order when triggered."
        )
    else:
        st.info("🆕 FIXED mode (as of now): no matching running position — will open as new.")
    st.caption("Note: mode is re-evaluated at trigger time, not when you add this order.")

    if target_entry > 0:
        cp_now = st.session_state.get("current_cp", 0) if symbol == "BTC" else st.session_state.get("current_eth_cp", 0)
        if cp_now > 0:
            diff = abs(cp_now - target_entry)
            st.caption(f"Current price: ${cp_now:,.2f} — ${diff:,.2f} away from trigger")

    if st.button("✅ Add Pre-Order", use_container_width=True):
        if target_entry <= 0 or lot_qty <= 0:
            st.error("Target Entry Price and Quantity are required.")
        elif liq_val and side == "Buy" and liq_val >= target_entry:
            st.error("❌ Liquidation price for a Buy must be below entry price.")
        elif liq_val and side == "Sell" and liq_val <= target_entry:
            st.error("❌ Liquidation price for a Sell must be above entry price.")
        else:
            pre_orders.append({
                "account": acc,
                "symbol": symbol,
                "side": side,
                "target_entry_price": target_entry,
                "qty": lot_qty * ls,
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "alert_threshold": threshold,
                "created_at": str(datetime.datetime.now()),
            })
            save_pre_orders(pre_orders)
            st.success(f"✅ Pre-order added — {acc} [{symbol}] {side} @ ${target_entry:,.2f}")
            st.rerun()

@st.dialog("✏️ Edit Pre-Order", width="large")
def dialog_edit_pre_order(pre_orders, idx, orders):
    default = pre_orders[idx]
    default_sym = default.get("symbol", "BTC")

    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS,
                           index=ACCOUNTS.index(default.get("account", "A-1")) if default.get("account") in ACCOUNTS else 0,
                           key="pre_edit_acc")
        symbol = st.selectbox("Symbol", SYMBOLS,
                              index=SYMBOLS.index(default_sym) if default_sym in SYMBOLS else 0,
                              key="pre_edit_symbol")
        side = st.selectbox("Side", ["Buy", "Sell"],
                            index=0 if default.get("side", "Buy") == "Buy" else 1,
                            key="pre_edit_side")
    with f2:
        target_entry = st.number_input(
            "Target Entry Price (USD)", min_value=0.0,
            value=float(default.get("target_entry_price", 0)), step=0.1, key="pre_edit_entry"
        )
        ls = get_lot_size(symbol)
        default_lots = qty_to_lots(default.get("qty", 0) or 0, symbol)
        lot_qty = st.number_input("Quantity (Lots)", min_value=1, value=max(1, default_lots),
                                  step=1, key="pre_edit_qty")
        st.caption(f"= {lot_qty * ls:.4f} {symbol}")
        threshold = st.number_input("Alert Threshold (%)", min_value=0.5, max_value=20.0,
                                    value=float(default.get("alert_threshold", 3.0)),
                                    step=0.5, key="pre_edit_threshold")
    with f3:
        liq_default = default.get("liquidation")
        liq_input = st.number_input("Liquidation Price (optional)", min_value=0.0,
                                    value=float(liq_default) if liq_default else 0.0,
                                    step=0.1, key="pre_edit_liq")
        liq_val = liq_input if liq_input > 0 else None

    f4, f5 = st.columns(2)
    with f4:
        tg_default = default.get("target")
        tg_input = st.number_input("Target / TG (optional)", min_value=0.0,
                                   value=float(tg_default) if tg_default else 0.0,
                                   step=0.1, key="pre_edit_tg")
        tg_val = tg_input if tg_input > 0 else None
    with f5:
        sl_default = default.get("stop_loss")
        sl_input = st.number_input("Stop Loss / SL (optional)", min_value=0.0,
                                   value=float(sl_default) if sl_default else 0.0,
                                   step=0.1, key="pre_edit_sl")
        sl_val = sl_input if sl_input > 0 else None

    # Live mode preview
    existing_match = [
        o for o in orders
        if o["account"] == acc and o.get("symbol", "BTC") == symbol and o["side"] == side
    ]
    if existing_match:
        ex = existing_match[0]
        ex_lots = qty_to_lots(ex.get("qty", 0) or 0, symbol)
        st.warning(f"📐 PYRAMID mode (as of now): existing {ex_lots} lots @ ${ex.get('entry_price',0):,.2f}")
    else:
        st.info("🆕 FIXED mode (as of now): will open as new position.")

    if st.button("💾 Update Pre-Order", use_container_width=True):
        if target_entry <= 0 or lot_qty <= 0:
            st.error("Target Entry Price and Quantity are required.")
        elif liq_val and side == "Buy" and liq_val >= target_entry:
            st.error("❌ Liquidation price for a Buy must be below entry price.")
        elif liq_val and side == "Sell" and liq_val <= target_entry:
            st.error("❌ Liquidation price for a Sell must be above entry price.")
        else:
            pre_orders[idx].update({
                "account": acc,
                "symbol": symbol,
                "side": side,
                "target_entry_price": target_entry,
                "qty": lot_qty * ls,
                "liquidation": liq_val,
                "target": tg_val,
                "stop_loss": sl_val,
                "alert_threshold": threshold,
            })
            save_pre_orders(pre_orders)
            st.success("✅ Pre-order updated.")
            st.rerun()

@st.dialog("🗑️ Bulk Close Positions", width="large")
def dialog_bulk_close(orders, filtered):
    if "bulk_close_version" not in st.session_state:
        st.session_state["bulk_close_version"] = 0

    version = st.session_state["bulk_close_version"]

    # Select All / Deselect All — no st.rerun(), pre-set keys instead
    sa1, sa2, _ = st.columns([2, 2, 5])
    with sa1:
        if st.button("☑️ Select All", use_container_width=True, key="bulk_sel_all"):
            new_v = version + 1
            st.session_state["bulk_close_version"] = new_v
            for i in range(len(filtered)):
                st.session_state[f"bulk_chk_{new_v}_{i}"] = True
            version = new_v
    with sa2:
        if st.button("⬜ Deselect All", use_container_width=True, key="bulk_desel_all"):
            new_v = version + 1
            st.session_state["bulk_close_version"] = new_v
            for i in range(len(filtered)):
                st.session_state[f"bulk_chk_{new_v}_{i}"] = False
            version = new_v

    st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)

    selected_to_close = []
    for i, (o, c) in enumerate(filtered):
        sym = o.get("symbol", "BTC")
        side_label = "BUY" if o["side"] == "Buy" else "SELL"
        pnl_sign = "+" if c["running_inr"] >= 0 else ""
        exchange = ACCOUNT_GROUP.get(o["account"], "?")
        lots = qty_to_lots(o.get("qty", 0) or 0, sym)

        label = (
            f"{o['account']} ({exchange}) · {sym} · {side_label} · "
            f"${o.get('entry_price', 0):,.2f} · {lots} lots · "
            f"₹{pnl_sign}{c['running_inr']:,.0f}"
        )
        checked = st.checkbox(label, key=f"bulk_chk_{version}_{i}")
        if checked:
            selected_to_close.append(o)

    st.markdown("---")

    if selected_to_close:
        st.warning(f"⚠️ {len(selected_to_close)} position(s) selected.")
        if st.button(
            f"🗑️ Close {len(selected_to_close)} Position(s)",
            type="primary",
            use_container_width=True,
            key="bulk_close_confirm"
        ):
            for o in selected_to_close:
                if o in orders:
                    orders.remove(o)
            save_orders(orders)
            st.session_state["bulk_close_version"] = 0
            st.rerun()  # ← only here, after actual deletion, closing dialog is fine
    else:
        st.info("No positions selected. Check positions above to close them.")

# ==========================================
# TELEGRAM COMMAND LISTENER FRAGMENT
# ==========================================

@st.fragment(run_every=5)
def telegram_command_listener(orders, cp):
    TELEGRAM_TOKEN_UI = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_IDS_UI = [
        st.secrets.get("TELEGRAM_CHAT_ID", ""),
        st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
    ]
    TELEGRAM_CHAT_IDS_UI = [c for c in TELEGRAM_CHAT_IDS_UI if c]

    if not TELEGRAM_TOKEN_UI:
        return

    offset = st.session_state.get("tg_last_update_id", None)
    params = {"timeout": 0, "limit": 10}
    if offset is not None:
        params["offset"] = offset + 1

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/getUpdates",
            params=params, timeout=5
        )
        if not r.ok:
            return
        updates = r.json().get("result", [])
    except Exception:
        return

    new_last_id = offset or 0
    eth_cp = st.session_state.get("price_cache_eth", {}).get("price", 0)

    for update in updates:
        update_id = update.get("update_id", 0)
        new_last_id = max(new_last_id, update_id)

        message = update.get("message", {})
        raw_text = message.get("text", "").strip()
        text = raw_text.lower()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not chat_id:
            continue

        # /report
        if text.startswith("/report"):
            if not orders:
                msg = "⚪ No open positions at the moment."
            else:
                fresh_btc = _do_fetch('BTC')
                fresh_eth = _do_fetch('ETH')
                btc_price = fresh_btc["price"] if fresh_btc else cp
                eth_price = fresh_eth["price"] if fresh_eth else eth_cp

                total_usd = total_profit = total_loss = total_inr = 0
                profit_count = loss_count = 0
                buy_qty_btc = sell_qty_btc = buy_qty_eth = sell_qty_eth = 0
                lines = []
                order_pnls = []

                ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
                active_accounts_btc = {o.get("account") for o in orders if o.get("symbol", "BTC") == "BTC"}
                active_accounts_eth = {o.get("account") for o in orders if o.get("symbol") == "ETH"}
                idle_btc = [a for a in ALL_ACCOUNTS if a not in active_accounts_btc]
                idle_eth = [a for a in ALL_ACCOUNTS if a not in active_accounts_eth]
                now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

                for o in orders:
                    sym = o.get("symbol", "BTC")
                    price = eth_price if sym == "ETH" else btc_price
                    running_usd = (price - o.get("entry_price", 0)) * o.get("qty", 0) if o.get("side") == "Buy" else (o.get("entry_price", 0) - price) * o.get("qty", 0)
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
                    qty = o.get("qty", 0) or 0
                    if o.get("side") == "Buy":
                        if sym == "ETH": buy_qty_eth += qty
                        else: buy_qty_btc += qty
                    else:
                        if sym == "ETH": sell_qty_eth += qty
                        else: sell_qty_btc += qty

                order_pnls.sort(key=lambda x: x[2], reverse=True)

                for o, running_usd, running_inr in order_pnls:
                    sym = o.get("symbol", "BTC")
                    side_emoji = "🟢" if o.get("side") == "Buy" else "🔴"
                    pnl_sign = "+" if running_inr >= 0 else ""
                    lots = qty_to_lots(o.get("qty", 0), sym)
                    lines.append(
                        f"  {side_emoji} <b>{o.get('account')}</b> [{sym}] "
                        f"@ ${o.get('entry_price', 0):,.1f} | {lots} lots "
                        f"→ <code>{pnl_sign}₹{running_inr:,.0f}</code>"
                    )

                total_sign = "+" if total_inr >= 0 else ""
                msg = (
                    f"₿ <code>${btc_price:,.1f}</code>  Ξ <code>${eth_price:,.2f}</code>\n"
                    f"P: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
                    f"L: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
                    f"<b>T</b>: <code>{total_sign}₹{total_inr:,.0f}</code>\n"
                    f"BTC BQ: {btc_to_lots(buy_qty_btc)} | SQ: {btc_to_lots(sell_qty_btc)} lots\n"
                    f"ETH BQ: {qty_to_lots(buy_qty_eth, 'ETH')} | SQ: {qty_to_lots(sell_qty_eth, 'ETH')} lots\n\n"
                )
                msg += "\n".join(lines)
                msg += (
                    f"\n\nTotal Orders: {len(orders)}\n"
                    f"BTC Idle ({len(idle_btc)}): {', '.join(idle_btc) if idle_btc else 'None'}\n"
                    f"ETH Idle ({len(idle_eth)}): {', '.join(idle_eth) if idle_eth else 'None'}"
                )

            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )

        # /setuppricealert
        elif text.startswith("/setuppricealert"):
            # Ask which symbol
            if cp <= 0:
                fresh = _do_fetch('BTC')
                cp = fresh["price"] if fresh else 0
            st.session_state["awaiting_interval_chat"] = chat_id
            st.session_state["awaiting_interval_symbol"] = "BTC"
            st.session_state["price_alert_current_cp"] = cp
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                json={"chat_id": chat_id, "text":
                    f"🔔 <b>Price Interval Alert Setup (BTC)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Please send the price interval you want to be alerted at.\n\n"
                    f"<b>Example:</b> Send <code>500</code> to get alerted every $500 move.\n\n"
                    f"Current BTC: <code>${cp:,.0f}</code>",
                    "parse_mode": "HTML"},
                timeout=10
            )

        # /setupethalert
        elif text.startswith("/setupethalert"):
            if eth_cp <= 0:
                fresh = _do_fetch('ETH')
                eth_cp = fresh["price"] if fresh else 0
            st.session_state["awaiting_interval_chat"] = chat_id
            st.session_state["awaiting_interval_symbol"] = "ETH"
            st.session_state["price_alert_current_cp"] = eth_cp
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                json={"chat_id": chat_id, "text":
                    f"🔔 <b>Price Interval Alert Setup (ETH)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Please send the price interval you want to be alerted at.\n\n"
                    f"<b>Example:</b> Send <code>50</code> to get alerted every $50 move.\n\n"
                    f"Current ETH: <code>${eth_cp:,.2f}</code>",
                    "parse_mode": "HTML"},
                timeout=10
            )

        # /stoppricealert
        elif text.startswith("/stoppricealert"):
            if st.session_state.get("price_alert_active"):
                interval = st.session_state.get("price_alert_interval", 0)
                sym = st.session_state.get("price_alert_symbol", "BTC")
                st.session_state["price_alert_active"] = False
                st.session_state.pop("awaiting_interval_chat", None)
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                    json={"chat_id": chat_id, "text":
                        f"🛑 <b>Price Alert Stopped ({sym})</b>\n"
                        f"Interval <code>${interval:,.0f}</code> alert deactivated.\n"
                        f"Use /setuppricealert or /setupethalert to start a new one.",
                        "parse_mode": "HTML"},
                    timeout=10
                )
            else:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚪ No active price interval alert to stop."},
                    timeout=10
                )

        # Interval number input
        elif st.session_state.get("awaiting_interval_chat") == chat_id:
            try:
                interval = float(raw_text.replace(",", "").strip())
                if interval <= 0:
                    raise ValueError()

                base = st.session_state.get("price_alert_current_cp", cp)
                alert_sym = st.session_state.get("awaiting_interval_symbol", "BTC")
                if base <= 0:
                    fresh = _do_fetch(alert_sym)
                    base = fresh["price"] if fresh else 0
                if base <= 0:
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                        json={"chat_id": chat_id, "text": "❌ Could not fetch price. Please try again."},
                        timeout=10
                    )
                    return

                last_level = round(base / interval) * interval
                st.session_state["price_alert_active"] = True
                st.session_state["price_alert_interval"] = interval
                st.session_state["price_alert_base"] = base
                st.session_state["price_alert_last_level"] = last_level
                st.session_state["price_alert_setup_chat"] = chat_id
                st.session_state["price_alert_symbol"] = alert_sym
                st.session_state.pop("awaiting_interval_chat", None)
                st.session_state.pop("awaiting_interval_symbol", None)

                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                    json={"chat_id": chat_id, "text":
                        f"✅ <b>{alert_sym} Price Alert Activated!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"📏 Interval: <code>${interval:,.0f}</code>\n"
                        f"📍 Base Price: <code>${base:,.2f}</code>\n"
                        f"🎯 First alerts at:\n"
                        f"   ↑ <code>${base + interval:,.2f}</code>\n"
                        f"   ↓ <code>${base - interval:,.2f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Use /stoppricealert to stop.",
                        "parse_mode": "HTML"},
                    timeout=10
                )
            except ValueError:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                    json={"chat_id": chat_id,
                          "text": "❌ Invalid interval. Please send a number, e.g. <code>500</code>",
                          "parse_mode": "HTML"},
                    timeout=10
                )

    st.session_state["tg_last_update_id"] = new_last_id

    # ==========================================
    # PRICE INTERVAL ALERT CHECK (BTC or ETH)
    # ==========================================
    if not st.session_state.get("price_alert_active"):
        return

    interval = st.session_state.get("price_alert_interval", 0)
    last_level = st.session_state.get("price_alert_last_level", 0)
    alert_sym = st.session_state.get("price_alert_symbol", "BTC")

    if interval <= 0:
        return

    try:
        fresh = _do_fetch(alert_sym)
        live_cp = fresh["price"] if fresh and fresh.get("price", 0) > 0 else 0
    except Exception:
        return

    if live_cp <= 0:
        return

    current_level = round(live_cp / interval) * interval

    if last_level == 0:
        st.session_state["price_alert_last_level"] = current_level
        return

    if current_level != last_level:
        direction = "UP" if current_level > last_level else "DOWN"
        levels_crossed = abs(int(round((current_level - last_level) / interval)))
        rounded_price = round(live_cp / 100) * 100

        alert_msg = f"<b>{alert_sym} {direction} — ${rounded_price:,.0f}</b>\n"
        alert_msg += f"Interval: <code>${interval:,.0f}</code>"
        if levels_crossed > 1:
            alert_msg += f"\nSkipped {levels_crossed - 1} level(s)"

        alert_chat = st.session_state.get("price_alert_setup_chat", "")
        if alert_chat:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN_UI}/sendMessage",
                json={"chat_id": alert_chat, "text": alert_msg, "parse_mode": "HTML"},
                timeout=10
            )

        st.session_state["price_alert_last_level"] = current_level

# ==========================================
# LIVE DASHBOARD FRAGMENT
# ==========================================

@st.fragment(run_every=30)
def live_dashboard(orders):
    # Fetch BTC and ETH
    result_btc = _do_fetch('BTC')
    if result_btc:
        st.session_state["price_cache"] = result_btc

    result_eth = _do_fetch('ETH')
    if result_eth:
        st.session_state["price_cache_eth"] = result_eth

    price_data = st.session_state.get("price_cache",
        {"price": 0, "change_pct": 0, "high": 0, "low": 0, "ok": False, "source": "none"})
    eth_data = st.session_state.get("price_cache_eth",
        {"price": 0, "change_pct": 0, "high": 0, "low": 0, "ok": False, "source": "none"})

    cp = price_data["price"]
    eth_cp = eth_data["price"]

    # ==========================================
    # STOP-ORDER TRIGGER CHECK (partial close)
    # ==========================================
    stop_orders = load_stop_orders()
    if stop_orders:
        so_triggered = []
        so_remaining = []
        for so in stop_orders:
            sym = so.get("target_symbol", "BTC")
            price = eth_cp if sym == "ETH" else cp
            direction = so.get("trigger_direction", "at_or_below")
            trigger_price = so.get("trigger_price", 0)

            if price <= 0 or trigger_price <= 0:
                so_remaining.append(so)
                continue

            hit = (direction == "at_or_below" and price <= trigger_price) or \
                  (direction == "at_or_above" and price >= trigger_price)

            if hit:
                so_triggered.append(so)
            else:
                so_remaining.append(so)

        if so_triggered:
            TG_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
            TG_CHATS = [c for c in [
                st.secrets.get("TELEGRAM_CHAT_ID", ""),
                st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
            ] if c]

            for so in so_triggered:
                sym = so.get("target_symbol", "BTC")
                price = eth_cp if sym == "ETH" else cp

                # Find matching running order (snapshot match)
                match_idx = None
                for idx, o in enumerate(orders):
                    if (o["account"] == so["target_account"] and
                        o.get("symbol", "BTC") == sym and
                        o["side"] == so["target_side"]):
                        match_idx = idx
                        break

                if match_idx is None:
                    # Position no longer exists — skip silently, don't re-add to remaining
                    st.toast(f"⚠️ Stop-order target position no longer found — skipped", icon="⚠️")
                    continue

                target_pos = orders[match_idx]
                close_qty = so.get("qty", 0)
                remaining_qty = (target_pos.get("qty", 0) or 0) - close_qty

                # Calculate realized P&L for the partial close
                entry = target_pos.get("entry_price", 0)
                side = target_pos["side"]
                if side == "Buy":
                    realized_usd = (price - entry) * close_qty
                else:
                    realized_usd = (entry - price) * close_qty
                realized_inr = realized_usd * USD_TO_INR

                closed_lots = qty_to_lots(close_qty, sym)

                if remaining_qty <= 0.0000001:
                    # Fully closed
                    orders.pop(match_idx)
                    close_note = "Position fully closed."
                else:
                    orders[match_idx]["qty"] = remaining_qty
                    remaining_lots = qty_to_lots(remaining_qty, sym)
                    close_note = f"Remaining: {remaining_lots} lots @ ${entry:,.2f}"

                # Telegram notification
                if TG_TOKEN and TG_CHATS:
                    pnl_sign = "+" if realized_inr >= 0 else ""
                    msg = (
                        f"🛑 <b>STOP-ORDER TRIGGERED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"<b>{so['target_account']}</b> [{sym}] {side.upper()}\n"
                        f"Closed: <code>{closed_lots} lots</code> @ <code>${price:,.2f}</code>\n"
                        f"Realized P&L: <code>{pnl_sign}₹{realized_inr:,.0f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{close_note}"
                    )
                    for cid in TG_CHATS:
                        requests.post(
                            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                            json={"chat_id": cid, "text": msg, "parse_mode": "HTML"},
                            timeout=10
                        )

                st.toast(f"🛑 {so['target_account']} [{sym}] stop-order hit — {closed_lots} lots closed", icon="🛑")

            save_orders(orders)
            save_stop_orders(so_remaining)
            st.rerun()

    # ==========================================
    # PRE-ORDER TRIGGER CHECK (fixed / pyramid)
    # ==========================================
    pre_orders = load_pre_orders()
    if pre_orders:
        po_triggered = []
        po_remaining = []
        for po in pre_orders:
            sym = po.get("symbol", "BTC")
            price = eth_cp if sym == "ETH" else cp
            side = po.get("side", "Buy")
            target = po.get("target_entry_price", 0)

            if price <= 0 or target <= 0:
                po_remaining.append(po)
                continue

            hit = (side == "Buy" and price >= target) or (side == "Sell" and price <= target)

            if hit:
                po_triggered.append(po)
            else:
                po_remaining.append(po)

        if po_triggered:
            TG_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
            TG_CHATS = [c for c in [
                st.secrets.get("TELEGRAM_CHAT_ID", ""),
                st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
            ] if c]

            for po in po_triggered:
                sym = po.get("symbol", "BTC")
                price = eth_cp if sym == "ETH" else cp
                side = po.get("side", "Buy")
                new_qty = po.get("qty", 0)
                new_entry = po["target_entry_price"]
                lots = qty_to_lots(new_qty, sym)

                # Check for existing matching running position (account+symbol+side)
                match_idx = None
                for idx, o in enumerate(orders):
                    if (o["account"] == po["account"] and
                        o.get("symbol", "BTC") == sym and
                        o["side"] == side):
                        match_idx = idx
                        break

                if match_idx is not None:
                    # PYRAMID — weighted average entry
                    existing = orders[match_idx]
                    ex_qty = existing.get("qty", 0) or 0
                    ex_entry = existing.get("entry_price", 0) or 0

                    total_qty = ex_qty + new_qty
                    avg_entry = ((ex_qty * ex_entry) + (new_qty * new_entry)) / total_qty if total_qty > 0 else new_entry

                    orders[match_idx]["qty"] = total_qty
                    orders[match_idx]["entry_price"] = round(avg_entry, 2)
                    # Keep existing liq/tg/sl unless pre-order specifies new ones
                    if po.get("liquidation"):
                        orders[match_idx]["liquidation"] = po["liquidation"]
                    if po.get("target"):
                        orders[match_idx]["target"] = po["target"]
                    if po.get("stop_loss"):
                        orders[match_idx]["stop_loss"] = po["stop_loss"]

                    total_lots = qty_to_lots(total_qty, sym)
                    mode_note = f"PYRAMID — new avg entry ${avg_entry:,.2f}, total {total_lots} lots"
                else:
                    # FIXED — new position
                    new_order = {
                        "account": po["account"],
                        "symbol": sym,
                        "side": side,
                        "entry_price": new_entry,
                        "qty": new_qty,
                        "liquidation": po.get("liquidation"),
                        "target": po.get("target"),
                        "stop_loss": po.get("stop_loss"),
                        "alert_threshold": po.get("alert_threshold", 3.0),
                        "added_at": str(datetime.datetime.now()),
                    }
                    orders.append(new_order)
                    mode_note = f"FIXED — new position opened, {lots} lots"

                # Telegram notification
                if TG_TOKEN and TG_CHATS:
                    msg = (
                        f"🟢 <b>PRE-ORDER TRIGGERED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"<b>{po['account']}</b> [{sym}] {side.upper()}\n"
                        f"Trigger Entry: <code>${new_entry:,.2f}</code>\n"
                        f"Current Price: <code>${price:,.2f}</code>\n"
                        f"Qty Added: <code>{lots} lots</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{mode_note}"
                    )
                    for cid in TG_CHATS:
                        requests.post(
                            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                            json={"chat_id": cid, "text": msg, "parse_mode": "HTML"},
                            timeout=10
                        )

                st.toast(f"🟢 {po['account']} [{sym}] pre-order triggered!", icon="✅")

            save_orders(orders)
            save_pre_orders(po_remaining)
            st.rerun()

    # ==========================================
    # PRICE BAR — BTC and ETH side by side
    # ==========================================

    col_btc, col_eth, col_refresh = st.columns([5, 5, 1])

    with col_btc:
        btc_color = "price-up" if price_data["change_pct"] >= 0 else "price-down"
        btc_arrow = "▲" if price_data["change_pct"] >= 0 else "▼"
        chg_color = color_val(price_data["change_pct"])
        st.markdown(
            f'<div class="price-display {btc_color}">BTC ${cp:,.1f}</div>'
            f'<div style="display:flex;gap:20px;margin-top:4px">'
            f'<span><span class="stat-label">CHANGE </span><span style="{chg_color};font-weight:700">{btc_arrow} {abs(price_data["change_pct"]):.2f}%</span></span>'
            f'<span><span class="stat-label">HIGH </span><span style="font-weight:700">${price_data["high"]:,.1f}</span></span>'
            f'<span><span class="stat-label">LOW </span><span style="font-weight:700">${price_data["low"]:,.1f}</span></span>'
            f'</div>',
            unsafe_allow_html=True
        )

    with col_eth:
        if eth_data.get("ok"):
            eth_color = "price-up" if eth_data["change_pct"] >= 0 else "price-down"
            eth_arrow = "▲" if eth_data["change_pct"] >= 0 else "▼"
            eth_chg_color = color_val(eth_data["change_pct"])
            st.markdown(
                f'<div class="price-display {eth_color}">ETH ${eth_cp:,.2f}</div>'
                f'<div style="display:flex;gap:20px;margin-top:4px">'
                f'<span><span class="stat-label">CHANGE </span><span style="{eth_chg_color};font-weight:700">{eth_arrow} {abs(eth_data["change_pct"]):.2f}%</span></span>'
                f'<span><span class="stat-label">HIGH </span><span style="font-weight:700">${eth_data["high"]:,.2f}</span></span>'
                f'<span><span class="stat-label">LOW </span><span style="font-weight:700">${eth_data["low"]:,.2f}</span></span>'
                f'</div>',
                unsafe_allow_html=True
            )

    with col_refresh:
        st.markdown("<div style='margin-top:8px'>", unsafe_allow_html=True)
        if st.button("🔄", help="Force refresh prices"):
            st.session_state.pop("price_cache", None)
            st.session_state.pop("price_cache_eth", None)
            st.rerun(scope="fragment")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ==========================================
    # ACTION BUTTONS — all in one row
    # ==========================================

    btn1, btn2, btn3, btn4 = st.columns([2, 2, 2, 2])
    with btn1:
        send_report_btc = st.button("📊 Send Report BTC", help="Send instant BTC portfolio report to Telegram", use_container_width=True)
    with btn2:
        send_report_eth = st.button("📊 Send Report ETH", help="Send instant ETH portfolio report to Telegram", use_container_width=True)
    with btn3:
        send_btc = st.button("📈 BTC Chart", help="Send BTC candlestick chart", use_container_width=True)
    with btn4:
        send_eth = st.button("📈 ETH Chart", help="Send ETH candlestick chart", use_container_width=True)

    st.caption(f"BTC: {price_data.get('source','—')} · ETH: {eth_data.get('source','—')} · {datetime.datetime.now().strftime('%H:%M:%S')}")
    st.markdown("---")

    # Telegram credentials
    TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_IDS_UI = [c for c in [
        st.secrets.get("TELEGRAM_CHAT_ID", ""),
        st.secrets.get("TELEGRAM_CHAT_ID_2", ""),
    ] if c]

    # Send Report button
    if send_report_btc or send_report_eth:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS_UI:
            st.warning("Telegram not configured in secrets.")
        elif not orders:
            st.info("No open positions to report.")
        else:
            fresh_btc = _do_fetch('BTC')
            fresh_eth = _do_fetch('ETH')
            report_cp = fresh_btc["price"] if fresh_btc else cp
            report_eth_cp = fresh_eth["price"] if fresh_eth else eth_cp

            # ← Compute idle accounts BEFORE the loop, filtered by symbol
            ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
            active_accounts_btc = {o.get("account") for o in orders if o.get("symbol", "BTC") == "BTC"}
            active_accounts_eth = {o.get("account") for o in orders if o.get("symbol") == "ETH"}
            inactive_accounts_btc = [a for a in ALL_ACCOUNTS if a not in active_accounts_btc]
            inactive_accounts_eth = [a for a in ALL_ACCOUNTS if a not in active_accounts_eth]

            # Calculate per-symbol totals
            btc_pnls = []
            eth_pnls = []
            btc_profit = btc_loss = btc_tp = btc_tl = btc_net = btc_net_usd = 0
            eth_profit = eth_loss = eth_tp = eth_tl = eth_net = eth_net_usd = 0
            buy_qty_btc = sell_qty_btc = buy_qty_eth = sell_qty_eth = 0

            for o in orders:
                sym = o.get("symbol", "BTC")
                price = report_eth_cp if sym == "ETH" else report_cp
                running_usd = (price - o.get("entry_price", 0)) * o.get("qty", 0) if o.get("side") == "Buy" else (o.get("entry_price", 0) - price) * o.get("qty", 0)
                running_inr = running_usd * USD_TO_INR
                qty = o.get("qty", 0) or 0
                lots = qty_to_lots(qty, sym)
                side_emoji = "🟢" if o.get("side") == "Buy" else "🔴"
                pnl_sign = "+" if running_inr >= 0 else ""
                line = (
                    f"  {side_emoji} <b>{o.get('account')}</b> "
                    f"@ ${o.get('entry_price', 0):,.2f} | {lots} lots "
                    f"→ <code>{pnl_sign}₹{running_inr:,.0f}</code>"
                )
                if sym == "BTC":
                    btc_pnls.append((running_inr, running_usd, line))
                    btc_net += running_inr
                    btc_net_usd += running_usd
                    if running_inr > 0: btc_profit += 1; btc_tp += running_inr
                    elif running_inr < 0: btc_loss += 1; btc_tl += running_inr
                    if o.get("side") == "Buy": buy_qty_btc += qty
                    else: sell_qty_btc += qty
                else:
                    eth_pnls.append((running_inr, running_usd, line))
                    eth_net += running_inr
                    eth_net_usd += running_usd
                    if running_inr > 0: eth_profit += 1; eth_tp += running_inr
                    elif running_inr < 0: eth_loss += 1; eth_tl += running_inr
                    if o.get("side") == "Buy": buy_qty_eth += qty
                    else: sell_qty_eth += qty

            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

            if send_report_btc and btc_pnls:
                btc_pnls.sort(key=lambda x: x[0], reverse=True)
                btc_sign = "+" if btc_net >= 0 else ""
                msg_btc = (
                    f"₿ <b>BTC Report</b>  <code>${report_cp:,.1f}</code>\n"
                    f"P: {btc_profit} | <code>+₹{btc_tp:,.0f}</code>\n"
                    f"L: {btc_loss} | <code>₹{btc_tl:,.0f}</code>\n"
                    f"<b>T</b>: <code>{btc_sign}₹{btc_net:,.0f}</code> (<code>{btc_sign}${btc_net_usd:,.2f}</code>)\n"
                    f"BQ: {btc_to_lots(buy_qty_btc)}L | SQ: {btc_to_lots(sell_qty_btc)}L\n\n"
                )
                msg_btc += "\n".join(l for _, _, l in btc_pnls)
                msg_btc += (
                    f"\n\nTotal: {len(btc_pnls)}\n"
                    f"Idle ({len(inactive_accounts_btc)}): {', '.join(inactive_accounts_btc) if inactive_accounts_btc else 'None'}"
                )
                all_ok = True
                for cid in TELEGRAM_CHAT_IDS_UI:
                    r = requests.post(url, json={"chat_id": cid, "text": msg_btc, "parse_mode": "HTML"}, timeout=10)
                    if not r.ok: all_ok = False
                if all_ok: st.success("✅ BTC report sent!")
                else: st.error("❌ Failed to send BTC report.")

            if send_report_eth and eth_pnls:
                eth_pnls.sort(key=lambda x: x[0], reverse=True)
                eth_sign = "+" if eth_net >= 0 else ""
                msg_eth = (
                    f"Ξ <b>ETH Report</b>  <code>${report_eth_cp:,.2f}</code>\n"
                    f"P: {eth_profit} | <code>+₹{eth_tp:,.0f}</code>\n"
                    f"L: {eth_loss} | <code>₹{eth_tl:,.0f}</code>\n"
                    f"<b>T</b>: <code>{eth_sign}₹{eth_net:,.0f}</code> (<code>{eth_sign}${eth_net_usd:,.2f}</code>)\n"
                    f"BQ: {qty_to_lots(buy_qty_eth,'ETH')}L | SQ: {qty_to_lots(sell_qty_eth,'ETH')}L\n\n"
                )
                msg_eth += "\n".join(l for _, _, l in eth_pnls)
                msg_eth += (
                    f"\n\nTotal: {len(eth_pnls)}\n"
                    f"Idle ({len(inactive_accounts_eth)}): {', '.join(inactive_accounts_eth) if inactive_accounts_eth else 'None'}"
                )
                all_ok = True
                for cid in TELEGRAM_CHAT_IDS_UI:
                    r = requests.post(url, json={"chat_id": cid, "text": msg_eth, "parse_mode": "HTML"}, timeout=10)
                    if not r.ok: all_ok = False
                if all_ok: st.success("✅ ETH report sent!")
                else: st.error("❌ Failed to send ETH report.")

            elif send_report_eth and not eth_pnls:
                st.info("No ETH positions to report.")

    # Chart buttons
    if send_btc:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS_UI:
            st.warning("Telegram not configured.")
        else:
            send_chart_telegram("BTC", TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS_UI)

    if send_eth:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS_UI:
            st.warning("Telegram not configured.")
        else:
            send_chart_telegram("ETH", TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS_UI)

    if not orders:
        st.info("👋 No open positions. Add one below.")
        return

    # Use correct price per order
    calcs = [calculate(o, get_order_cp(o)) for o in orders]

    # Danger alerts
    danger_orders = [
        (o, c) for o, c in zip(orders, calcs)
        if c["danger_pct"] is not None and c["danger_pct"] >= 70
    ]
    if danger_orders:
        for o, c in danger_orders:
            sym = o.get("symbol", "BTC")
            price_cp = eth_cp if sym == "ETH" else cp
            st.markdown(f"""
            <div class="danger-zone">
                🚨 <b>{o['account']}</b> [{sym}] ({o['side']}) is <b>{c['danger_pct']:.0f}%</b> toward liquidation!
                Current: ${price_cp:,.2f} | Liq: ${o['liquidation']:,.1f} | Distance: ${abs(c['liq_danger']):,.1f}
            </div>
            """, unsafe_allow_html=True)

    # ==========================================
    # SUMMARY
    # ==========================================

    # Calculate all values
    total_inr = sum(c["running_inr"] for c in calcs)
    total_usd = sum(c["running_usd"] for c in calcs)

    btc_orders = [(o, c) for o, c in zip(orders, calcs) if o.get("symbol", "BTC") == "BTC"]
    eth_orders = [(o, c) for o, c in zip(orders, calcs) if o.get("symbol") == "ETH"]

    def calc_summary(pairs):
        profit_count = sum(1 for _, c in pairs if c["running_inr"] > 0)
        loss_count = sum(1 for _, c in pairs if c["running_inr"] < 0)
        total_profit = sum(c["running_inr"] for _, c in pairs if c["running_inr"] > 0)
        total_loss = sum(c["running_inr"] for _, c in pairs if c["running_inr"] < 0)
        net_inr = sum(c["running_inr"] for _, c in pairs)
        net_usd = sum(c["running_usd"] for _, c in pairs)
        buy_qty = sum(o.get("qty", 0) or 0 for o, _ in pairs if o.get("side") == "Buy")
        sell_qty = sum(o.get("qty", 0) or 0 for o, _ in pairs if o.get("side") == "Sell")
        return profit_count, loss_count, total_profit, total_loss, net_inr, net_usd, buy_qty, sell_qty

    btc_p, btc_l, btc_tp, btc_tl, btc_net_inr, btc_net_usd, btc_bq, btc_sq = calc_summary(btc_orders)
    eth_p, eth_l, eth_tp, eth_tl, eth_net_inr, eth_net_usd, eth_bq, eth_sq = calc_summary(eth_orders)

    net_color = "#00e676" if total_inr >= 0 else "#ff1744"
    btc_net_color = "#00e676" if btc_net_inr >= 0 else "#ff1744"
    eth_net_color = "#00e676" if eth_net_inr >= 0 else "#ff1744"
    ts = "+" if total_inr >= 0 else ""

    st.subheader("📊 Summary", anchor="summary")

    # Row 1 — Overall
    st.markdown("##### Overall")
    r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)
    with r1c1:
        st.markdown(summary_box(
            "Net Running P&L",
            f"{fmt_inr(total_inr)}<br><small style='font-size:11px;opacity:0.7'>{fmt_usd(total_usd)}</small>",
            net_color
        ), unsafe_allow_html=True)
    with r1c2:
        st.markdown(summary_box(
            "Profit Positions",
            f"{sum(1 for c in calcs if c['running_inr'] > 0)}<br><small style='font-size:11px;color:#00e676'>+₹{sum(c['running_inr'] for c in calcs if c['running_inr'] > 0):,.0f}</small>"
        ), unsafe_allow_html=True)
    with r1c3:
        st.markdown(summary_box(
            "Loss Positions",
            f"{sum(1 for c in calcs if c['running_inr'] < 0)}<br><small style='font-size:11px;color:#ff1744'>₹{sum(c['running_inr'] for c in calcs if c['running_inr'] < 0):,.0f}</small>"
        ), unsafe_allow_html=True)
    with r1c4:
        st.markdown(summary_box("Total Positions", len(orders)), unsafe_allow_html=True)
    with r1c5:
        buy_count = btc_to_lots(btc_bq) + qty_to_lots(eth_bq, 'ETH')
        sell_count = btc_to_lots(btc_sq) + qty_to_lots(eth_sq, 'ETH')
        st.markdown(summary_box(
            "Overall Buy/Sell Qty",
            f"Buy: {buy_count}L \n Sell: {sell_count}L"
        ), unsafe_allow_html=True)

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # Row 2 — BTC
    if btc_orders:
        st.markdown("##### ₿ BTC")
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        with b1:
            st.markdown(summary_box(
                "BTC Net P&L",
                f"{fmt_inr(btc_net_inr)}<br><small style='font-size:11px;opacity:0.7'>{fmt_usd(btc_net_usd)}</small>",
                btc_net_color
            ), unsafe_allow_html=True)
        with b2:
            st.markdown(summary_box(
                "BTC Profit",
                f"{btc_p} pos<br><small style='font-size:11px;color:#00e676'>+₹{btc_tp:,.0f}</small>"
            ), unsafe_allow_html=True)
        with b3:
            st.markdown(summary_box(
                "BTC Loss",
                f"{btc_l} pos<br><small style='font-size:11px;color:#ff1744'>₹{btc_tl:,.0f}</small>"
            ), unsafe_allow_html=True)
        with b4:
            st.markdown(summary_box("BTC Positions", len(btc_orders)), unsafe_allow_html=True)
        with b5:
            st.markdown(summary_box(
                "BTC Buy Lots",
                f"{btc_to_lots(btc_bq)}L",
                "#00e676"
            ), unsafe_allow_html=True)
        with b6:
            st.markdown(summary_box(
                "BTC Sell Lots",
                f"{btc_to_lots(btc_sq)}L",
                "#ff1744"
            ), unsafe_allow_html=True)

        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # Row 3 — ETH
    if eth_orders:
        st.markdown("##### Ξ ETH")
        e1, e2, e3, e4, e5, e6 = st.columns(6)
        with e1:
            st.markdown(summary_box(
                "ETH Net P&L",
                f"{fmt_inr(eth_net_inr)}<br><small style='font-size:11px;opacity:0.7'>{fmt_usd(eth_net_usd)}</small>",
                eth_net_color
            ), unsafe_allow_html=True)
        with e2:
            st.markdown(summary_box(
                "ETH Profit",
                f"{eth_p} pos<br><small style='font-size:11px;color:#00e676'>+₹{eth_tp:,.0f}</small>"
            ), unsafe_allow_html=True)
        with e3:
            st.markdown(summary_box(
                "ETH Loss",
                f"{eth_l} pos<br><small style='font-size:11px;color:#ff1744'>₹{eth_tl:,.0f}</small>"
            ), unsafe_allow_html=True)
        with e4:
            st.markdown(summary_box("ETH Positions", len(eth_orders)), unsafe_allow_html=True)
        with e5:
            st.markdown(summary_box(
                "ETH Buy Lots",
                f"{qty_to_lots(eth_bq, 'ETH')}L",
                "#00e676"
            ), unsafe_allow_html=True)
        with e6:
            st.markdown(summary_box(
                "ETH Sell Lots",
                f"{qty_to_lots(eth_sq, 'ETH')}L",
                "#ff1744"
            ), unsafe_allow_html=True)

    st.markdown("---")

    # Analysis table
    st.subheader("📋 Position Analysis", anchor="position-analysis")
    sorted_pairs = sorted(zip(orders, calcs), key=lambda x: x[1]["running_inr"])
    table_rows = []
    for o, c in sorted_pairs:
        danger_str = f"{c['danger_pct']:.0f}% to Liq" if c["danger_pct"] is not None else "—"
        sym = o.get("symbol", "BTC")
        table_rows.append({
            "Account": o["account"],
            "Symbol": sym,
            "Exchange": ACCOUNT_GROUP.get(o["account"], "—"),
            "Side": o["side"],
            "Entry": fmt_price(o.get("entry_price")),
            "Qty (Lots)": qty_to_lots(o.get("qty", 0) or 0, sym),
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
    
    # ==========================================
    # CROSS-PAIR HEDGE ANALYSIS
    # Shows accounts with opposite BTC/ETH positions
    # ==========================================

    # Build per-account position map
    account_positions = {}
    for o, c in zip(orders, calcs):
        acc = o["account"]
        sym = o.get("symbol", "BTC")
        if acc not in account_positions:
            account_positions[acc] = {}
        if sym not in account_positions[acc]:
            account_positions[acc][sym] = []
        account_positions[acc][sym].append((o, c))

    # Find accounts with BTC+ETH and opposite sides
    hedge_accounts = []
    for acc, syms in account_positions.items():
        if "BTC" not in syms or "ETH" not in syms:
            continue
        btc_sides = {o["side"] for o, _ in syms["BTC"]}
        eth_sides = {o["side"] for o, _ in syms["ETH"]}
        # Opposite if BTC has Buy and ETH has Sell, or BTC has Sell and ETH has Buy
        is_hedge = (
            ("Buy" in btc_sides and "Sell" in eth_sides) or
            ("Sell" in btc_sides and "Buy" in eth_sides) or 
            ("Buy" in btc_sides and "Buy" in eth_sides) or 
            ("Sell" in btc_sides and "Sell" in eth_sides)
        )
        if is_hedge:
            hedge_accounts.append(acc)

    if hedge_accounts:
        st.subheader("🔀 Cross-Pair Hedge", anchor="cross-pair-hedge")
        st.caption("Accounts with opposite BTC/ETH positions — combined running P&L.")

        for acc in sorted(hedge_accounts):
            btc_pairs = account_positions[acc]["BTC"]
            eth_pairs = account_positions[acc]["ETH"]
            exchange = ACCOUNT_GROUP.get(acc, "?")

            btc_inr = sum(c["running_inr"] for _, c in btc_pairs)
            btc_usd = sum(c["running_usd"] for _, c in btc_pairs)
            eth_inr = sum(c["running_inr"] for _, c in eth_pairs)
            eth_usd = sum(c["running_usd"] for _, c in eth_pairs)
            net_inr = btc_inr + eth_inr
            net_usd = btc_usd + eth_usd

            net_color = "#00e676" if net_inr >= 0 else "#ff1744"
            btc_color = "#00e676" if btc_inr >= 0 else "#ff1744"
            eth_color = "#00e676" if eth_inr >= 0 else "#ff1744"
            net_sign = "+" if net_inr >= 0 else ""
            btc_sign = "+" if btc_inr >= 0 else ""
            eth_sign = "+" if eth_inr >= 0 else ""

            # Build position lines for BTC
            btc_lines = []
            for o, c in btc_pairs:
                arrow_color = "#00c853" if o["side"] == "Buy" else "#ff1744"
                side_arrow = "↑" if o["side"] == "Buy" else "↓"
                lots = qty_to_lots(o.get("qty", 0) or 0, "BTC")
                pnl_s = "+" if c["running_inr"] >= 0 else ""
                btc_lines.append(
                    f"<span style='color:{arrow_color};font-weight:700'>{side_arrow}</span> "
                    f"${o.get('entry_price',0):,.1f} · {lots}L · "
                    f"<span style='color:{'#00e676' if c['running_inr']>=0 else '#ff1744'}'>"
                    f"₹{pnl_s}{c['running_inr']:,.0f}</span>"
                )

            # Build position lines for ETH
            eth_lines = []
            for o, c in eth_pairs:
                arrow_color = "#00c853" if o["side"] == "Buy" else "#ff1744"
                side_arrow = "↑" if o["side"] == "Buy" else "↓"
                lots = qty_to_lots(o.get("qty", 0) or 0, "ETH")
                pnl_s = "+" if c["running_inr"] >= 0 else ""
                eth_lines.append(
                    f"<span style='color:{arrow_color};font-weight:700'>{side_arrow}</span> "
                    f"${o.get('entry_price',0):,.1f} · {lots}L · "
                    f"<span style='color:{'#00e676' if c['running_inr']>=0 else '#ff1744'}'>"
                    f"₹{pnl_s}{c['running_inr']:,.0f}</span>"
                )

            st.markdown(f"""
            <div style="background:var(--secondary-background-color);
                        border:1px solid rgba(128,128,128,0.2);
                        border-radius:12px;padding:16px;margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                    <div>
                        <span style="font-size:16px;font-weight:700">{acc}</span>
                        <span style="font-size:12px;color:#888;margin-left:8px">{exchange}</span>
                    </div>
                    <div style="text-align:right">
                        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Net Combined P&L</div>
                        <div style="font-size:16px;font-weight:800;font-family:monospace;color:{net_color}">
                            ₹{net_sign}{net_inr:,.0f}
                        </div>
                        <div style="font-size:11px;color:#888">${net_sign}{net_usd:,.2f}</div>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">₿ BTC</div>
                        <div style="font-size:12px;font-family:monospace;margin-bottom:6px">
                            {'<br>'.join(btc_lines)}
                        </div>
                        <div style="font-size:12px;font-weight:700;color:{btc_color};font-family:monospace;border-top:1px solid rgba(128,128,128,0.15);padding-top:6px;margin-top:4px">
                            Total: ${btc_sign}{btc_usd:,.0f}
                        </div>
                    </div>
                    <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Ξ ETH</div>
                        <div style="font-size:12px;font-family:monospace;margin-bottom:6px">
                            {'<br>'.join(eth_lines)}
                        </div>
                        <div style="font-size:12px;font-weight:700;color:{eth_color};font-family:monospace;border-top:1px solid rgba(128,128,128,0.15);padding-top:6px;margin-top:4px">
                            Total: ${eth_sign}{eth_usd:,.0f}
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
    # st.markdown("---")

    st.session_state["current_cp"] = cp
    st.session_state["current_eth_cp"] = eth_cp

# ==========================================
# MAIN PAGE
# ==========================================

st.title("⚡ Live Order Monitor")

orders = load_orders()
pre_orders = load_pre_orders()
stop_orders = load_stop_orders()

# Quick-nav bar — jump to any section on the page
render_quick_nav(orders, pre_orders, stop_orders)

# Price interval alert state
for key, default in [
    ("price_alert_active", False),
    ("price_alert_interval", 0),
    ("price_alert_base", 0),
    ("price_alert_last_level", 0),
    ("price_alert_symbol", "BTC"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

telegram_command_listener(orders, st.session_state.get("current_cp", 0))
live_dashboard(orders)

cp = st.session_state.get("current_cp", 0)
eth_cp = st.session_state.get("current_eth_cp", 0)

btn_add1, btn_add2, btn_add3 = st.columns(3)
with btn_add1:
    if st.button("➕ Add New Position", use_container_width=True):
        dialog_add_position(orders)
with btn_add2:
    if st.button("⏳ Add Pre-Order", use_container_width=True):
        dialog_add_pre_order(pre_orders, orders)
with btn_add3:
    if st.button("🛑 Add Stop-Order", use_container_width=True):
        dialog_add_stop_order(orders, stop_orders)

# ==========================================
# PRE-ORDERS SECTION
# ==========================================
if pre_orders:
    st.subheader("⏳ Pending Pre-Orders", anchor="pre-orders")
    for i, po in enumerate(pre_orders):
        sym = po.get("symbol", "BTC")
        side = po.get("side", "Buy")
        target = po.get("target_entry_price", 0)
        lots = qty_to_lots(po.get("qty", 0) or 0, sym)
        exchange = ACCOUNT_GROUP.get(po["account"], "?")
        side_color = "#00c853" if side == "Buy" else "#ff1744"
        side_arrow = "↑" if side == "Buy" else "↓"

        # Determine current mode
        will_pyramid = any(
            o["account"] == po["account"] and o.get("symbol", "BTC") == sym and o["side"] == side
            for o in orders
        )
        mode_label = "📐 PYRAMID" if will_pyramid else "🆕 FIXED"

        curr_price = st.session_state.get("current_eth_cp", 0) if sym == "ETH" else st.session_state.get("current_cp", 0)
        dist_str = f"${abs(curr_price - target):,.2f} away" if curr_price > 0 else "—"

        pc1, pc2, pc3 = st.columns([9, 1, 1])
        with pc1:
            st.markdown(f"""
            <div style="background:var(--secondary-background-color);
                        border:1px solid rgba(128,128,128,0.15);
                        border-left: 3px solid {side_color};
                        border-radius:8px;padding:12px 16px;
                        display:flex;justify-content:space-between;align-items:center">
                <div>
                    <span style="font-weight:700">{po['account']}</span>
                    <span style="color:#888;font-size:12px;margin-left:6px">({exchange})</span>
                    <span style="color:{side_color};font-weight:700;margin-left:10px">{side_arrow} {side.upper()}</span>
                    <span style="color:#888;font-size:12px;margin-left:6px">[{sym}]</span>
                    <span style="font-size:11px;margin-left:10px;opacity:0.8">{mode_label}</span>
                </div>
                <div style="text-align:right">
                    <div style="font-size:16px;font-weight:700;font-family:monospace">@ ${target:,.2f}</div>
                    <div style="font-size:12px;color:#888">{lots} lots · {dist_str}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with pc2:
            if st.button("✏️", key=f"edit_pre_{i}", help="Edit pre-order"):
                dialog_edit_pre_order(pre_orders, i, orders)
        with pc3:
            if st.button("✕", key=f"del_pre_{i}", help="Cancel pre-order"):
                pre_orders.pop(i)
                save_pre_orders(pre_orders)
                st.rerun()

    st.markdown("---")

# ==========================================
# STOP-ORDERS SECTION
# ==========================================
if stop_orders:
    st.subheader("🛑 Pending Stop-Orders", anchor="stop-orders")
    for i, so in enumerate(stop_orders):
        sym = so.get("target_symbol", "BTC")
        lots = qty_to_lots(so.get("qty", 0) or 0, sym)
        exchange = ACCOUNT_GROUP.get(so["target_account"], "?")
        direction_label = "≤" if so.get("trigger_direction") == "at_or_below" else "≥"

        curr_price = st.session_state.get("current_eth_cp", 0) if sym == "ETH" else st.session_state.get("current_cp", 0)
        dist_str = f"${abs(curr_price - so['trigger_price']):,.2f} away" if curr_price > 0 else "—"

        pc1, pc2, pc3 = st.columns([9, 1, 1])
        with pc1:
            st.markdown(f"""
            <div style="background:var(--secondary-background-color);
                        border:1px solid rgba(128,128,128,0.15);
                        border-left: 3px solid #ffa726;
                        border-radius:8px;padding:12px 16px;
                        display:flex;justify-content:space-between;align-items:center">
                <div>
                    <span style="font-weight:700">{so['target_account']}</span>
                    <span style="color:#888;font-size:12px;margin-left:6px">({exchange})</span>
                    <span style="color:#ffa726;font-weight:700;margin-left:10px">{so['target_side'].upper()}</span>
                    <span style="color:#888;font-size:12px;margin-left:6px">[{sym}]</span>
                </div>
                <div style="text-align:right">
                    <div style="font-size:16px;font-weight:700;font-family:monospace">
                        Price {direction_label} ${so['trigger_price']:,.2f}
                    </div>
                    <div style="font-size:12px;color:#888">close {lots} lots · {dist_str}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with pc2:
            if st.button("✏️", key=f"edit_so_{i}", help="Edit stop-order"):
                dialog_edit_stop_order(stop_orders, i, orders)
        with pc3:
            if st.button("✕", key=f"del_so_{i}", help="Cancel stop-order"):
                stop_orders.pop(i)
                save_stop_orders(stop_orders)
                st.rerun()

    st.markdown("---")

# ==========================================
# POSITION CARDS
# ==========================================

if orders:
    st.subheader("🗂️ Position Cards", anchor="position-cards")

    # Filters row
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        filter_sym = st.selectbox("Filter Symbol", ["All", "BTC", "ETH"])
    with filter_col2:
        filter_side = st.selectbox("Filter Side", ["All", "Buy", "Sell"])
    with filter_col3:
        filter_acc = st.multiselect("Filter Account", ACCOUNTS, default=[])
    with filter_col4:
        filter_danger = st.checkbox("⚠️ Danger only (≥70% to Liq)")

    def get_card_cp(o):
        sym = o.get("symbol", "BTC")
        return eth_cp if sym == "ETH" else cp

    filtered = [
        (o, calculate(o, get_card_cp(o))) for o in orders
        if (filter_sym == "All" or o.get("symbol", "BTC") == filter_sym)
        and (filter_side == "All" or o["side"] == filter_side)
        and (not filter_acc or o["account"] in filter_acc)
        and (not filter_danger or (calculate(o, get_card_cp(o))["danger_pct"] or 0) >= 70)
    ]

    if not filtered:
        st.info("No positions match the filter.")
    else:
        # ---- Expand / Collapse All ----
        if "cards_expanded" not in st.session_state:
            st.session_state["cards_expanded"] = False

        ea1, ea2, _ = st.columns([2, 2, 5])
        with ea1:
            if st.button("📂 Expand All", use_container_width=True):
                st.session_state["cards_expanded"] = True
                st.rerun()
        with ea2:
            if st.button("📁 Collapse All", use_container_width=True):
                st.session_state["cards_expanded"] = False
                st.rerun()

        # ---- Bulk Close Dialog ----
        if "bulk_close_version" not in st.session_state:
            st.session_state["bulk_close_version"] = 0

        if st.button("🗑️ Bulk Close Positions", use_container_width=False):
            dialog_bulk_close(orders, filtered)

        st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)

        cards_expanded = st.session_state["cards_expanded"]

        # ---- Position Cards Loop ----
        for i, (o, c) in enumerate(filtered):
            sym = o.get("symbol", "BTC")
            side_label = "BUY / LONG" if o["side"] == "Buy" else "SELL / SHORT"
            danger_pct = c["danger_pct"] or 0
            card_cp = get_card_cp(o)
            liq = o.get("liquidation")
            tg = o.get("target")
            sl = o.get("stop_loss")

            # Auto-expand if danger >= 70%
            should_expand = cards_expanded or danger_pct >= 70

            with st.expander(
                f"{o['account']} [{sym}] ({ACCOUNT_GROUP.get(o['account'], '?')}) "
                f"— {side_label} — Running: {fmt_inr(c['running_inr'])}",
                expanded=should_expand
            ):
                # ---- Row 1: Position Info + P&L (2 columns) ----
                r1_left, r1_right = st.columns(2)

                with r1_left:
                    st.markdown(f"""
                    <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                        <div style="font-size:10px;color:#888;text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:8px">Position</div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                            <div>
                                <div class="stat-label">Symbol</div>
                                <div class="stat-value">{sym}</div>
                            </div>
                            <div>
                                <div class="stat-label">Side</div>
                                <div class="stat-value" style="color:{'#00c853' if o['side']=='Buy' else '#ff1744'}">
                                    {'▲ LONG' if o['side']=='Buy' else '▼ SHORT'}
                                </div>
                            </div>
                            <div>
                                <div class="stat-label">Entry Price</div>
                                <div class="stat-value">${o.get('entry_price', 0):,.2f}</div>
                            </div>
                            <div>
                                <div class="stat-label">Quantity</div>
                                <div class="stat-value">{fmt_lots(o.get('qty', 0) or 0, sym)}</div>
                            </div>
                            <div>
                                <div class="stat-label">Current Price</div>
                                <div class="stat-value">${card_cp:,.2f}</div>
                            </div>
                            <div>
                                <div class="stat-label">EP × CP Diff</div>
                                <div class="stat-value" style="{color_val(c['ep_cp_diff'])}">{fmt_price(c['ep_cp_diff'])}</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with r1_right:
                    pnl_color = "#00e676" if c["running_inr"] >= 0 else "#ff1744"
                    st.markdown(f"""
                    <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                        <div style="font-size:10px;color:#888;text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:8px">Running P&L</div>
                        <div style="text-align:center;padding:2px 0">
                            <div style="font-size:18px;font-weight:800;font-family:monospace;
                                        color:{pnl_color};line-height:1.1">
                                {fmt_inr(c['running_inr'])}
                            </div>
                            <div style="font-size:12px;color:#888;margin-top:4px;font-family:monospace">
                                {fmt_usd(c['running_usd'])}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

                # ---- Row 2: Liquidation + TG/SL (2 columns) ----
                r2_left, r2_right = st.columns(2)

                with r2_left:
                    if liq:
                        bar_pct = min(danger_pct, 100)
                        bar_color = "#ff1744" if bar_pct >= 70 else ("#ffa726" if bar_pct >= 40 else "#00e676")
                        st.markdown(f"""
                        <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                            <div style="font-size:10px;color:#888;text-transform:uppercase;
                                        letter-spacing:1px;margin-bottom:8px">Liquidation</div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
                                <div>
                                    <div class="stat-label">Liq Price</div>
                                    <div class="stat-value" style="color:#ff6b6b">${liq:,.2f}</div>
                                </div>
                                <div>
                                    <div class="stat-label">Distance</div>
                                    <div class="stat-value">${abs(c['liq_danger']):,.2f}</div>
                                </div>
                                <div>
                                    <div class="stat-label">Liq Loss (INR)</div>
                                    <div class="stat-value" style="color:#ff1744">{fmt_inr(c['liq_loss_inr'])}</div>
                                </div>
                            </div>
                            <div class="stat-label">Risk — {bar_pct:.0f}% toward liquidation</div>
                            <div style="background:#2a2a4a;border-radius:4px;height:8px;
                                        overflow:hidden;margin-top:4px">
                                <div style="width:{bar_pct}%;background:{bar_color};
                                            height:100%;border-radius:4px"></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background:rgba(255,255,255,0.03);border-radius:8px;
                                    padding:12px;text-align:center">
                            <div class="stat-label">Liquidation</div>
                            <div class="stat-value" style="color:#555">Not set</div>
                        </div>
                        """, unsafe_allow_html=True)

                with r2_right:
                    tg_block = ""
                    sl_block = ""
                    if tg:
                        tg_block = f"""
                        <div>
                            <div class="stat-label">Target (TG)</div>
                            <div class="stat-value" style="color:#69f0ae">${tg:,.2f}</div>
                        </div>
                        <div>
                            <div class="stat-label">Profit at TG</div>
                            <div class="stat-value" style="color:#00e676">{fmt_inr(c['profit_inr'])}</div>
                        </div>
                        """
                    if sl:
                        sl_block = f"""
                        <div>
                            <div class="stat-label">Stop Loss (SL)</div>
                            <div class="stat-value" style="color:#ffa726">${sl:,.2f}</div>
                        </div>
                        <div>
                            <div class="stat-label">Loss at SL</div>
                            <div class="stat-value" style="color:#ff1744">{fmt_inr(c['loss_inr'])}</div>
                        </div>
                        """
                    if tg or sl:
                        st.markdown(f"""
                        <div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:12px">
                            <div style="font-size:10px;color:#888;text-transform:uppercase;
                                        letter-spacing:1px;margin-bottom:8px">Targets</div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                                {tg_block}{sl_block}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background:rgba(255,255,255,0.03);border-radius:8px;
                                    padding:12px;text-align:center">
                            <div class="stat-label">TG / SL</div>
                            <div class="stat-value" style="color:#555">Not set</div>
                        </div>
                        """, unsafe_allow_html=True)

                # ---- Action Buttons ----
                st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
                btn1, btn2, _ = st.columns([2, 2, 5])
                with btn1:
                    if st.button("✏️ Edit", key=f"edit_{i}", use_container_width=True):
                        dialog_edit_position(orders, orders.index(o))
                with btn2:
                    if st.button("🗑️ Close", key=f"del_{i}", use_container_width=True):
                        orders.remove(o)
                        save_orders(orders)
                        st.success(f"Position {o['account']} [{sym}] removed.")
                        st.rerun()

# ==========================================
# PROJECTION FEATURE
# ==========================================

st.markdown("---")
st.subheader("🔮 Position Projection", anchor="projection")
st.caption("Simulate how your positions would look at different prices.")

proj_col1, proj_col2, proj_col3 = st.columns([2, 2, 3])
with proj_col1:
    projected_btc = st.number_input(
        "Projected BTC Price (USD)",
        min_value=0.0,
        value=float(cp) if cp > 0 else 0.0,
        step=100.0,
        key="proj_btc_price"
    )
with proj_col2:
    projected_eth = st.number_input(
        "Projected ETH Price (USD)",
        min_value=0.0,
        value=float(eth_cp) if eth_cp > 0 else 0.0,
        step=10.0,
        key="proj_eth_price"
    )

def get_proj_cp(order):
    sym = order.get("symbol", "BTC")
    return projected_eth if sym == "ETH" else projected_btc

if (projected_btc > 0 or projected_eth > 0) and orders:
    proj_calcs = [calculate(o, get_proj_cp(o)) for o in orders]

    proj_total_inr = sum(c["running_inr"] for c in proj_calcs)
    proj_profit = [o for o, c in zip(orders, proj_calcs) if c["running_inr"] > 0]
    proj_loss = [o for o, c in zip(orders, proj_calcs) if c["running_inr"] < 0]
    proj_liquidated = [
        o for o, c in zip(orders, proj_calcs)
        if o.get("liquidation") and (
            (o["side"] == "Buy" and get_proj_cp(o) <= o["liquidation"]) or
            (o["side"] == "Sell" and get_proj_cp(o) >= o["liquidation"])
        )
    ]

    if proj_liquidated:
        liq_accounts = ", ".join(f"{o['account']}[{o.get('symbol','BTC')}]" for o in proj_liquidated)
        st.markdown(f"""
        <div class="danger-zone">
            💀 At these prices, these positions would be <b>liquidated</b>: <b>{liq_accounts}</b>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("#### 📊 Projected Summary")
    ps1, ps2, ps3, ps4, ps5 = st.columns(5)
    net_color = "#00e676" if proj_total_inr >= 0 else "#ff1744"
    with ps1: st.markdown(summary_box("Net P&L", fmt_inr(proj_total_inr), net_color), unsafe_allow_html=True)
    with ps2: st.markdown(summary_box("Profit", len(proj_profit), "#00e676"), unsafe_allow_html=True)
    with ps3: st.markdown(summary_box("Loss", len(proj_loss), "#ff1744"), unsafe_allow_html=True)
    with ps4: st.markdown(summary_box("Liquidated", len(proj_liquidated), "#ff1744" if proj_liquidated else "#888"), unsafe_allow_html=True)
    with ps5: st.markdown(summary_box("Total", len(orders)), unsafe_allow_html=True)

    st.markdown("#### 📋 Projected Analysis")
    proj_sorted = sorted(zip(orders, proj_calcs), key=lambda x: x[1]["running_inr"])
    proj_rows = []
    for o, c in proj_sorted:
        sym = o.get("symbol", "BTC")
        liq = o.get("liquidation")
        is_liquidated = liq and (
            (o["side"] == "Buy" and get_proj_cp(o) <= liq) or
            (o["side"] == "Sell" and get_proj_cp(o) >= liq)
        )
        danger_str = "💀 LIQUIDATED" if is_liquidated else (
            f"{c['danger_pct']:.0f}% to Liq" if c["danger_pct"] is not None else "—"
        )
        proj_rows.append({
            "Account": o["account"],
            "Symbol": sym,
            "Exchange": ACCOUNT_GROUP.get(o["account"], "—"),
            "Side": o["side"],
            "Entry": fmt_price(o.get("entry_price")),
            "Qty (Lots)": qty_to_lots(o.get("qty", 0) or 0, sym),
            "Proj Price": fmt_price(get_proj_cp(o)),
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

elif (projected_btc > 0 or projected_eth > 0) and not orders:
    st.info("No open positions to project.")

# ==========================================
# SIDEBAR INFO
# ==========================================

price_data = st.session_state.get("price_cache", {})
eth_data = st.session_state.get("price_cache_eth", {})
st.sidebar.markdown("---")
st.sidebar.markdown(f"**BTC:** ${price_data.get('price', 0):,.1f}")
st.sidebar.markdown(f"**ETH:** ${eth_data.get('price', 0):,.2f}")
st.sidebar.markdown(f"**Source:** {price_data.get('source', '—')}")
st.sidebar.markdown(f"**Open Positions:** {len(orders)}")