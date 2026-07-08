"""
core.config — shared constants and tiny pure-Python helpers.

Kept dependency-free (only the stdlib `re`) so every entry point can import it,
including the cron scripts that install just `requests ccxt`.
"""

import re

# --- Financial constants ---
USD_TO_INR = 85.0
BTC_LOT_SIZE = 0.001   # 1 lot = 0.001 BTC
ETH_LOT_SIZE = 0.01    # 1 lot = 0.01 ETH

# --- GitHub sync target ---
REPO_NAME = "Sstendafity/trading-dashboard"

# --- Trade-history schema (app.py) ---
TARGET_COLS = [
    'Account', 'Date', 'Time', 'Contract', 'Side',
    'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID',
]

# Maps raw exchange side terminology onto the canonical Long/Short vocabulary.
SIDE_MAP = {
    'buy': 'Long', 'long': 'Long',
    'sell': 'Short', 'short': 'Short',
    'unknown': 'Unknown',
}

_ACCOUNT_RE = re.compile(r'^([a-zA-Z]+)(\d+)$')


def normalize_account_name(name):
    """Normalize an account label like ``A6`` -> ``A-6`` (idempotent).

    Mirrors the regex previously repeated across app.py's parsers.
    """
    return _ACCOUNT_RE.sub(r'\1-\2', str(name).strip())
