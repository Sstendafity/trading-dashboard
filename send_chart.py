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
import datetime
import pandas as pd

from core.price_feed import fetch_ohlcv
from core.charts import build_candlestick_chart, fmt_volume
from core.telegram import send_message, send_photo

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
# TELEGRAM (fan-out over configured chats)
# ==========================================

def send_text(message):
    for chat_id in TELEGRAM_CHAT_IDS:
        if send_message(TELEGRAM_TOKEN, chat_id, message):
            print(f"Text sent to {chat_id}")
        else:
            print(f"Text failed to {chat_id}")

def send_photo_only(image_bytes, filename="chart.png"):
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = send_photo(TELEGRAM_TOKEN, chat_id, image_bytes, filename=filename)
            if r.ok:
                print(f"Photo sent to {chat_id}")
            else:
                print(f"Photo failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Photo error for {chat_id}: {e}")

def send_photo_with_caption(image_bytes, caption, filename="chart.png"):
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = send_photo(TELEGRAM_TOKEN, chat_id, image_bytes,
                           filename=filename, caption=caption)
            if r.ok:
                print(f"Photo+caption sent to {chat_id}")
            else:
                print(f"Photo+caption failed to {chat_id}: {r.text}")
        except Exception as e:
            print(f"Photo+caption error for {chat_id}: {e}")

# ==========================================
# PROCESS AND SEND ONE SYMBOL
# ==========================================

def process_and_send(symbol):
    """Fetch OHLCV, build chart, send text + photo for one symbol."""
    print(f"\n--- Processing {symbol} ---")

    ohlcv = fetch_ohlcv(symbol)
    if not ohlcv:
        print(f"❌ Failed to fetch {symbol} OHLCV")
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
    image_bytes = build_candlestick_chart(df_chart, chart_title)

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
