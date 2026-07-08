"""
alert_check.py — BTC position alert check.

Runs via GitHub Actions cron. All logic lives in core.position_alert; this file
just supplies the BTC-specific parameters.
"""

from core.position_alert import run_alert_check


def main():
    run_alert_check(
        symbol="BTC",
        lot_size=0.001,
        alert_state_db="alert_state_btc.json",
    )


if __name__ == "__main__":
    main()
