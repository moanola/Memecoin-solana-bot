from telegram.error import BadRequest

import safe_bot


async def test_retries_plain_on_parse_error(monkeypatch):
    calls = []

    async def fake_send(self, *args, **kwargs):
        calls.append(kwargs.get("parse_mode"))
        if kwargs.get("parse_mode"):
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 5")
        return "sent"

    monkeypatch.setattr(safe_bot.ExtBot, "send_message", fake_send)
    bot = safe_bot.SafeMarkdownBot(token="123456:TEST-DUMMY-TOKEN")
    assert await bot.send_message(chat_id=1, text="*bad_", parse_mode="Markdown") == "sent"
    assert calls == ["Markdown", None]
