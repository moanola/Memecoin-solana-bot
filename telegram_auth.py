"""
telegram_auth.py — Telegram Mini App initData and Login Widget checks.

Pure functions. No network, no bot import. Algorithms match Telegram's docs:

  Mini App:  https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
  Login Widget: https://core.telegram.org/widgets/login#checking-authorization

The Mini App secret is HMAC_SHA256(bot_token, key="WebAppData").
The Login Widget secret is SHA256(bot_token).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    """initData or login payload failed validation."""


def _hmac_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _check_hash(calculated: str, received: str) -> None:
    if not received or len(calculated) != len(received):
        raise TelegramAuthError("bad hash")
    if not hmac.compare_digest(calculated, received):
        raise TelegramAuthError("bad hash")


def _check_auth_date(auth_date: int, max_age_s: int, now: float | None) -> None:
    current = time.time() if now is None else now
    if auth_date <= 0 or current - auth_date > max_age_s or auth_date > current + 30:
        raise TelegramAuthError("stale auth_date")


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_s: int = 86400,
    now: float | None = None,
) -> dict:
    """Validate Mini App initData. Returns the Telegram user object.

    Every field except `hash` is part of the data-check-string (including the
    newer `signature` field, when the client sends one).
    """
    if not init_data or not bot_token:
        raise TelegramAuthError("missing initData")
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise TelegramAuthError("malformed initData") from exc
    received = pairs.pop("hash", None)
    if not received:
        raise TelegramAuthError("missing hash")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    _check_hash(_hmac_hex(secret, data_check), received)
    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except ValueError as exc:
        raise TelegramAuthError("bad auth_date") from exc
    _check_auth_date(auth_date, max_age_s, now)
    raw_user = pairs.get("user")
    if not raw_user:
        raise TelegramAuthError("missing user")
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise TelegramAuthError("bad user") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise TelegramAuthError("missing user id")
    try:
        user["id"] = int(user["id"])
    except (TypeError, ValueError) as exc:
        raise TelegramAuthError("bad user id") from exc
    return user


def _widget_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def validate_login_widget(
    data: dict,
    bot_token: str,
    max_age_s: int = 86400,
    now: float | None = None,
) -> dict:
    """Validate a Telegram Login Widget payload. Returns {id, username, first_name}."""
    if not isinstance(data, dict) or not bot_token:
        raise TelegramAuthError("missing login payload")
    received = data.get("hash")
    if not received or not isinstance(received, str):
        raise TelegramAuthError("missing hash")
    fields = {
        k: v for k, v in data.items()
        if k != "hash" and v is not None and v != ""
    }
    data_check = "\n".join(f"{k}={_widget_value(fields[k])}" for k in sorted(fields))
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    _check_hash(_hmac_hex(secret, data_check), received)
    try:
        auth_date = int(fields.get("auth_date") or 0)
        uid = int(fields["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthError("bad login fields") from exc
    _check_auth_date(auth_date, max_age_s, now)
    return {
        "id": uid,
        "username": fields.get("username") or "",
        "first_name": fields.get("first_name") or "",
    }


def issue_session(uid: int, bot_token: str, ttl_s: int = 7 * 24 * 3600, now: float | None = None) -> str:
    """HMAC session for clients that authenticated via the Login Widget."""
    current = int(time.time() if now is None else now)
    exp = current + ttl_s
    msg = f"{int(uid)}.{exp}"
    sig = _hmac_hex(bot_token.encode("utf-8"), msg)
    return f"{msg}.{sig}"


def read_session(token: str, bot_token: str, now: float | None = None) -> int:
    """Return the user id from a session token, or raise TelegramAuthError."""
    if not token or not bot_token or token.count(".") != 2:
        raise TelegramAuthError("bad session")
    uid_s, exp_s, sig = token.split(".")
    msg = f"{uid_s}.{exp_s}"
    expect = _hmac_hex(bot_token.encode("utf-8"), msg)
    _check_hash(expect, sig)
    try:
        exp = int(exp_s)
        uid = int(uid_s)
    except ValueError as exc:
        raise TelegramAuthError("bad session") from exc
    current = time.time() if now is None else now
    if exp < current:
        raise TelegramAuthError("expired session")
    return uid
