"""initData / Login Widget validation. No network, no Telegram."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from telegram_auth import (
    TelegramAuthError,
    issue_session,
    read_session,
    validate_init_data,
    validate_login_widget,
)

TOKEN = "123456:TEST-DUMMY-TOKEN"


def _sign_init(fields: dict, token: str = TOKEN) -> str:
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def _user(uid=42, username="neo") -> str:
    return json.dumps({"id": uid, "username": username, "first_name": "Neo"}, separators=(",", ":"))


def test_init_data_accepts_a_fresh_signed_payload():
    now = 1_700_000_000
    raw = _sign_init({
        "auth_date": str(now),
        "query_id": "AAE",
        "user": _user(),
    })
    user = validate_init_data(raw, TOKEN, max_age_s=3600, now=now + 10)
    assert user["id"] == 42
    assert user["username"] == "neo"


def test_init_data_includes_signature_field_in_the_check_string():
    now = 1_700_000_000
    raw = _sign_init({
        "auth_date": str(now),
        "query_id": "AAE",
        "signature": "deadbeef",
        "user": _user(7, "ada"),
    })
    user = validate_init_data(raw, TOKEN, max_age_s=60, now=now)
    assert user["id"] == 7


def test_init_data_rejects_tampered_user():
    now = 1_700_000_000
    raw = _sign_init({"auth_date": str(now), "query_id": "AAE", "user": _user(1)})
    # Flip the signed user id without recomputing the hash.
    tampered = raw.replace("id%22%3A1", "id%22%3A2") if "id%22%3A1" in raw else raw.replace('"id":1', '"id":2')
    assert tampered != raw
    with pytest.raises(TelegramAuthError):
        validate_init_data(tampered, TOKEN, max_age_s=60, now=now)


def test_init_data_rejects_stale_auth_date():
    auth_date = 1_700_000_000
    raw = _sign_init({"auth_date": str(auth_date), "query_id": "AAE", "user": _user()})
    with pytest.raises(TelegramAuthError, match="stale"):
        validate_init_data(raw, TOKEN, max_age_s=60, now=auth_date + 120)


def test_init_data_rejects_wrong_token():
    now = 1_700_000_000
    raw = _sign_init({"auth_date": str(now), "user": _user()})
    with pytest.raises(TelegramAuthError):
        validate_init_data(raw, "999:OTHER", max_age_s=60, now=now)


def _sign_widget(fields: dict, token: str = TOKEN) -> dict:
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(token.encode()).digest()
    fields = dict(fields)
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return fields


def test_login_widget_and_session_round_trip():
    now = 1_700_000_000
    payload = _sign_widget({
        "id": "42",
        "first_name": "Neo",
        "username": "neo",
        "auth_date": str(now),
    })
    # The widget callback hands numbers, not strings, for id and auth_date.
    payload["id"] = int(payload["id"])
    payload["auth_date"] = int(payload["auth_date"])
    user = validate_login_widget(payload, TOKEN, max_age_s=3600, now=now + 5)
    assert user["id"] == 42
    token = issue_session(user["id"], TOKEN, ttl_s=100, now=now)
    assert read_session(token, TOKEN, now=now + 50) == 42
    with pytest.raises(TelegramAuthError):
        read_session(token, TOKEN, now=now + 200)
    with pytest.raises(TelegramAuthError):
        read_session(token + "ff", TOKEN, now=now)
