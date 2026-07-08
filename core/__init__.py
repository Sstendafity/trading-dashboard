"""
core — shared building blocks for the trading dashboard.

Import submodules directly (e.g. `from core.price_feed import fetch_price`) so
that lightweight callers (bot.py, alert_check*.py) never pull in heavy optional
dependencies such as pandas / mplfinance, which live only in core.charts.
"""
