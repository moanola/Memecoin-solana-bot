"""
access.py — single access-control gate for every Telegram handler.

Pure logic (access_allowed) is separated from the PTB wrapper (make_gate) so
it can be unit-tested without Telegram.
"""
import functools
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Callback prefixes that must reach the handler even for unapproved users,
# because the handler itself enforces admin-only access (approve/deny buttons).
PASSTHROUGH_CALLBACK_PREFIXES = ("access_approve_", "access_deny_")


def access_allowed(uid: int, users: dict, admin_ids, enabled: bool) -> bool:
    """True if uid may use the bot. Never creates a user record."""
    if not enabled:
        return True
    if uid in admin_ids:
        return True
    return bool((users.get(uid) or {}).get("access_approved"))


def make_gate(
    get_users: Callable[[], dict],
    get_admin_ids: Callable[[], set],
    is_enabled: Callable[[], bool],
    admin_username: Callable[[], str],
):
    """Return a decorator that wraps an async PTB handler with the access gate."""

    def gate(handler):
        @functools.wraps(handler)
        async def wrapper(update, ctx, *args, **kwargs):
            u = getattr(update, "effective_user", None)
            if u is None:
                return None  # channel posts etc. — every handler ignored these anyway
            if access_allowed(u.id, get_users(), get_admin_ids(), is_enabled()):
                return await handler(update, ctx, *args, **kwargs)

            q = getattr(update, "callback_query", None)
            if q is not None:
                data = q.data or ""
                if data.startswith(PASSTHROUGH_CALLBACK_PREFIXES):
                    # Handler checks is_admin itself (non-admins get nothing).
                    return await handler(update, ctx, *args, **kwargs)
                try:
                    await q.answer("🔒 Access required. Send /start to request access.", show_alert=True)
                except Exception:
                    pass
                return None

            msg = getattr(update, "effective_message", None)
            if msg is not None:
                try:
                    await msg.reply_text(
                        "🔒 Access required. Send /start in a private chat to request access, "
                        "or contact @" + admin_username() + "."
                    )
                except Exception:
                    pass
            return None

        wrapper.__access_gated__ = True
        return wrapper

    return gate
