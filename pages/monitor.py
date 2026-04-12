import streamlit as st
import pandas as pd
import requests
import json
import os
import datetime
import re
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

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard"

EXCHANGES = ["Delta", "CS", "Pi42", "CDX", "MDX", "ZEP"]
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
div.stButton > button {
    white-space: nowrap;
    padding-left: 16px;
    padding-right: 16px;
    height: auto;
}
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
.safe-zone {
    background: rgba(0, 230, 118, 0.08);
    border: 1px solid rgba(0, 230, 118, 0.2);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: #69f0ae;
}
.summary-box {
    background: #0f0f23;
    border-radius: 10px;
    padding: 14px;
    text-align: center;
}
.divider { border-top: 1px solid #2a2a4a; margin: 8px 0; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# PRICE FETCHING
# ==========================================

@st.cache_data(ttl=60)
def fetch_btc_price():
    # Try CoinGecko first (works on Streamlit Cloud)
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&ids=bitcoin",
            timeout=10
        )
        data = r.json()[0]
        return {
            "price": float(data["current_price"]),
            "change_pct": float(data["price_change_percentage_24h"] or 0),
            "high": float(data["high_24h"]),
            "low": float(data["low_24h"]),
            "ok": True
        }
    except Exception:
        pass

    # Fallback: Bybit (also works on Streamlit Cloud)
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers"
            "?category=linear&symbol=BTCUSDT",
            timeout=10
        )
        data = r.json()["result"]["list"][0]
        return {
            "price": float(data["lastPrice"]),
            "change_pct": float(data["price24hPcnt"]) * 100,
            "high": float(data["highPrice24h"]),
            "low": float(data["lowPrice24h"]),
            "ok": True
        }
    except Exception:
        return {"price": 0, "change_pct": 0, "high": 0, "low": 0, "ok": False}

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
    # Sync to GitHub
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

    if side == "Buy":  # Long
        ep_cp_diff = cp - entry
        liq_danger = (cp - liq) if liq else None
        ep_liq_diff = (entry - liq) if liq else None
        ep_tg_diff = (tg - entry) if tg else None
        ep_sl_diff = (entry - sl) if sl else None
    else:  # Short/Sell
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

    # Danger level: how close current price is to liquidation (as % of ep→liq distance)
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

# ==========================================
# MAIN PAGE
# ==========================================

st.title("⚡ Live Order Monitor")

# --- LIVE PRICE BAR ---
price_data = fetch_btc_price()
cp = price_data["price"]

if not price_data["ok"]:
    st.error("⚠️ Could not fetch price. Both CoinGecko and Bybit failed.")
    cp = 0

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
    if st.button("🔄", help="Refresh price"):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# Load orders
orders = load_orders()

# ==========================================
# ANALYSIS SUMMARY
# ==========================================

