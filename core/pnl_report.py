"""
core.pnl_report — running-P&L math and the Telegram portfolio report builder.

Previously bot.py, alert_check.py and alert_check_ETH.py each carried their own
near-identical copy of `calc_running_pnl` and `build_report_msg`. They differed
only by a few parameters (lot size, account universe, an optional header line),
which are now explicit arguments.

Pure Python — safe to import from the lightweight cron scripts.
"""

from core.config import USD_TO_INR


def qty_to_lots(qty, lot_size):
    """Convert a raw coin quantity into whole lots."""
    return round((qty or 0) / lot_size)


def calc_running_pnl(order, current_price, usd_to_inr=USD_TO_INR):
    """Return (running_usd, running_inr) for one open position at `current_price`."""
    side = order.get("side", "Buy")
    entry = order.get("entry_price", 0) or 0
    qty = order.get("qty", 0) or 0

    if side == "Buy":
        running_usd = (current_price - entry) * qty
    else:
        running_usd = (entry - current_price) * qty

    return running_usd, running_usd * usd_to_inr


def build_report_msg(orders, current_price, all_accounts, lot_size,
                     header=None, usd_to_inr=USD_TO_INR):
    """Build the HTML portfolio report used by the bot and the cron alert scripts.

    Parameters preserve the previous per-script behaviour exactly:
      * all_accounts — the account universe used for the "Idle Accounts" line
      * lot_size     — coin-per-lot for the lots display
      * header       — optional first line (e.g. "BTC Report"); omitted when None
    """
    total_usd = 0
    total_profit = 0
    total_loss = 0
    total_inr = 0
    profit_count = 0
    loss_count = 0
    buy_qty = 0
    sell_qty = 0
    order_pnls = []

    active_accounts = {o.get("account") for o in orders}
    inactive_accounts = [a for a in all_accounts if a not in active_accounts]

    for o in orders:
        running_usd, running_inr = calc_running_pnl(o, current_price, usd_to_inr)
        total_usd += running_usd
        total_inr += running_inr
        if running_inr > 0:
            profit_count += 1
            total_profit += running_inr
        elif running_inr < 0:
            loss_count += 1
            total_loss += running_inr
        order_pnls.append((o, running_usd, running_inr))
        if o.get("side") == "Buy":
            buy_qty += o.get("qty", 0) or 0
        else:
            sell_qty += o.get("qty", 0) or 0

    order_pnls.sort(key=lambda x: x[2], reverse=True)

    lines = []
    for o, running_usd, running_inr in order_pnls:
        side_emoji = "🟢" if o.get("side") == "Buy" else "🔴"
        pnl_sign = "+" if running_inr >= 0 else ""
        lines.append(
            f"  {side_emoji} <b>{o.get('account')}</b> "
            f"@ ${o.get('entry_price', 0):,.1f} | "
            f"{qty_to_lots(o.get('qty', 0), lot_size)} lots "
            f"→ <code>{pnl_sign}₹{running_inr:,.0f}</code>"
        )

    total_sign = "+" if total_inr >= 0 else ""

    msg = ""
    if header:
        msg += f"{header}\n"
    msg += (
        f"<b>CP</b>: <code>${current_price:,.1f}</code>\n"
        f"P: {profit_count} | <code>{total_sign}₹{total_profit:,.0f}</code>\n"
        f"L: {loss_count} | <code>{total_sign}₹{total_loss:,.0f}</code>\n"
        f"<b>T</b>: <code>{total_sign}₹{total_inr:,.0f}</code>\n"
        f"BQ: {qty_to_lots(buy_qty, lot_size)} lots\n"
        f"SQ: {qty_to_lots(sell_qty, lot_size)} lots\n"
        f"\n"
    )
    msg += "\n".join(lines)
    msg += (
        f"\n\n"
        f"Total Orders: {len(orders)}\n"
        f"Idle Accounts ({len(inactive_accounts)}): "
        f"{', '.join(inactive_accounts) if inactive_accounts else 'None'}"
    )
    return msg
