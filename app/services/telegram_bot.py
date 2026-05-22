"""Helpers for calling the Telegram Bot API (sync, no external deps)."""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_TG_BASE = "https://api.telegram.org/bot{token}/{method}"


def _call(bot_token: str, method: str, payload: dict) -> dict:
    url = _TG_BASE.format(token=bot_token, method=method)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            result = json.loads(body)
        except Exception:
            result = {"ok": False, "description": body.decode("utf-8", errors="replace")}
    return result


def create_invoice_link(
    bot_token: str,
    title: str,
    description: str,
    payload: str,
    stars_amount: int,
) -> str:
    """Create a Telegram Stars invoice link.

    `stars_amount` is the price in Stars (currency XTR).
    Returns the invoice URL string.
    """
    result = _call(
        bot_token,
        "createInvoiceLink",
        {
            "title": title,
            "description": description,
            "payload": payload,
            "currency": "XTR",           # Telegram Stars
            "prices": [{"label": title, "amount": stars_amount}],
        },
    )
    if not result.get("ok"):
        raise RuntimeError(f"Telegram createInvoiceLink error: {result.get('description', result)}")
    return result["result"]


def answer_pre_checkout_query(bot_token: str, query_id: str, ok: bool, error_message: str | None = None) -> None:
    """Must be called within 10 s of receiving a pre_checkout_query."""
    payload: dict = {"pre_checkout_query_id": query_id, "ok": ok}
    if not ok and error_message:
        payload["error_message"] = error_message
    result = _call(bot_token, "answerPreCheckoutQuery", payload)
    if not result.get("ok"):
        logger.warning("answerPreCheckoutQuery failed: %s", result)


def send_message(bot_token: str, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    """Send a text message; failures are logged but not raised."""
    result = _call(
        bot_token,
        "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
    )
    if not result.get("ok"):
        logger.error("sendMessage failed for chat_id=%s: %s", chat_id, result)


def set_webhook(bot_token: str, webhook_url: str, secret_token: str = "") -> dict:
    """Register (or replace) the bot webhook. Call once after deploy."""
    payload: dict = {"url": webhook_url, "allowed_updates": ["message", "pre_checkout_query", "callback_query"]}
    if secret_token:
        payload["secret_token"] = secret_token
    return _call(bot_token, "setWebhook", payload)


def delete_webhook(bot_token: str) -> dict:
    """Remove the bot webhook (reverts to long-polling mode)."""
    return _call(bot_token, "deleteWebhook", {})


def get_webhook_info(bot_token: str) -> dict:
    """Return current webhook status from Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def set_my_commands(bot_token: str, commands: list[dict]) -> dict:
    """Register bot commands so they appear in Telegram's menu.

    Each command is {"command": "whoami", "description": "Ver mi ID de Telegram"}.
    """
    return _call(bot_token, "setMyCommands", {"commands": commands})
