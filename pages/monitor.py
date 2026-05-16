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
import math
import mplfinance as mpf
import matplotlib.pyplot as plt
import io

# if not check_password():
#     st.stop()

# ==========================================
# CONFIGURATION
# ==========================================

ORDERS_DB = "running_orders.json"
USD_TO_INR = 85.0
LOT_SIZE = 0.001      # 1 lot = 0.001 BTC
ETH_LOT_SIZE = 0.01   # 1 lot = 0.01 ETH

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard"

ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
ACCOUNT_GROUP = {
    "A-1": "Delta", "A-2": "Delta", "A-3": "Delta", "A-4": "Delta", "A-5": "Delta", "A-6": "Delta",
    "A-7": "CS", "A-8": "CS", "A-9": "CS", "A-10": "CS", "A-11": "CS",
    "A-12": "Pi42", "A-13": "CDX", "A-14": "MDX", "A-15": "ZEP", "A-16": "BN", "A-17": "BYT"
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

def fetch_with_ccxt(symbol='BTC/USDT'):
    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']
    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': False,
            })
            ticker = exchange.fetch_ticker(symbol)
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

def fetch_with_coingecko(coin_id='bitcoin'):
    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={coin_id}",
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

def fetch_with_bybit(symbol='BTCUSDT'):
    r = requests.get(
        f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}",
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

def _do_fetch(symbol='BTC'):
    """Fetch price for BTC or ETH."""
    ccxt_sym = f"{symbol}/USDT"
    bybit_sym = f"{symbol}USDT"
    coin_id = 'bitcoin' if symbol == 'BTC' else 'ethereum'
    try:
        result = fetch_with_ccxt(ccxt_sym)
        if result:
            return result
    except Exception:
        pass
    try:
        return fetch_with_coingecko(coin_id)
    except Exception:
        pass
    try:
        return fetch_with_bybit(bybit_sym)
    except Exception:
        pass
    return None

def fmt_volume(vol, price):
    vol_usd = vol * price
    if vol_usd >= 1_000_000:
        return f"{vol_usd / 1_000_000:,.2f}M"
    else:
        return f"{vol_usd / 1_000:,.1f}K"

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
# CHART BUILDER
# ==========================================

def build_candlestick_chart(df_chart, chart_title):
    mc = mpf.make_marketcolors(
        up='#00e676', down='#ff1744',
        edge='inherit', wick='inherit',
        volume={'up': '#00e676', 'down': '#ff1744'},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, base_mpf_style='nightclouds',
        gridstyle='--', gridcolor='#2a2a4a',
        facecolor='#0f0f23', figcolor='#0f0f23',
        y_on_right=True,
        rc={'axes.labelcolor': '#aaaaaa', 'xtick.color': '#aaaaaa', 'ytick.color': '#aaaaaa'}
    )
    fig, axes = mpf.plot(
        df_chart, type='candle', style=style,
        ylabel='', volume=True, ylabel_lower='',
        figsize=(14, 8), returnfig=True, tight_layout=True,
        datetime_format='%m-%d %H:%M', xrotation=30,
    )
    axes[0].set_title(chart_title, color='#cccccc', fontsize=10,
                      fontfamily='monospace', loc='center', pad=10)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='#0f0f23', edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()

