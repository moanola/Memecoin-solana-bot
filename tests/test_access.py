from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from access import access_allowed, make_gate


def test_access_allowed_rules():
    users = {1: {"access_approved": True}, 2: {}}
    assert access_allowed(1, users, set(), True)
    assert not access_allowed(2, users, set(), True)
    assert not access_allowed(3, users, set(), True)
    assert access_allowed(3, users, {3}, True)        # admin
    assert access_allowed(3, users, set(), False)     # gate disabled
    assert 3 not in users                              # never creates records


def _gate(users, admins=frozenset()):
    return make_gate(lambda: users, lambda: set(admins), lambda: True, lambda: "admin")


def _msg_update(uid):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid), callback_query=None,
                           effective_message=msg), msg


def _cb_update(uid, data):
    q = SimpleNamespace(data=data, answer=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid), callback_query=q,
                           effective_message=None), q


async def test_gate_blocks_unapproved_message():
    users = {}
    handler = AsyncMock()
    upd, msg = _msg_update(42)
    await _gate(users)(handler)(upd, None)
    handler.assert_not_called()
    msg.reply_text.assert_awaited_once()
    assert users == {}


async def test_gate_allows_approved_and_admin():
    users = {7: {"access_approved": True}}
    handler = AsyncMock()
    await _gate(users)(handler)(_msg_update(7)[0], None)
    await _gate(users, {8})(handler)(_msg_update(8)[0], None)
    assert handler.await_count == 2


async def test_gate_blocks_unapproved_callback_with_alert():
    handler = AsyncMock()
    upd, q = _cb_update(42, "buy_SomeMint")
    await _gate({})(handler)(upd, None)
    handler.assert_not_called()
    assert q.answer.await_args.kwargs.get("show_alert") is True


async def test_gate_passes_access_callbacks_through():
    handler = AsyncMock()
    upd, _ = _cb_update(42, "access_approve_123")
    await _gate({})(handler)(upd, None)
    handler.assert_awaited_once()


def test_every_handler_is_gated_except_start():
    import sol_trading_bot as bot
    from telegram.ext import Application, CommandHandler

    app = Application.builder().token("123456:TEST-DUMMY-TOKEN").build()
    bot._register_handlers(app)
    handlers = [h for group in app.handlers.values() for h in group]
    assert handlers
    for h in handlers:
        is_start = isinstance(h, CommandHandler) and "start" in h.commands
        assert getattr(h.callback, "__access_gated__", False) != is_start, h


async def test_start_does_not_create_record_for_unapproved(monkeypatch):
    import sol_trading_bot as bot

    monkeypatch.setattr(bot, "ACCESS_CONTROL_ENABLED", True)
    uid = 555123
    bot.users.pop(uid, None)
    bot._pending_access.pop(uid, None)
    user = SimpleNamespace(id=uid, username="new_user", first_name="New", full_name="New User")
    upd = SimpleNamespace(effective_user=user, message=SimpleNamespace(reply_text=AsyncMock()),
                          effective_chat=SimpleNamespace(type="private"))
    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), args=[])
    try:
        await bot.cmd_start(upd, ctx)
        assert uid not in bot.users
        assert uid in bot._pending_access
        upd.message.reply_text.assert_awaited()
    finally:
        bot.users.pop(uid, None)
        bot._pending_access.pop(uid, None)
