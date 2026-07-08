"""
core.telegram — thin, token-parameterized wrappers over the Telegram Bot API.

Consolidates the sendMessage / sendPhoto / getUpdates HTTP calls that were
duplicated across bot.py, alert_check.py, alert_check_ETH.py and send_chart.py.
Callers pass their own bot token and chat id(s); no module-level secrets here.

Only depends on `requests`.
"""

import requests

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _url(token, method):
    return API_BASE.format(token=token, method=method)


def send_message(token, chat_id, text, timeout=10):
    """Send an HTML message to a single chat. Returns True on success."""
    try:
        r = requests.post(
            _url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=timeout,
        )
        if not r.ok:
            print(f"Failed to send to chat {chat_id}: {r.text}")
        return r.ok
    except Exception as e:
        print(f"Error sending to chat {chat_id}: {e}")
        return False


def send_message_to_all(token, chat_ids, text, timeout=10):
    """Send the same message to every chat id. Returns True only if all succeed."""
    success = True
    for chat_id in chat_ids:
        if not send_message(token, chat_id, text, timeout=timeout):
            success = False
    return success


def send_photo(token, chat_id, image_bytes, filename="chart.png", caption=None, timeout=30):
    """Send a PNG photo (optionally captioned) to one chat. Returns the response."""
    data = {"chat_id": chat_id}
    if caption is not None:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    return requests.post(
        _url(token, "sendPhoto"),
        data=data,
        files={"photo": (filename, image_bytes, "image/png")},
        timeout=timeout,
    )


def get_updates(token, offset=None, timeout=10, limit=10):
    """Long-poll getUpdates. Returns the `result` list (empty on any error)."""
    params = {"timeout": 0, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(_url(token, "getUpdates"), params=params, timeout=timeout)
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        print(f"getUpdates failed: {e}")
    return []