def send_chart_telegram(symbol, TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS_UI):
    """Fetch OHLCV, build chart, send to Telegram. Used by both BTC and ETH buttons."""
    ccxt_sym = f"{symbol}/USDT"
    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']
    ohlcv = None
    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({'timeout': 10000, 'enableRateLimit': True})
            ohlcv = exchange.fetch_ohlcv(ccxt_sym, timeframe='1h', limit=48)
            break
        except Exception:
            continue
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
                active_accounts = {o.get("account") for o in orders}
                inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]
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
                    f"Idle Accounts ({len(inactive_accounts)}): {', '.join(inactive_accounts) if inactive_accounts else 'None'}"
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
                f'<div class="price-display {eth_color}" style="font-size:1.6rem">ETH ${eth_cp:,.2f}</div>'
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

    btn1, btn2, btn3, _ = st.columns([2, 2, 2, 3])
    with btn1:
        send_report = st.button("📊 Send Report", help="Send instant portfolio report to Telegram", use_container_width=True)
    with btn2:
        send_btc = st.button("📈 BTC Chart", help="Send BTC candlestick chart", use_container_width=True)
    with btn3:
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
    if st.button("📊 Send Report Now", help="Send instant portfolio report to Telegram"):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS_UI:
            st.warning("Telegram not configured in secrets.")
        elif not orders:
            st.info("No open positions to report.")
        else:
            total_usd = total_profit = total_loss = total_inr = 0
            profit_count = loss_count = 0
            buy_qty_btc = sell_qty_btc = buy_qty_eth = sell_qty_eth = 0
            lines = []
            order_pnls = []
            ALL_ACCOUNTS = [f"A-{i}" for i in range(1, 18)]
            active_accounts = {o.get("account") for o in orders}
            inactive_accounts = [a for a in ALL_ACCOUNTS if a not in active_accounts]

            for o in orders:
                sym = o.get("symbol", "BTC")
                price = eth_cp if sym == "ETH" else cp
                running_usd = (price - o.get("entry_price", 0)) * o.get("qty", 0) if o.get("side") == "Buy" else (o.get("entry_price", 0) - price) * o.get("qty", 0)
                running_inr = running_usd * USD_TO_INR
                total_usd += running_usd
                total_inr += running_inr
                if running_inr > 0: profit_count += 1; total_profit += running_inr
                elif running_inr < 0: loss_count += 1; total_loss += running_inr
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
                f"₿ <code>${cp:,.1f}</code>  Ξ <code>${eth_cp:,.2f}</code>\n"
                f"P: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
                f"L: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
                f"<b>T</b>: <code>{total_sign}₹{total_inr:,.0f}</code>\n"
                f"BTC BQ: {btc_to_lots(buy_qty_btc)} | SQ: {btc_to_lots(sell_qty_btc)} lots\n"
                f"ETH BQ: {qty_to_lots(buy_qty_eth, 'ETH')} | SQ: {qty_to_lots(sell_qty_eth, 'ETH')} lots\n\n"
            )
            msg += "\n".join(lines)
            msg += f"\n\nTotal Orders: {len(orders)}\nIdle Accounts ({len(inactive_accounts)}): {', '.join(inactive_accounts) if inactive_accounts else 'None'}"

            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            all_ok = True
            for cid in TELEGRAM_CHAT_IDS_UI:
                r = requests.post(url, json={"chat_id": cid, "text": msg, "parse_mode": "HTML"}, timeout=10)
                if not r.ok: all_ok = False
            if all_ok:
                st.success("✅ Report sent!")
            else:
                st.error("❌ Failed to send to some chats.")

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

    st.caption(f"BTC source: {price_data.get('source', '—')} · ETH source: {eth_data.get('source', '—')} · {datetime.datetime.now().strftime('%H:%M:%S')}")
    st.markdown("---")

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

    # Summary
    total_running_inr = sum(c["running_inr"] for c in calcs)
    profit_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] > 0]
    loss_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] < 0]
    buy_qty_btc = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Buy" and o.get("symbol", "BTC") == "BTC")
    sell_qty_btc = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Sell" and o.get("symbol", "BTC") == "BTC")
    buy_qty_eth = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Buy" and o.get("symbol") == "ETH")
    sell_qty_eth = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Sell" and o.get("symbol") == "ETH")

    st.markdown("### 📊 Summary")
    s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
    net_color = "#00e676" if total_running_inr >= 0 else "#ff1744"
    with s1: st.markdown(summary_box("Net P&L", fmt_inr(total_running_inr), net_color), unsafe_allow_html=True)
    with s2: st.markdown(summary_box("Profit", len(profit_orders), "#00e676"), unsafe_allow_html=True)
    with s3: st.markdown(summary_box("Loss", len(loss_orders), "#ff1744"), unsafe_allow_html=True)
    with s4: st.markdown(summary_box("Total", len(orders)), unsafe_allow_html=True)
    with s5: st.markdown(summary_box("BTC Buy/Sell", f"{btc_to_lots(buy_qty_btc)}L / {btc_to_lots(sell_qty_btc)}L"), unsafe_allow_html=True)
    with s6: st.markdown(summary_box("ETH Buy/Sell", f"{qty_to_lots(buy_qty_eth,'ETH')}L / {qty_to_lots(sell_qty_eth,'ETH')}L"), unsafe_allow_html=True)
    with s7: st.markdown(summary_box("Positions", f"BTC:{sum(1 for o in orders if o.get('symbol','BTC')=='BTC')} ETH:{sum(1 for o in orders if o.get('symbol')=='ETH')}"), unsafe_allow_html=True)

    st.markdown("---")

    # Analysis table
    st.markdown("### 📋 Position Analysis")
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
    st.markdown("---")

    st.session_state["current_cp"] = cp
    st.session_state["current_eth_cp"] = eth_cp

