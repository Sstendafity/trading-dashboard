"""
core.charts — dark-themed candlestick chart rendering for Telegram.

Shared by send_chart.py (hourly cron) and pages/monitor.py (on-demand button),
which previously carried byte-identical copies of this renderer.

Imports pandas / mplfinance / matplotlib, so ONLY import this module from
callers that install those dependencies (the chart workflows and the Streamlit
app) — never from the lightweight cron alert scripts.
"""

import io

import mplfinance as mpf
import matplotlib.pyplot as plt


def fmt_volume(vol, price):
    """Format a volume figure as USD notional, e.g. '12.34M' or '567.8K'."""
    vol_usd = vol * price
    if vol_usd >= 1_000_000:
        return f"{vol_usd / 1_000_000:,.2f}M"
    else:
        return f"{vol_usd / 1_000:,.1f}K"


def build_candlestick_chart(df, title):
    """Render a candlestick+volume chart and return it as PNG bytes."""
    mc = mpf.make_marketcolors(
        up='#00e676', down='#ff1744',
        edge='inherit', wick='inherit',
        volume={'up': '#00e676', 'down': '#ff1744'},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, base_mpf_style='nightclouds',
        gridstyle='--', gridcolor='#2a2a4a',
        facecolor='#0f0f23', figcolor='#0f0f23',
        y_on_right=True,
        rc={'axes.labelcolor': '#aaaaaa', 'xtick.color': '#aaaaaa', 'ytick.color': '#aaaaaa'},
    )
    fig, axes = mpf.plot(
        df, type='candle', style=style,
        ylabel='', volume=True, ylabel_lower='',
        figsize=(14, 8), returnfig=True, tight_layout=True,
        datetime_format='%m-%d %H:%M', xrotation=30,
    )
    axes[0].set_title(title, color='#cccccc', fontsize=10,
                      fontfamily='monospace', loc='center', pad=10)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='#0f0f23', edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()
