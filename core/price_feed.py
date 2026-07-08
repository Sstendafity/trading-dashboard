"""
core.price_feed — single source of truth for crypto price data.

Previously the CCXT -> CoinGecko -> Bybit fallback chain was copy-pasted across
bot.py, alert_check.py, alert_check_ETH.py, pages/monitor.py and send_chart.py.

Three shapes of data are needed by callers, so three functions are exposed —
all sharing the same exchange list and fallback order:

  * fetch_price(symbol)  -> float          (bot / cron alerts: just the last price)
  * fetch_ticker(symbol) -> dict | None    (monitor: price + 24h change/high/low)
  * fetch_ohlcv(symbol)  -> list | None    (charts / daily-open lookups)

Only depends on `requests` and (optionally) `ccxt`, so it is safe to import from
the lightweight cron scripts.
"""

import requests

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# Fallback order for CCXT exchanges.
EXCHANGES = ['okx', 'kucoin', 'gateio', 'htx']

# Maps a bare symbol onto its CoinGecko coin id.
COINGECKO_IDS = {'BTC': 'bitcoin', 'ETH': 'ethereum'}


# ==========================================
# SIMPLE LAST-PRICE (float) — bot / cron alerts
# ==========================================

def _ccxt_price(symbol):
    if not CCXT_AVAILABLE:
        return None
    for exchange_id in EXCHANGES:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': False,
            })
            ticker = exchange.fetch_ticker(f'{symbol}/USDT')
            price = float(ticker['last'])
            print(f"Price fetched via CCXT ({exchange_id}): ${price:,.2f}")
            return price
        except Exception as e:
            print(f"CCXT {exchange_id} failed: {e}")
            continue
    return None


def _coingecko_price(symbol):
    coin_id = COINGECKO_IDS.get(symbol, 'bitcoin')
    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/markets"
        f"?vs_currency=usd&ids={coin_id}",
        timeout=10,
    )
    price = float(r.json()[0]["current_price"])
    print(f"Price fetched via CoinGecko: ${price:,.2f}")
    return price


def _bybit_price(symbol):
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers"
        f"?category=linear&symbol={symbol}USDT",
        timeout=10,
    )
    price = float(r.json()["result"]["list"][0]["lastPrice"])
    print(f"Price fetched via Bybit: ${price:,.2f}")
    return price


def fetch_price(symbol='BTC'):
    """Return the current last price as a float, trying each source in turn.

    Raises if every source fails (matches the previous script behaviour).
    """
    try:
        price = _ccxt_price(symbol)
        if price:
            return price
    except Exception as e:
        print(f"CCXT failed: {e}")

    try:
        return _coingecko_price(symbol)
    except Exception as e:
        print(f"CoinGecko failed: {e}")

    try:
        return _bybit_price(symbol)
    except Exception as e:
        print(f"Bybit failed: {e}")

    raise Exception("All price sources failed")


# ==========================================
# RICH TICKER (dict) — monitor dashboard
# ==========================================

def _ccxt_ticker(symbol):
    if not CCXT_AVAILABLE:
        return None
    for exchange_id in EXCHANGES:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': False,
            })
            ticker = exchange.fetch_ticker(f'{symbol}/USDT')
            return {
                "price": float(ticker['last']),
                "change_pct": float(ticker['percentage'] or 0),
                "high": float(ticker['high'] or 0),
                "low": float(ticker['low'] or 0),
                "ok": True,
                "source": exchange_id,
            }
        except Exception:
            continue
    return None


def _coingecko_ticker(symbol):
    coin_id = COINGECKO_IDS.get(symbol, 'bitcoin')
    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={coin_id}",
        timeout=10,
    )
    data = r.json()[0]
    return {
        "price": float(data["current_price"]),
        "change_pct": float(data["price_change_percentage_24h"] or 0),
        "high": float(data["high_24h"]),
        "low": float(data["low_24h"]),
        "ok": True,
        "source": "coingecko",
    }


def _bybit_ticker(symbol):
    r = requests.get(
        f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT",
        timeout=10,
    )
    data = r.json()["result"]["list"][0]
    return {
        "price": float(data["lastPrice"]),
        "change_pct": float(data["price24hPcnt"]) * 100,
        "high": float(data["highPrice24h"]),
        "low": float(data["lowPrice24h"]),
        "ok": True,
        "source": "bybit",
    }


def fetch_ticker(symbol='BTC'):
    """Return a dict with price + 24h change/high/low, or None if all fail."""
    try:
        result = _ccxt_ticker(symbol)
        if result:
            return result
    except Exception:
        pass
    try:
        return _coingecko_ticker(symbol)
    except Exception:
        pass
    try:
        return _bybit_ticker(symbol)
    except Exception:
        pass
    return None


# ==========================================
# OHLCV CANDLES — charts / daily-open lookups
# ==========================================

def fetch_ohlcv(symbol='BTC', timeframe='1h', limit=48):
    """Return raw OHLCV rows from the first exchange that responds, else None."""
    if not CCXT_AVAILABLE:
        return None
    for exchange_id in EXCHANGES:
        try:
            exchange = getattr(ccxt, exchange_id)({
                'timeout': 10000,
                'enableRateLimit': True,
            })
            ohlcv = exchange.fetch_ohlcv(f'{symbol}/USDT', timeframe=timeframe, limit=limit)
            print(f"OHLCV fetched via {exchange_id} [{symbol}/USDT]")
            return ohlcv
        except Exception as e:
            print(f"OHLCV {exchange_id} [{symbol}] failed: {e}")
            continue
    return None
