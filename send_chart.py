"""
send_chart.py
Fetches last 24 hourly BTC/USDT candles, generates a candlestick chart,
and sends both a text summary and chart image to Telegram.

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
import matplotlib.ticker as mticker

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

def fetch_ohlcv():
    exchanges_to_try = ['okx', 'kucoin', 'gateio', 'htx']
    for exchange_id in exchanges_to_try:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': True,
            })
            # Fetch 48 candles so MAs have enough history, display last 24
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=48)
            print(f"OHLCV fetched via {exchange_id}")
            return ohlcv
        except Exception as e:
            print(f"{exchange_id} failed: {e}")
            continue
    raise Exception("All exchanges failed to fetch OHLCV")

def fmt_volume(vol, price):
    """Convert BTC volume to USD and format in K/M."""
    vol_usd = vol * price
    if vol_usd >= 1_000_000:
        return f"{vol_usd / 1_000_000:,.2f}M"
    else:
        return f"{vol_usd / 1_000:,.1f}K"
    
# ==========================================
# TELEGRAM
# ==========================================

def send_text(message):
    """Send text message only."""
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

def send_photo_only(image_bytes):
    """Send chart image only, no caption."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(url, data={
                "chat_id": chat_id,
            }, files={
                "photo": ("btc_chart.png", image_bytes, "image/png")
            }, timeout=30)
            if r.ok:
                print(f"Photo sent to {chat_id}")
            else:
                print(f"Photo failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Photo error for {chat_id}: {e}")

def send_photo_with_caption(image_bytes, caption):
    """Send chart image with text as caption."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(url, data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }, files={
                "photo": ("btc_chart.png", image_bytes, "image/png")
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

    # Add title centered above the candle chart axes
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
# MAIN
# ==========================================

def main():
    print("=" * 40)
    print("BTC Chart — Hourly Send")
    print(f"Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 40)

    # Fetch OHLCV
    ohlcv = fetch_ohlcv()

    # Build DataFrame
    df_full = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_full['timestamp'] = pd.to_datetime(df_full['timestamp'], unit='ms')
    df_full.set_index('timestamp', inplace=True)

    # Current (latest completed) candle — index -1
    current = df_full.iloc[-2]
    candle_time = df_full.index[-2].strftime('%Y-%m-%d %H:00 UTC')

    o = current['open']
    h = current['high']
    l = current['low']
    c = current['close']
    vol = current['volume']
    vol_str = fmt_volume(vol, c)
    change = c - o
    change_pct = (change / o) * 100
    change_sign = '+' if change >= 0 else ''

    # ==========================================
    # TEXT MESSAGE
    # ==========================================

    text_msg = (
        f"O <code>{o:,.1f}</code>  "
        f"H <code>{h:,.1f}</code>  "
        f"L <code>{l:,.1f}</code>  "
        f"C <code>{c:,.1f}</code>\n"
        f"Vol <code>{vol_str}</code>  ·  "
        f"Change <code>{change_sign}{change:,.1f} ({change_sign}{change_pct:.2f}%)</code>\n"
        f"<b>BTC/USDT · 1H · {candle_time}</b>"
    )

    # ==========================================
    # CHART — last 24 candles only
    # ==========================================

    df_chart = df_full.iloc[:-1].tail(24).copy()

    chart_title = (
        f"BTC/USDT · 1H   "
        f"O {o:,.1f}  H {h:,.1f}  L {l:,.1f}  C {c:,.1f}  "
        f"Change {change_sign}{change:,.1f} ({change_sign}{change_pct:.2f}%)  "
        f"Vol {vol_str}"
    )

    image_bytes = build_chart(df_chart, chart_title)

    # ==========================================
    # SEND
    # Options:
    #   A) Text + photo separately (current)
    #   B) Photo with caption — swap comments below
    # ==========================================

    # Option A — separate text then photo (default)
    send_text(text_msg)
    send_photo_only(image_bytes)

    # Option B — photo with caption (comment out A and uncomment below)
    # send_photo_with_caption(image_bytes, text_msg)

    print("Done.")


if __name__ == "__main__":
    main()