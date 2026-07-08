"""
alert_check_ETH.py — ETH position alert check.

Runs via GitHub Actions cron. All logic lives in core.position_alert; this file
just supplies the ETH-specific parameters.
"""

from core.position_alert import run_alert_check


def main():
    run_alert_check(
        symbol="ETH",
        lot_size=0.01,
        alert_state_db="alert_state_eth.json",
    )


if __name__ == "__main__":
    main()