if orders:
    calcs = [calculate(o, cp) for o in orders]

    total_running_inr = sum(c["running_inr"] for c in calcs)
    profit_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] > 0]
    loss_orders = [o for o, c in zip(orders, calcs) if c["running_inr"] < 0]
    buy_qty = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Buy")
    sell_qty = sum(o.get("qty", 0) or 0 for o in orders if o.get("side") == "Sell")

    # Danger alerts
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

    st.markdown("### 📊 Summary")
    s1, s2, s3, s4, s5, s6 = st.columns(6)

    def summary_box(label, value, color="#fff"):
        return f'<div class="summary-box"><div class="stat-label">{label}</div><div class="stat-value" style="color:{color}">{value}</div></div>'

    net_color = "#00e676" if total_running_inr >= 0 else "#ff1744"

    with s1: st.markdown(summary_box("Net Running P&L", fmt_inr(total_running_inr), net_color), unsafe_allow_html=True)
    with s2: st.markdown(summary_box("Profit Positions", len(profit_orders), "#00e676"), unsafe_allow_html=True)
    with s3: st.markdown(summary_box("Loss Positions", len(loss_orders), "#ff1744"), unsafe_allow_html=True)
    with s4: st.markdown(summary_box("Total Positions", len(orders), "#fff"), unsafe_allow_html=True)
    with s5: st.markdown(summary_box("Buy Qty (BTC)", f"{buy_qty:.4f}", "#00e676"), unsafe_allow_html=True)
    with s6: st.markdown(summary_box("Sell Qty (BTC)", f"{sell_qty:.4f}", "#ff1744"), unsafe_allow_html=True)

    st.markdown("---")

    # ==========================================
    # ANALYSIS TABLE
    # ==========================================

    st.markdown("### 📋 Position Analysis")

    sorted_pairs = sorted(
        zip(orders, calcs),
        key=lambda x: x[1]["running_inr"]
    )

    table_rows = []
    for o, c in sorted_pairs:
        danger_str = f"{c['danger_pct']:.0f}% to Liq" if c["danger_pct"] is not None else "—"

        table_rows.append({
            "Account": o["account"],
            "Exchange": ACCOUNT_GROUP.get(o["account"], "—"),
            "Side": o["side"],
            "Entry": fmt_price(o.get("entry_price")),
            "Qty": f"{o.get('qty', 0):.4f}",
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

# ==========================================
# POSITION CARDS (DETAILED VIEW)
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
                st.markdown(f'<div class="stat-label">Quantity</div><div class="stat-value">{o.get("qty", 0):.4f} BTC</div>', unsafe_allow_html=True)
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
            btn1, btn2, _ = st.columns([1, 1, 5])
            with btn1:
                if st.button("✏️ Edit", key=f"edit_{i}"):
                    st.session_state["editing_idx"] = orders.index(o)
                    st.rerun()
            with btn2:
                if st.button("🗑️ Close Position", key=f"del_{i}"):
                    orders.remove(o)
                    save_orders(orders)
                    st.success(f"Position {o['account']} removed.")
                    st.rerun()

st.markdown("---")

# ==========================================
# ADD / EDIT POSITION FORM
# ==========================================

editing_idx = st.session_state.get("editing_idx", None)
form_title = "✏️ Edit Position" if editing_idx is not None else "➕ Add New Position"

with st.expander(form_title, expanded=(editing_idx is not None or not orders)):
    default = {}
    if editing_idx is not None and editing_idx < len(orders):
        default = orders[editing_idx]

    f1, f2, f3 = st.columns(3)
    with f1:
        acc = st.selectbox("Account", ACCOUNTS,
                           index=ACCOUNTS.index(default.get("account", "A-1")) if default.get("account") in ACCOUNTS else 0,
                           key="form_acc")
        side = st.selectbox("Side", ["Buy", "Sell"],
                            index=0 if default.get("side", "Buy") == "Buy" else 1,
                            key="form_side")
    with f2:
        entry = st.number_input("Entry Price (USD)", min_value=0.0, value=float(default.get("entry_price", 0) or 0), step=0.1, key="form_entry")
        qty = st.number_input("Quantity (BTC)", min_value=0.0, value=float(default.get("qty", 0) or 0), step=0.001, format="%.4f", key="form_qty")
        threshold = st.number_input(
            "Alert Threshold (%)",
            min_value=0.5, max_value=20.0,
            value=float(default.get("alert_threshold", 3.0)),
            step=0.5, key="form_threshold"
        )
    with f3:
        liq_default = default.get("liquidation", None)
        liq_input = st.number_input("Liquidation Price (optional)", min_value=0.0,
                                    value=float(liq_default) if liq_default else 0.0,
                                    step=0.1, key="form_liq")
        liq_val = liq_input if liq_input > 0 else None

    f4, f5 = st.columns(2)
    with f4:
        tg_default = default.get("target", None)
        tg_input = st.number_input("Target / TG (optional)", min_value=0.0,
                                   value=float(tg_default) if tg_default else 0.0,
                                   step=0.1, key="form_tg")
        tg_val = tg_input if tg_input > 0 else None
    with f5:
        sl_default = default.get("stop_loss", None)
        sl_input = st.number_input("Stop Loss / SL (optional)", min_value=0.0,
                                   value=float(sl_default) if sl_default else 0.0,
                                   step=0.1, key="form_sl")
        sl_val = sl_input if sl_input > 0 else None

    btn_col1, btn_col2 = st.columns([2, 5])
    with btn_col1:
        submit_label = "💾 Update" if editing_idx is not None else "✅ Add Position"
        if st.button(submit_label, use_container_width=True):
            if entry <= 0 or qty <= 0:
                st.error("Entry Price and Quantity are required.")
            else:
                new_order = {
                    "account": acc,
                    "side": side,
                    "entry_price": entry,
                    "qty": qty,
                    "liquidation": liq_val,
                    "target": tg_val,
                    "stop_loss": sl_val,
                    "added_at": str(datetime.datetime.now()),
                    "alert_threshold": threshold,
                }
                if editing_idx is not None:
                    orders[editing_idx] = new_order
                    st.session_state.pop("editing_idx", None)
                    st.success("✅ Position updated.")
                else:
                    orders.append(new_order)
                    st.success(f"✅ {acc} {side} position added.")
                save_orders(orders)
                st.rerun()

    if editing_idx is not None:
        with btn_col2:
            if st.button("✖ Cancel Edit"):
                st.session_state.pop("editing_idx", None)
                st.rerun()

# ==========================================
# AUTO REFRESH
# ==========================================

from streamlit_autorefresh import st_autorefresh

refresh_interval = st.sidebar.selectbox(
    "Auto Refresh", ["Off", "30s", "1 min", "5 min"],
    index=0  # default to Off — safer
)
refresh_ms = {"30s": 30_000, "1 min": 60_000, "5 min": 300_000}

if refresh_interval != "Off":
    st_autorefresh(interval=refresh_ms[refresh_interval], key="price_refresh")
    st.sidebar.caption(f"Refreshing every {refresh_interval}")

st.sidebar.markdown("---")
st.sidebar.markdown(f"**BTC Price:** ${cp:,.1f}")
st.sidebar.markdown(f"**Open Positions:** {len(orders)}")
st.sidebar.markdown(f"**Last Update:** {datetime.datetime.now().strftime('%H:%M:%S')}")