# ==========================================
# MAIN PAGE
# ==========================================

st.title("⚡ Live Order Monitor")

orders = load_orders()

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

# ==========================================
# ADD POSITION BUTTON
# ==========================================

if st.button("➕ Add New Position"):
    dialog_add_position(orders)

st.markdown("---")

# ==========================================
# POSITION CARDS
# ==========================================

if orders:
    st.markdown("### 🗂️ Position Cards")

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

    for i, (o, c) in enumerate(filtered):
        sym = o.get("symbol", "BTC")
        side_label = "BUY / LONG" if o["side"] == "Buy" else "SELL / SHORT"
        danger_pct = c["danger_pct"] or 0
        card_cp = get_card_cp(o)

        with st.expander(
            f"{o['account']} [{sym}] ({ACCOUNT_GROUP.get(o['account'], '?')}) — {side_label} — "
            f"Running: {fmt_inr(c['running_inr'])}",
            expanded=False
        ):
            c1, c2, c3, c4 = st.columns(4)

            with c1:
                st.markdown(f'<div class="stat-label">Symbol</div><div class="stat-value">{sym}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Entry Price</div><div class="stat-value">${o.get("entry_price", 0):,.2f}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Quantity</div><div class="stat-value">{fmt_lots(o.get("qty", 0) or 0, sym)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">EP × CP Diff</div><div class="stat-value" style="{color_val(c["ep_cp_diff"])}">{fmt_price(c["ep_cp_diff"])}</div>', unsafe_allow_html=True)

            with c2:
                st.markdown(f'<div class="stat-label">Current Price</div><div class="stat-value">${card_cp:,.2f}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Running P&L (USD)</div><div class="stat-value" style="{color_val(c["running_usd"])}">{fmt_usd(c["running_usd"])}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="stat-label">Running P&L (INR)</div><div class="stat-value" style="{color_val(c["running_inr"])}">{fmt_inr(c["running_inr"])}</div>', unsafe_allow_html=True)

            with c3:
                liq = o.get("liquidation")
                if liq:
                    st.markdown(f'<div class="stat-label">Liquidation Price</div><div class="stat-value" style="color:#ff6b6b">${liq:,.2f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">CP × Liq Distance</div><div class="stat-value">${abs(c["liq_danger"]):,.2f}</div>', unsafe_allow_html=True)
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
                    st.markdown(f'<div class="stat-label">Target (TG)</div><div class="stat-value" style="color:#69f0ae">${tg:,.2f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="stat-label">Profit at TG (INR)</div><div class="stat-value" style="color:#00e676">{fmt_inr(c["profit_inr"])}</div>', unsafe_allow_html=True)
                if sl:
                    st.markdown(f'<div class="stat-label">Stop Loss (SL)</div><div class="stat-value" style="color:#ffa726">${sl:,.2f}</div>', unsafe_allow_html=True)
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
                    st.success(f"Position {o['account']} [{sym}] removed.")
                    st.rerun()

# ==========================================
# PROJECTION FEATURE
# ==========================================

st.markdown("---")
st.markdown("### 🔮 Position Projection")
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