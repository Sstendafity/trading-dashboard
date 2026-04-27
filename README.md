# 📊 Trading Dashboard

A personal multi-account BTC trading dashboard built with Streamlit, featuring live price monitoring, P&L tracking, Telegram alerts, and hourly candlestick chart notifications.

---

## Features

### 📈 Report Page (`app.py`)
- Upload and process trade history from multiple exchanges (Delta, CoinSwitch, Pi42, CoinDCX, MDX, ZebPay)
- Supports multiple CSV formats per exchange
- Normalized account naming (A-1 through A-15)
- Master trade history stored in `trade_history.csv`

### ⚡ Live Order Monitor (`pages/monitor.py`)
- Real-time BTC price via CCXT (OKX → KuCoin → Gate.io → HTX → CoinGecko → Bybit)
- Auto-refresh every 30 seconds using `@st.fragment`
- Multi-position tracking with P&L in USD and INR
- Liquidation risk progress bar per position
- Position cards with Edit / Close Position
- Summary table sorted by running P&L
- **Projection feature** — simulate P&L at any price
- **Send Report Now** button — instant Telegram portfolio report
- **Send Chart Now** button — instant BTC candlestick chart to Telegram
- Quantity displayed in lots (1 lot = 0.001 BTC)

### 🤖 Telegram Bot (`bot.py`)
Runs 24/7 on Railway. Supports:

| Command | Description |
|---|---|
| `/report` | Instant portfolio report with current P&L |
| `/setuppricealert` | Set up price interval alerts (e.g. every $500) |
| `/stoppricealert` | Stop price interval alerts |

### 🔔 GitHub Actions Alerts (`alert_check.py`)
Runs every 15 minutes via cron-job.org:
- Per-position % move alerts (configurable threshold per position)
- Liquidation price alerts
- 15-minute portfolio report
- `/report` command support

### 📉 Hourly Chart (`send_chart.py`)
Runs every hour via cron-job.org:
- Fetches last 24 hourly OHLCV candles
- Generates dark-themed candlestick chart with volume
- Sends text summary + chart image to Telegram

---

## Tech Stack

- **Frontend:** Streamlit (Python)
- **Price Data:** CCXT, CoinGecko, Bybit REST API
- **Alerts:** GitHub Actions + cron-job.org
- **Bot:** Python polling bot on Railway
- **Storage:** GitHub repo (JSON files for state)
- **Notifications:** Telegram Bot API

---

## Project Structure

```
trading-dashboard/
├── app.py                          # Report page — trade history upload & analysis
├── auth.py                         # Shared password authentication
├── bot.py                          # Telegram bot (Railway)
├── alert_check.py                  # GitHub Actions alert script
├── send_chart.py                   # GitHub Actions hourly chart script
├── trade_history.csv               # Master trade database
├── running_orders.json             # Open positions
├── alert_state.json                # Alert dedup state
├── price_alert_configs.json        # Price interval alert state
├── requirements.txt
├── pages/
│   └── monitor.py                  # Live Order Monitor page
└── .github/workflows/
    ├── price_alert.yml             # 15-min alert workflow
    └── hourly_chart.yml            # Hourly chart workflow
```

---

## Setup

### 1. Fork & Clone

```bash
git clone https://github.com/YOUR_USERNAME/trading-dashboard.git
cd trading-dashboard
```

### 2. Streamlit Cloud

1. Go to [streamlit.io/cloud](https://streamlit.io/cloud) → New app → select your repo
2. Set **Main file path:** `app.py`
3. Add **Secrets** (Settings → Secrets):

```toml
APP_PASSWORD = "your_password"
GITHUB_TOKEN = "your_github_pat"
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
TELEGRAM_CHAT_ID_2 = "optional_second_chat_id"
```

### 3. GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions → add:

| Secret | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `TELEGRAM_CHAT_ID_2` | Optional second chat ID |

### 4. cron-job.org (Free)

Sign up at [cron-job.org](https://cron-job.org) and create **two jobs**:

**Job 1 — 15-min alerts:**
```
URL: https://api.github.com/repos/YOUR_USERNAME/trading-dashboard/actions/workflows/price_alert.yml/dispatches
Method: POST
Headers:
  Authorization: Bearer YOUR_PAT_TOKEN
  Accept: application/vnd.github+json
  Content-Type: application/json
Body: {"ref":"main"}
Schedule: Every 15 minutes
```

**Job 2 — Hourly chart:**
```
URL: https://api.github.com/repos/YOUR_USERNAME/trading-dashboard/actions/workflows/hourly_chart.yml/dispatches
Method: POST
Headers: (same as above)
Body: {"ref":"main"}
Schedule: Every 1 hour
```

### 5. Railway (Telegram Bot)

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Select your repo
3. Set **Start Command:** `python bot.py`
4. Add environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TELEGRAM_CHAT_ID_2`
   - `GITHUB_TOKEN`
5. **Disable auto-deploy** (Settings → Source → Disconnect branch) to prevent Railway from restarting on every GitHub push

### 6. Trade History Data

The dashboard processes trade history CSVs from multiple exchanges. To use with your own data, replace `trade_history.csv` with your own exports. Supported formats:
- Delta Exchange (CSV export)
- CoinSwitch
- Pi42
- CoinDCX
- MDX
- ZebPay (`TXNHISTORY_STATEMENT`)

---

## Accounts

Accounts are named A-1 through A-15 and grouped by exchange:

| Accounts | Exchange |
|---|---|
| A-1 to A-6 | Delta |
| A-7 to A-11 | CoinSwitch |
| A-12 | Pi42 |
| A-13 | CoinDCX |
| A-14 | MDX |
| A-15 | ZebPay |

---

## Requirements

```
streamlit
pandas
requests
ccxt
PyGithub
streamlit-autorefresh
mplfinance
matplotlib
```

---

## License

MIT — free to use and modify for personal or commercial use.
