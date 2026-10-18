"""
safe_bot.py — ExtBot subclass that survives Telegram Markdown parse errors.

The bot builds ~400 Markdown messages by string concatenation, and many of
them include token names/symbols chosen by token creators. One stray "_" or
"*" makes Telegram reject the whole message with "Can't parse entities",
and most call sites swallow the exception, so the user silently gets nothing.

Rather than rewriting every message, this bot retries once with parse_mode
disabled when (and only when) Telegram reports a parse error. Formatting is
lost for that one message, but the content is delivered.
"""
import logging

from telegram.error import BadRequest
from telegram.ext import ExtBot

logger = logging.getLogger(__name__)

_PARSE_ERR_MARKERS = ("can't parse entities", "can't find end of the entity", "unsupported start tag")


def is_parse_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(m in msg for m in _PARSE_ERR_MARKERS)


class SafeMarkdownBot(ExtBot):
    async def _retry_plain(self, method, args, kwargs):
        try:
            return await method(*args, **kwargs)
        except BadRequest as e:
            if kwargs.get("parse_mode") and is_parse_error(e):
                logger.warning("Markdown parse error (%s) — resending as plain text", e)
                kwargs = dict(kwargs, parse_mode=None)
                return await method(*args, **kwargs)
            raise

    async def send_message(self, *args, **kwargs):
        return await self._retry_plain(super().send_message, args, kwargs)

    async def edit_message_text(self, *args, **kwargs):
        return await self._retry_plain(super().edit_message_text, args, kwargs)

    async def send_photo(self, *args, **kwargs):
        return await self._retry_plain(super().send_photo, args, kwargs)

    async def edit_message_caption(self, *args, **kwargs):
        return await self._retry_plain(super().edit_message_caption, args, kwargs)
