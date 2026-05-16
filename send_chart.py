"""
send_chart.py
Fetches last 24 hourly candles for BTC and ETH, generates candlestick charts,
and sends both text summary and chart image to Telegram for each.

Run via GitHub Actions hourly.
Environment variables required:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  TELEGRAM_CHAT_ID_2  (optional)
"""

import os
import io
import datetime
import requests
import ccxt
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

# ==========================================
# CONFIGURATION
# ==========================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [
    os.environ["TELEGRAM_CHAT_ID"],
    os.environ.get("TELEGRAM_CHAT_ID_2", ""),
]
TELEGRAM_CHAT_IDS = [cid for cid in TELEGRAM_CHAT_IDS if cid]

# ==========================================
# FETCH OHLCV
# ==========================================

def fetch_ohlcv(symbol='BTC/USDT'):
    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']
    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': True,
            })
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=48)
            print(f"OHLCV fetched via {exchange_id} [{symbol}]")
            return ohlcv
        except Exception as e:
            print(f"{exchange_id} [{symbol}] failed: {e}")
            continue
    raise Exception(f"All exchanges failed to fetch OHLCV for {symbol}")

def fmt_volume(vol, price):
    vol_usd = vol * price
    if vol_usd >= 1_000_000:
        return f"{vol_usd / 1_000_000:,.2f}M"
    else:
        return f"{vol_usd / 1_000:,.1f}K"

# ==========================================
# TELEGRAM
# ==========================================

def send_text(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }, timeout=10)
            if r.ok:
                print(f"Text sent to {chat_id}")
            else:
                print(f"Text failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Text error for {chat_id}: {e}")

def send_photo_only(image_bytes, filename="chart.png"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(url, data={"chat_id": chat_id}, files={
                "photo": (filename, image_bytes, "image/png")
            }, timeout=30)
            if r.ok:
                print(f"Photo sent to {chat_id}")
            else:
                print(f"Photo failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Photo error for {chat_id}: {e}")

def send_photo_with_caption(image_bytes, caption, filename="chart.png"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(url, data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }, files={
                "photo": (filename, image_bytes, "image/png")
            }, timeout=30)
            if r.ok:
                print(f"Photo+caption sent to {chat_id}")
            else:
                print(f"Photo+caption failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Photo+caption error for {chat_id}: {e}")

# ==========================================
# BUILD CHART
# ==========================================

def build_chart(df, title):
    mc = mpf.make_marketcolors(
        up='#00e676',
        down='#ff1744',
        edge='inherit',
        wick='inherit',
        volume={'up': '#00e676', 'down': '#ff1744'},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style='nightclouds',
        gridstyle='--',
        gridcolor='#2a2a4a',
        facecolor='#0f0f23',
        figcolor='#0f0f23',
        y_on_right=True,
        rc={
            'axes.labelcolor': '#aaaaaa',
            'xtick.color': '#aaaaaa',
            'ytick.color': '#aaaaaa',
        }
    )
    fig, axes = mpf.plot(
        df,
        type='candle',
        style=style,
        ylabel='',
        volume=True,
        ylabel_lower='',
        figsize=(14, 8),
        returnfig=True,
        tight_layout=True,
        datetime_format='%m-%d %H:%M',
        xrotation=30,
    )
    axes[0].set_title(
        title,
        color='#cccccc',
        fontsize=10,
        fontfamily='monospace',
        loc='center',
        pad=10,
    )
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='#0f0f23', edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()

# ==========================================
# PROCESS AND SEND ONE SYMBOL
# ==========================================

def process_and_send(symbol):
    """Fetch OHLCV, build chart, send text + photo for one symbol."""
    ccxt_sym = f"{symbol}/USDT"
    print(f"\n--- Processing {symbol} ---")

    try:
        ohlcv = fetch_ohlcv(ccxt_sym)
    except Exception as e:
        print(f"❌ Failed to fetch {symbol} OHLCV: {e}")
        return

    df_full = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_full['timestamp'] = pd.to_datetime(df_full['timestamp'], unit='ms')
    df_full.set_index('timestamp', inplace=True)

    # Use last COMPLETED candle (iloc[-2])
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
    change_sign = '+' if change >= 0 else ''

    # Text message
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

    # Chart — last 24 completed candles
    df_chart = df_full.iloc[:-1].tail(24).copy()
    chart_title = (
        f"{symbol}/USDT · 1H   "
        f"O {o:,.2f}  H {h:,.2f}  L {l:,.2f}  C {c:,.2f}  "
        f"Change {change_sign}{change:,.2f} ({change_sign}{change_pct:.2f}%)  "
        f"Vol {vol_str}"
    )
    image_bytes = build_chart(df_chart, chart_title)

    # Send — Option A: photo then text separately (default)
    send_photo_only(image_bytes, filename=f"{symbol.lower()}_chart.png")
    send_text(text_msg)

    # Option B: photo with caption (comment out A and uncomment below)
    # send_photo_with_caption(image_bytes, text_msg, filename=f"{symbol.lower()}_chart.png")

    print(f"✅ {symbol} chart sent.")

# ==========================================
# MAIN
# ==========================================

def main():
    print("=" * 40)
    print("Hourly Chart — BTC + ETH")
    print(f"Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 40)

    process_and_send("BTC")
    process_and_send("ETH")

    print("\nDone.")


if __name__ == "__main__":
    main()