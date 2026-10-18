"""
webapi.py — paper-trading terminal API.

Runs inside the bot process (see sol_trading_bot.main) on the same asyncio
loop, so handlers call the live in-memory state and the existing buy/sell
functions. Nothing here signs a transaction or touches a private key.

Every route except /health and POST /api/auth/login requires a verified
Telegram identity and the same access gate as access.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import sol_trading_bot as bot
from telegram_auth import (
    TelegramAuthError,
    issue_session,
    read_session,
    validate_init_data,
    validate_login_widget,
)

logger = logging.getLogger(__name__)

_feed: dict[str, dict] = {}
_feed_lock = asyncio.Lock()
_feed_refresh_task: asyncio.Task | None = None
_last_record_ts = 0.0
_last_refresh_ts = 0.0
FEED_CAP = 80
SCAN_CAP = 24
# sniper_job record_scans every 5 minutes. The old 90s loop started a second
# full scan and raced that job. The loop below only backfills an empty feed.


def _max_age() -> int:
    try:
        return int(os.getenv("INITDATA_MAX_AGE_S", "86400"))
    except ValueError:
        return 86400


def _origins() -> list[str]:
    raw = os.getenv("WEBAPP_ORIGIN", "")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def _origin_allowed(origin: str | None) -> bool:
    allowed = _origins()
    if not origin:
        return True  # non-browser clients and tests
    if not allowed:
        return False
    return origin.rstrip("/") in allowed


class LoginBody(BaseModel):
    id: int
    auth_date: int
    hash: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


class BuyBody(BaseModel):
    contract: str = Field(min_length=8, max_length=128)
    amount_usd: float = Field(gt=0, le=10_000)
    preset: str | None = None
    tp_x: float | None = None
    tp_pct: float | None = None
    invalidation_pct: float | None = None
    time_stop_min: float | None = None

    @field_validator("preset")
    @classmethod
    def _known_preset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip().lower()
        if not name:
            return None
        if name not in {"scalp", "standard", "runner"}:
            raise ValueError("Unknown exit preset. Choose scalp, standard, or runner.")
        return name


class SellBody(BaseModel):
    contract: str = Field(min_length=8, max_length=128)
    percent: float | None = Field(default=None, gt=0, le=100)
    amount_usd: float | None = Field(default=None, gt=0)


class ApexToggle(BaseModel):
    enabled: bool


class VaultBody(BaseModel):
    action: str  # fund | withdraw
    amount: float | None = None
    all: bool = False


class SplitBody(BaseModel):
    percent: int = Field(ge=0, le=100)


def record_scan(contract: str, info: dict, sc: dict, source: str = "sniper") -> None:
    """Store one sniper-scan result for the terminal feed. Safe to call from sniper_job."""
    global _last_record_ts
    if not contract or not isinstance(info, dict) or not isinstance(sc, dict):
        return
    _feed[contract] = _public_token(contract, info, sc, source=source)
    _last_record_ts = time.time()
    if len(_feed) > FEED_CAP:
        oldest = sorted(_feed.values(), key=lambda e: e.get("ts") or 0)[: len(_feed) - FEED_CAP]
        for entry in oldest:
            _feed.pop(entry.get("contract", ""), None)


def _num(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _public_token(contract: str, info: dict, sc: dict, ai: dict | None = None, source: str = "sniper") -> dict:
    rug_risks = info.get("rug_risks") or []
    out = {
        "contract": contract,
        "symbol": info.get("symbol") or "?",
        "name": info.get("name") or "",
        "chain": info.get("chain") or "",
        "dex": info.get("dex") or "",
        "pair": info.get("pair_addr") or "",
        "price": _num(info.get("price")),
        "mc": _num(info.get("mc")),
        "liq": _num(info.get("liq")),
        "liq_pct": _num(info.get("liq_pct")),
        "vol_m5": _num(info.get("vol_m5")),
        "vol_h1": _num(info.get("vol_h1")),
        "vol_h24": _num(info.get("vol_h24")),
        "ch_m5": _num(info.get("ch_m5")),
        "ch_h1": _num(info.get("ch_h1")),
        "ch_h24": _num(info.get("ch_h24")),
        "age_h": info.get("age_h"),
        "buy_pct": info.get("buy_pct"),
        "buys_h1": info.get("buys_h1"),
        "sells_h1": info.get("sells_h1"),
        "image": info.get("token_image") or "",
        "twitter": info.get("twitter") or "",
        "telegram": info.get("telegram") or "",
        "website": info.get("website") or "",
        "score": int(sc.get("score") or 0),
        "verdict": sc.get("verdict") or "",
        "flags": list(sc.get("flags") or [])[:6],
        "warnings": list(sc.get("warnings") or [])[:4],
        "strengths": list(sc.get("strengths") or [])[:5],
        "rug": {
            "no_mint": info.get("no_mint"),
            "no_freeze": info.get("no_freeze"),
            "lp_burn": info.get("lp_burn"),
            "top10_pct": (round(float(info["top10_pct"]), 1) if info.get("top10_pct") is not None else None),
            "insider_pct": info.get("insider_pct"),
            "risks": [str(r) for r in rug_risks][:8],
            "rate_limited": bool(info.get("rc_rate_limited")),
        },
        "source": source,
        "ts": time.time(),
        "paper": True,
        "quote_symbol": info.get("quote_symbol") or "",
        "quote_kind": info.get("quote_kind") or "",
        "pair_label": info.get("pair_label") or "",
        "price_indicative": bool(info.get("price_indicative")),
        "price_derived": bool(info.get("price_derived")),
        "multi_hop_txs": info.get("multi_hop_txs"),
        "fee_sweep": bool(info.get("fee_sweep")),
        "copycat_role": info.get("copycat_role") or "",
        "copycat_label": info.get("copycat_label") or "",
        "copycat_original_symbol": info.get("copycat_original_symbol") or "",
        "launch_group_size": info.get("launch_group_size"),
        "launch_group_sold_pct": info.get("launch_group_sold_pct"),
        "launch_group_confident": bool(info.get("launch_group_confident")),
        "dev_cashout": bool(info.get("dev_cashout")),
        "dev_cashout_reason": info.get("dev_cashout_reason") or "",
        "rug_memory_note": info.get("rug_memory_note") or "",
        "holders_per_hour": info.get("holders_per_hour"),
        "holder_retention_pct": info.get("holder_retention_pct"),
        "kol_exit_note": info.get("kol_exit_note") or "",
        "helius": bool(os.getenv("HELIUS_API_KEY")),
        "pf_curve": info.get("pf_curve"),
        "pf_graduated": bool(info.get("pf_graduated")),
        "pf_replies": info.get("pf_replies") or 0,
        "pf_dev_pct": info.get("pf_dev_pct"),
        "virtual_sol_reserves": info.get("virtual_sol_reserves") or info.get("pf_virtual_sol_lamports"),
    }
    if ai:
        out["ai"] = {
            "verdict": ai.get("verdict"),
            "confidence": ai.get("confidence"),
            "suggested_amount": ai.get("suggested_amount"),
            "thesis": ai.get("thesis") or "",
            "red_flags": list(ai.get("red_flags") or [])[:4],
            "green_flags": list(ai.get("green_flags") or [])[:4],
            "rug_risk": ai.get("rug_risk"),
            "momentum": ai.get("momentum"),
            "social_score": ai.get("social_score"),
        }
    return out


def _iso(v):
    """UTC ISO-8601 with a Z suffix. Naive values are local wall time."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.astimezone()
        v = v.astimezone(timezone.utc).replace(microsecond=0)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _auth_header_user(authorization: str | None, init_data_header: str | None) -> dict:
    token = bot.BOT_TOKEN
    if not token:
        raise HTTPException(status_code=503, detail="Bot token is not configured")
    if init_data_header:
        try:
            return validate_init_data(init_data_header.strip(), token, _max_age())
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    scheme, _, value = authorization.partition(" ")
    value = value.strip()
    scheme = scheme.lower()
    try:
        if scheme == "tma" and value:
            return validate_init_data(value, token, _max_age())
        if scheme == "bearer" and value:
            uid = read_session(value, token)
            return {"id": uid}
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    raise HTTPException(status_code=401, detail="Authentication required")


def _load_user(tg_user: dict) -> tuple[int, dict]:
    uid = int(tg_user["id"])
    if not bot.user_has_access(uid):
        raise HTTPException(
            status_code=403,
            detail="Access required. Send /start to the bot and wait for admin approval.",
        )
    ud = bot.users.get(uid)
    if ud is None:
        # Admins and open-access deployments have no record until first contact.
        # user_has_access already passed, so creating the record matches /start.
        name = tg_user.get("username") or tg_user.get("first_name") or ("User" + str(uid))
        ud = bot.get_user(uid, name)
    if ud.get("admin_banned"):
        raise HTTPException(status_code=403, detail="Account suspended")
    uname = tg_user.get("username")
    if uname and ud.get("username") in (None, "", "User" + str(uid)):
        ud["username"] = uname
    return uid, ud


async def require_user(authorization: str | None = None, x_telegram_init_data: str | None = None) -> tuple[int, dict]:
    tg_user = _auth_header_user(authorization, x_telegram_init_data)
    return _load_user(tg_user)


async def current_user(
    authorization: str | None = Header(default=None),
    x_telegram_init_data: str | None = Header(default=None),
) -> tuple[int, dict]:
    return await require_user(authorization, x_telegram_init_data)


def _balance_ready(ud: dict) -> bool:
    return isinstance(ud.get("balance"), (int, float))


def _me_payload(uid: int, ud: dict) -> dict:
    balance = ud.get("balance")
    savings = _num(ud.get("savings"))
    invested = sum(_num(h.get("total_invested")) for h in (ud.get("holdings") or {}).values())
    marked = 0.0
    marked_known = True
    for contract, h in (ud.get("holdings") or {}).items():
        cached = bot._token_cache.get(contract)
        price = None
        if cached and isinstance(cached.get("data"), dict):
            price = cached["data"].get("price")
        if price:
            marked += _num(h.get("amount")) * _num(price)
        else:
            marked += _num(h.get("total_invested"))
            marked_known = False
    equity = None
    if _balance_ready(ud):
        # Cash + savings + unspent APEX vault + every open position at the live mark.
        equity = round(_num(balance) + savings + _num(ud.get("apex_vault")) + marked, 4)
    return {
        "paper": True,
        "uid": uid,
        "username": ud.get("username") or "",
        "balance": balance,
        "balance_set": _balance_ready(ud),
        "savings": round(savings, 4),
        "starting_balance": ud.get("starting_balance"),
        "realized_pnl": round(_num(ud.get("realized_pnl")), 4),
        "total_fees_paid": round(_num(ud.get("total_fees_paid")), 4),
        "open_cost": round(invested, 4),
        "equity": equity,
        "equity_uses_live_prices": marked_known,
        "apex_vault": round(_num(ud.get("apex_vault")), 4),
        "open_positions": len(ud.get("holdings") or {}),
        "quick_buy_amount": _num(ud.get("quick_buy_amount"), 100.0),
    }


def _apex_exit_view(h: dict) -> dict | None:
    """APEX positions have no manual exit plan. Show the rules the checker actually uses."""
    if (h.get("mood") or "") not in ("APEX", "AI-Sniper", "APEX-DCA"):
        return None
    sl = h.get("stop_loss_pct")
    try:
        trail = float(h.get("apex_trail_pct") or bot.APEX_TRAIL_PCT_EARLY)
    except (TypeError, ValueError):
        trail = bot.APEX_TRAIL_PCT_EARLY
    activate = bot.APEX_TRAIL_ACTIVATE_X
    partial = int(round(bot.APEX_LOCK_2X_PCT * 100))
    rules = []
    if sl:
        rules.append(f"Stop loss {float(sl):g}%")
    else:
        rules.append("Stop loss set at entry from rug risk")
    rules.append(f"Trail activates at {activate:g}×")
    rules.append(f"Trail width {round(trail * 100, 1):g}%")
    rules.append(f"Sell {partial}% at 2×")
    rules.append("Threat RED, launch-group dump, or dev cash-out closes the position")
    return {
        "stop_loss_pct": sl,
        "trail_activate_x": activate,
        "trail_pct": trail,
        "rules": rules,
    }


def _open_realized(d: dict) -> float:
    """Partial-sell PnL still sitting on open holdings. Closed rounds are in the log."""
    return sum(_num(h.get("realized_total")) for h in (d.get("holdings") or {}).values())


def _mark_holdings(d: dict) -> float:
    """Open positions at the live cached price, falling back to cost."""
    total = 0.0
    for contract, h in (d.get("holdings") or {}).items():
        price = None
        cached = bot._token_cache.get(contract)
        if cached and isinstance(cached.get("data"), dict):
            price = cached["data"].get("price")
        amount = _num(h.get("amount"))
        if price and amount:
            total += amount * _num(price)
        else:
            total += _num(h.get("total_invested"))
    return total


def _best_win_streak(logs: list) -> int:
    ordered = sorted(logs, key=lambda t: str(_iso(t.get("closed_at")) or ""))
    best = cur = 0
    for t in ordered:
        if _num(t.get("realized_pnl")) > 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


async def _position_rows(ud: dict) -> list[dict]:
    holdings = ud.get("holdings") or {}
    if not holdings:
        return []
    contracts = list(holdings.keys())
    infos = await asyncio.gather(*[bot.get_token(c) for c in contracts], return_exceptions=True)
    rows = []
    for contract, info in zip(contracts, infos):
        h = holdings.get(contract)
        if not h:
            continue
        if isinstance(info, Exception) or not info:
            info = None
        price = _num(info.get("price")) if info else 0.0
        live = bool(price)
        if not live:
            price = _num(h.get("avg_price"))
        amount = _num(h.get("amount"))
        cost = _num(h.get("total_invested"))
        value = amount * price
        pnl = value - cost
        buy_cost = _num(h.get("buy_cost")) or cost
        remain = (cost / buy_cost) if buy_cost else 1.0
        entry_fees = _num(h.get("entry_fees")) * remain
        pnl_net = pnl - entry_fees
        avg = _num(h.get("avg_price"))
        rows.append({
            "contract": contract,
            "symbol": h.get("symbol") or "?",
            "name": h.get("name") or "",
            "chain": h.get("chain") or "",
            "amount": amount,
            "avg_price": avg,
            "price": price,
            "price_live": live,
            "value": round(value, 4),
            "cost": round(cost, 4),
            "pnl": round(pnl, 4),
            "pnl_net": round(pnl_net, 4),
            "entry_fees": round(entry_fees, 4),
            "pnl_pct": round((pnl_net / cost * 100), 2) if cost else 0.0,
            "x": round(price / avg, 4) if avg else 0.0,
            "mood": h.get("mood") or "",
            "exit_plan": h.get("exit_plan"),
            "apex_exit": _apex_exit_view(h),
            "bought_at": _iso(h.get("bought_at")),
            "liq": _num(info.get("liq")) if info else _num(h.get("liq_at_buy")),
            "mc": _num(info.get("mc")) if info else 0.0,
            "image": (info or {}).get("token_image") or "",
            "ch_h1": _num((info or {}).get("ch_h1")),
        })
    rows.sort(key=lambda r: abs(r["pnl"]), reverse=True)
    return rows


def _history_rows(uid: int, limit: int) -> list[dict]:
    logs = list(bot.trade_log.get(uid) or [])
    logs.sort(key=lambda t: str(_iso(t.get("closed_at")) or ""), reverse=True)
    out = []
    for t in logs[:limit]:
        out.append({
            "symbol": t.get("symbol"),
            "contract": t.get("contract"),
            "chain": t.get("chain"),
            "invested": t.get("invested"),
            "returned": t.get("returned"),
            "realized_pnl": t.get("realized_pnl"),
            "x": t.get("x"),
            "hold_h": t.get("hold_h"),
            "reason": t.get("reason"),
            "mood": t.get("mood") or "",
            "closed_at": _iso(t.get("closed_at")),
            "bought_at": _iso(t.get("bought_at")),
            "fees_paid": t.get("fees_paid"),
        })
    return out


def _leaderboard(sort: str, me: int) -> list[dict]:
    scores = []
    for uid, d in bot.users.items():
        if d.get("balance") is None:
            continue
        logs = bot.trade_log.get(uid) or []
        if not logs:
            continue
        wins = [t for t in logs if _num(t.get("realized_pnl")) > 0]
        wr = round(len(wins) / len(logs) * 100, 1) if logs else 0.0
        pnl = sum(_num(t.get("realized_pnl")) for t in logs) + _open_realized(d)
        marked = _mark_holdings(d)
        eq = _num(d.get("balance")) + marked + _num(d.get("savings")) + _num(d.get("apex_vault"))
        start = _num(d.get("starting_balance"), 5000) or 5000
        growth = round((eq - start) / start * 100, 1) if start > 0 else 0.0
        scores.append({
            "username": d.get("username") or "trader",
            "equity": round(eq, 2),
            "pnl": round(pnl, 2),
            "win_rate": wr,
            "trades": len(logs),
            "growth": growth,
            "streak": _best_win_streak(logs),
            "is_me": uid == me,
        })
    key = {"pnl": "pnl", "wr": "win_rate"}.get(sort, "equity")
    scores.sort(key=lambda s: s[key], reverse=True)
    for i, row in enumerate(scores, start=1):
        row["rank"] = i
    return scores[:50]


def _apex_payload(uid: int, ud: dict) -> dict:
    try:
        heat = round(bot.apex_capital_heat(ud) * 100, 1)
    except Exception:
        heat = 0.0
    try:
        paused = bot.apex_is_paused(uid)
    except Exception:
        paused = False
    enabled = bool(ud.get("apex_mode"))
    # An idle vault with APEX off is not a daily-loss halt.
    halted = False
    if enabled:
        try:
            halted = bool(bot.apex_is_daily_loss_halted(ud))
        except Exception:
            halted = False
    total = int(ud.get("apex_total_trades") or 0)
    wins = int(ud.get("apex_total_wins") or 0)
    logs = [
        t for t in (bot.trade_log.get(uid) or [])
        if (t.get("mood") or "") in ("APEX", "AI-Sniper", "APEX-DCA")
    ]
    if logs and len(logs) >= total:
        total = len(logs)
        wins = sum(1 for t in logs if _num(t.get("realized_pnl")) > 0)
    if enabled and paused:
        state = "paused"
    elif enabled and halted:
        state = "halted"
    elif enabled:
        state = "on"
    else:
        state = "off"
    return {
        "paper": True,
        "enabled": enabled,
        "state": state,
        "paused": paused,
        "halted": halted,
        "vault": round(_num(ud.get("apex_vault")), 4),
        "vault_pnl": round(_num(ud.get("apex_vault_pnl")), 4),
        "vault_peak": round(_num(ud.get("apex_vault_peak")), 4),
        "profit_split": _num(ud.get("apex_vault_profit_split"), 0.5),
        "profit_sent": round(_num(ud.get("apex_vault_total_profit_sent")), 4),
        "daily_pnl": round(_num(ud.get("apex_daily_pnl")), 4),
        "heat_pct": heat,
        "deployed": round(sum(
            _num(h.get("total_invested"))
            for h in (ud.get("holdings") or {}).values()
            if (h.get("mood") or "") in ("APEX", "AI-Sniper", "APEX-DCA")
        ), 4),
        "positions": bot.apex_count_positions(ud),
        "trades": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total else None,
        "consec_losses": int(ud.get("apex_consec_losses") or 0),
        "phase": bot.apex_get_phase(ud),
        "balance": ud.get("balance"),
        "buy_amount": _num((ud.get("sniper_filters") or {}).get("buy_amount"), 20),
        "sniper_paused": bool(getattr(bot, "_admin_sniper_paused", False)),
        "mood": _cached_mood(),
    }


def _cached_mood():
    try:
        from edge.flags import market_mood
        if not market_mood():
            return None
        from edge.mood import cached
        return cached()
    except Exception:
        return None


def _set_apex(uid: int, ud: dict, enabled: bool) -> None:
    """Same field updates as the Telegram apex_toggle callback."""
    if enabled and not ud.get("apex_mode"):
        bot.apex_reset_daily(ud)
        ud["apex_mode"] = True
        ud["apex_total_trades"] = ud.get("apex_total_trades", 0)
        ud["apex_total_wins"] = ud.get("apex_total_wins", 0)
        ud["apex_consec_losses"] = ud.get("apex_consec_losses", 0)
        ud["apex_daily_pnl"] = ud.get("apex_daily_pnl", 0.0)
        ud["apex_session_start_bal"] = ud.get("apex_vault", 0.0)
    elif not enabled:
        ud["apex_mode"] = False
    bot.save_user(uid, ud)


def _fund_vault(uid: int, ud: dict, amount: float | None, take_all: bool) -> None:
    if not _balance_ready(ud):
        raise HTTPException(status_code=400, detail="Set a starting balance with /start first")
    balance = _num(ud.get("balance"))
    if take_all:
        amt = balance
    else:
        amt = _num(amount)
    if amt <= 0 or amt > balance + 0.001:
        raise HTTPException(status_code=400, detail="Amount exceeds main balance")
    amt = min(amt, balance)
    ud["balance"] = round(balance - amt, 4)
    ud["apex_vault"] = round(_num(ud.get("apex_vault")) + amt, 4)
    ud.pop("_apex_vault_low_notified", None)
    bot.save_user(uid, ud)


def _withdraw_vault(uid: int, ud: dict, amount: float | None, take_all: bool) -> None:
    vault = _num(ud.get("apex_vault"))
    if take_all:
        amt = vault
    else:
        amt = _num(amount)
    if amt <= 0 or amt > vault + 0.001:
        raise HTTPException(status_code=400, detail="Amount exceeds vault")
    amt = min(amt, vault)
    ud["balance"] = round(_num(ud.get("balance")) + amt, 4)
    ud["apex_vault"] = round(vault - amt, 4)
    ud.pop("_apex_vault_low_notified", None)
    if ud["apex_vault"] < 0.01 and ud.get("apex_mode"):
        ud["apex_mode"] = False
    bot.save_user(uid, ud)


async def refresh_feed() -> int:
    """One sniper_scan pass. Concurrent callers share the in-flight scan."""
    global _feed_refresh_task
    async with _feed_lock:
        task = _feed_refresh_task
        if task is None or task.done():
            task = asyncio.get_running_loop().create_task(_refresh_feed_body())
            _feed_refresh_task = task
    return await task


async def _refresh_feed_body() -> int:
    """Score one sniper_scan pass. No extra trading rules."""
    global _last_refresh_ts
    try:
        raw = await bot.sniper_scan()
    except Exception as exc:
        logger.warning("terminal feed scan failed: %s", exc)
        return 0
    items = []
    seen = set()
    for item in raw or []:
        addr = (item or {}).get("tokenAddress") or ""
        if addr and addr not in seen:
            seen.add(addr)
            items.append(item)
    if not items:
        _last_refresh_ts = time.time()
        return 0
    # pump.fun births are first in sniper_scan and usually have no DexScreener
    # pair yet. Walk past those so the first SCAN_CAP rows are tokens we can price.
    def _rank(item: dict) -> int:
        if item.get("pairAddress") or item.get("pair_addr"):
            return 0
        if (item.get("source") or "") == "dexscreener":
            return 1
        return 2

    items.sort(key=_rank)
    scored = 0
    idx = 0
    while idx < len(items) and scored < SCAN_CAP:
        batch = items[idx:idx + 12]
        idx += 12
        infos = await asyncio.gather(
            *[bot.get_token(i["tokenAddress"]) for i in batch],
            return_exceptions=True,
        )
        for item, info in zip(batch, infos):
            if isinstance(info, Exception) or not info or not info.get("pair_addr"):
                continue
            info["pf_curve"] = item.get("_pf_curve") if item.get("_pf_curve") is not None else info.get("pf_curve")
            info["pf_replies"] = item.get("_pf_replies", info.get("pf_replies") or 0)
            info["pf_graduated"] = item.get("_pf_graduated", info.get("pf_graduated", False))
            info["pf_dev_pct"] = item.get("_pf_dev_pct") if item.get("_pf_dev_pct") is not None else info.get("pf_dev_pct")
            if item.get("_pf_virtual_sol_lamports"):
                info["virtual_sol_reserves"] = item["_pf_virtual_sol_lamports"]
                info["pf_virtual_sol_lamports"] = item["_pf_virtual_sol_lamports"]
            if item.get("_pf_real_token_reserves") is not None:
                info["real_token_reserves"] = item["_pf_real_token_reserves"]
            if item.get("_pf_quote_decimals") is not None:
                info["quote_decimals"] = item["_pf_quote_decimals"]
            info["boost_amount"] = item.get("_boost_amount", info.get("boost_amount") or 0)
            if not info.get("twitter") and item.get("_pf_twitter"):
                info["twitter"] = item["_pf_twitter"]
            if not info.get("telegram") and item.get("_pf_telegram"):
                info["telegram"] = item["_pf_telegram"]
            if not info.get("website") and item.get("_pf_website"):
                info["website"] = item["_pf_website"]
            sc = bot.sniper_score(info)
            record_scan(contract=item["tokenAddress"], info=info, sc=sc, source="scan")
            scored += 1
            if scored >= SCAN_CAP:
                break
    _last_refresh_ts = time.time()
    return scored


async def _feed_loop() -> None:
    """Backfill an empty terminal. sniper_job already publishes scans."""
    await asyncio.sleep(45)
    while True:
        try:
            if not _feed and time.time() - _last_record_ts > 20:
                await refresh_feed()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("terminal feed refresh")
        await asyncio.sleep(60)


def _candles_from_ohlcv(rows: list) -> list[dict]:
    candles = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else 0.0,
            })
        except (TypeError, ValueError):
            continue
    candles.sort(key=lambda c: c["time"])
    # lightweight-charts rejects duplicate timestamps
    dedup = {}
    for c in candles:
        dedup[c["time"]] = c
    return [dedup[k] for k in sorted(dedup)]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Tests set TERMINAL_FEED_LOOP=0 so they never call sniper_scan.
    if os.getenv("TERMINAL_FEED_LOOP", "1") == "0":
        yield
        return
    task = asyncio.create_task(_feed_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="APEX Terminal", version="1.0.0", lifespan=_lifespan)
    origins = _origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Telegram-Init-Data"],
        )

    @app.get("/health")
    @app.get("/api/health")
    async def health():
        return {"ok": True, "paper": True, "service": "apex-terminal"}

    @app.get("/")
    async def root():
        return {
            "service": "apex-terminal",
            "paper": True,
            "note": "The PWA is hosted separately. This process is the bot plus the API.",
        }

    @app.post("/api/auth/login")
    async def login(body: LoginBody):
        """Telegram Login Widget (browser, outside the Mini App). Returns a session token."""
        token = bot.BOT_TOKEN
        if not token:
            raise HTTPException(status_code=503, detail="Bot token is not configured")
        payload = body.model_dump(exclude_none=True)
        try:
            user = validate_login_widget(payload, token, _max_age())
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        uid, ud = _load_user(user)
        return {
            "paper": True,
            "token": issue_session(uid, token),
            "user": _me_payload(uid, ud),
        }

    @app.get("/api/me")
    async def me(user=Depends(current_user)):
        uid, ud = user
        return _me_payload(uid, ud)

    @app.get("/api/positions")
    async def positions(user=Depends(current_user)):
        _uid, ud = user
        rows = await _position_rows(ud)
        pnl = round(sum(r["pnl"] for r in rows), 4)
        value = round(sum(r["value"] for r in rows), 4)
        return {"paper": True, "positions": rows, "unrealized_pnl": pnl, "market_value": value}

    @app.get("/api/history")
    async def history(limit: int = 50, user=Depends(current_user)):
        uid, _ud = user
        limit = max(1, min(limit, 200))
        return {"paper": True, "trades": _history_rows(uid, limit)}

    @app.get("/api/feed")
    async def feed(refresh: bool = False, user=Depends(current_user)):
        _uid, _ud = user
        if refresh or (not _feed and time.time() - _last_refresh_ts > 5):
            await refresh_feed()
        rows = sorted(_feed.values(), key=lambda e: (e.get("score") or 0, e.get("ts") or 0), reverse=True)
        return {"paper": True, "tokens": rows[:FEED_CAP], "updated_at": _last_record_ts or _last_refresh_ts}

    @app.get("/api/tokens/{contract}")
    async def token_detail(contract: str, user=Depends(current_user)):
        uid, ud = user
        info = await bot.get_token(contract)
        if not info:
            raise HTTPException(status_code=404, detail="Token not found on DexScreener")
        try:
            from edge.enrich import enrich_onchain
            await enrich_onchain(contract, info)
        except Exception:
            logger.debug("token detail enrich failed", exc_info=True)
        fed = _feed.get(contract) or {}
        bot.carry_curve_fields(info, {
            "pf_curve": fed.get("pf_curve"),
            "pf_graduated": fed.get("pf_graduated"),
            "pf_replies": fed.get("pf_replies"),
            "pf_dev_pct": fed.get("pf_dev_pct"),
            "virtual_sol_reserves": fed.get("virtual_sol_reserves"),
        })
        sc = bot.sniper_score(info)
        ai = await bot.ai_analyze_token(info, sc, ud, uid)
        payload = _public_token(contract, info, sc, ai=ai, source="detail")
        held = (ud.get("holdings") or {}).get(contract)
        if held:
            price = _num(info.get("price"))
            cost = _num(held.get("total_invested"))
            value = _num(held.get("amount")) * price
            buy_cost = _num(held.get("buy_cost")) or cost
            remain = (cost / buy_cost) if buy_cost else 1.0
            entry_fees = _num(held.get("entry_fees")) * remain
            pnl = value - cost
            payload["position"] = {
                "amount": _num(held.get("amount")),
                "cost": cost,
                "value": round(value, 4),
                "pnl": round(pnl, 4),
                "pnl_net": round(pnl - entry_fees, 4),
                "entry_fees": round(entry_fees, 4),
                "avg_price": _num(held.get("avg_price")),
                "exit_plan": held.get("exit_plan"),
                "apex_exit": _apex_exit_view(held),
                "mood": held.get("mood") or "",
            }
        else:
            payload["position"] = None
        try:
            from slippage import slippage_pct, trade_cost_usd, tradable_liquidity_usd
            sample = _num(ud.get("quick_buy_amount"), 100) or 100
            tradable = tradable_liquidity_usd(info.get("liq"), None)
            if tradable is None:
                quote = await bot.bonding_curve_quote_usd(info, contract)
                tradable = tradable_liquidity_usd(0, quote)
            if tradable is None:
                payload["slippage"] = None
            else:
                payload["slippage"] = {
                    "sample_usd": sample,
                    "slippage_pct": round(slippage_pct(sample, tradable) * 100, 3),
                    "cost_usd": trade_cost_usd(sample, tradable),
                }
        except Exception:
            payload["slippage"] = None
        return payload

    @app.get("/api/tokens/{contract}/candles")
    async def candles(contract: str, user=Depends(current_user)):
        _uid, ud = user
        info = await bot.get_token(contract)
        rows = []
        source = "none"
        if info and info.get("pair_addr"):
            chain = (info.get("chain") or "solana").lower()
            rows = _candles_from_ohlcv(await bot.fetch_ohlcv(info["pair_addr"], chain))
            if rows:
                source = "geckoterminal"
        if not rows:
            held = (ud.get("holdings") or {}).get(contract) or {}
            points = []
            for p in held.get("price_history") or []:
                try:
                    points.append({
                        "time": int(p.get("ts") or 0),
                        "open": float(p["price"]),
                        "high": float(p["price"]),
                        "low": float(p["price"]),
                        "close": float(p["price"]),
                        "volume": 0.0,
                    })
                except (TypeError, ValueError, KeyError):
                    continue
            points = [p for p in points if p["time"] > 0]
            points.sort(key=lambda c: c["time"])
            if points:
                rows = points
                source = "position"
        return {"paper": True, "contract": contract, "source": source, "candles": rows}

    @app.post("/api/trade/buy")
    async def trade_buy(body: BuyBody, user=Depends(current_user)):
        uid, ud = user
        if not _balance_ready(ud):
            raise HTTPException(status_code=400, detail="Set a starting balance with /start in Telegram first")
        contract = body.contract.strip()
        fees_before = _num(ud.get("total_fees_paid"))
        plan = None
        if any(v is not None for v in (body.preset, body.tp_x, body.tp_pct, body.invalidation_pct, body.time_stop_min)):
            plan = {
                "preset": body.preset,
                "tp_x": body.tp_x,
                "tp_pct": body.tp_pct,
                "invalidation_pct": body.invalidation_pct,
                "time_stop_min": body.time_stop_min,
            }
        async with bot._get_user_lock(uid):
            result = await bot.do_buy_core(
                ud, uid, contract, float(body.amount_usd), planned=True, mood="", exit_plan=plan,
            )
        if isinstance(result, str):
            raise HTTPException(status_code=400, detail=result)
        info, tokens = result
        held = (ud.get("holdings") or {}).get(contract) or {}
        return {
            "paper": True,
            "ok": True,
            "symbol": info.get("symbol"),
            "name": info.get("name"),
            "contract": contract,
            "tokens": tokens,
            "price": info.get("price"),
            "spent": float(body.amount_usd),
            "fee": round(_num(ud.get("total_fees_paid")) - fees_before, 4),
            "balance": ud.get("balance"),
            "liq": info.get("liq"),
            "mc": info.get("mc"),
            "exit_plan": held.get("exit_plan"),
        }

    @app.post("/api/trade/sell")
    async def trade_sell(body: SellBody, user=Depends(current_user)):
        uid, ud = user
        if body.percent is None and body.amount_usd is None:
            raise HTTPException(status_code=400, detail="Send percent or amount_usd")
        contract = body.contract.strip()
        async with bot._get_user_lock(uid):
            if contract not in (ud.get("holdings") or {}):
                raise HTTPException(status_code=404, detail="Position not found")
            info = await bot.get_token(contract, max_age=bot.FILL_MAX_PRICE_AGE_S)
            if not info:
                raise HTTPException(status_code=503, detail="Price unavailable")
            h = ud["holdings"][contract]
            cv = _num(h.get("amount")) * _num(info.get("price"))
            if body.percent is not None:
                usd_amount = cv * (float(body.percent) / 100.0)
            else:
                usd_amount = min(float(body.amount_usd or 0), cv)
            usd_amount = min(usd_amount, cv)
            if usd_amount <= 0:
                raise HTTPException(status_code=400, detail="Invalid sell amount")
            # Same plan-tracking side effects as do_sell_query / do_sell_msg.
            # An intact exit plan is a rule break, not a followed-plan streak.
            pending_targets = [t for t in h.get("auto_sells", []) if not t.get("triggered")]
            plan_intact = False
            plan = h.get("exit_plan")
            if plan:
                try:
                    from edge.exit_plan import evaluate as _eval_exit
                    plan_intact = _eval_exit(plan, h, _num(info.get("price"))) is None
                except Exception:
                    plan_intact = True
            if pending_targets or plan_intact:
                ud["broken"] = ud.get("broken", 0) + 1
                ud["streak"] = 0
                h["followed_plan"] = False
            else:
                ud["followed"] = ud.get("followed", 0) + 1
                ud["streak"] = ud.get("streak", 0) + 1
                ud["best_streak"] = max(ud.get("best_streak", 0), ud["streak"])
                if plan:
                    h["followed_plan"] = True
            ud["daily_trades"] = ud.get("daily_trades", 0) + 1
            avg = _num(h.get("avg_price"), _num(info.get("price")))
            symbol = h.get("symbol")
            result = bot.sell_core(
                ud, uid, contract, usd_amount, _num(info.get("price")),
                reason="manual", liq=info.get("liq"),
            )
        cx = (_num(info.get("price")) / avg) if avg else 0.0
        return {
            "paper": True,
            "ok": True,
            "symbol": symbol,
            "contract": contract,
            "received": result.get("received"),
            "realized": result.get("realized"),
            "closed": result.get("closed"),
            "hold_h": result.get("hold_h"),
            "price": info.get("price"),
            "x": round(cx, 4),
            "balance": ud.get("balance"),
            "auto_saved": result.get("auto_saved"),
        }

    @app.get("/api/mood")
    async def market_mood(user=Depends(current_user)):
        """Mood gauge plus today's rule-break tally for this paper account."""
        uid, ud = user
        mood = _cached_mood()
        try:
            from edge.flags import market_mood as mood_on
            if mood_on() and mood is None:
                from edge.mood import refresh
                mood = await refresh()
        except Exception:
            logger.debug("mood refresh failed", exc_info=True)
        discipline = {"breaks": 0, "break_cost": 0, "overrides": 0, "rows": []}
        presets = {}
        try:
            from edge.exit_plan import PRESETS, nightly_report
            from edge.flags import exit_plan as plans_on
            presets = PRESETS
            if plans_on():
                today = datetime.now(bot.BOT_TZ).date()
                from datetime import time as dtime
                start = datetime.combine(today, dtime.min, tzinfo=bot.BOT_TZ).timestamp()
                discipline = nightly_report(ud, start)
        except Exception:
            logger.debug("discipline payload failed", exc_info=True)
        return {"paper": True, "mood": mood, "discipline": discipline, "presets": presets, "uid": uid}

    @app.get("/api/apex")
    async def apex_status(user=Depends(current_user)):
        uid, ud = user
        return _apex_payload(uid, ud)

    @app.post("/api/apex/toggle")
    async def apex_toggle(body: ApexToggle, user=Depends(current_user)):
        uid, ud = user
        _set_apex(uid, ud, body.enabled)
        return _apex_payload(uid, ud)

    @app.post("/api/apex/vault")
    async def apex_vault(body: VaultBody, user=Depends(current_user)):
        uid, ud = user
        action = (body.action or "").lower()
        async with bot._get_user_lock(uid):
            if action == "fund":
                _fund_vault(uid, ud, body.amount, body.all)
            elif action == "withdraw":
                _withdraw_vault(uid, ud, body.amount, body.all)
            else:
                raise HTTPException(status_code=400, detail="action must be fund or withdraw")
        return _apex_payload(uid, ud)

    @app.post("/api/apex/split")
    async def apex_split(body: SplitBody, user=Depends(current_user)):
        uid, ud = user
        ud["apex_vault_profit_split"] = body.percent / 100.0
        bot.save_user(uid, ud)
        return _apex_payload(uid, ud)

    @app.get("/api/leaderboard")
    async def leaderboard(sort: str = "equity", user=Depends(current_user)):
        uid, _ud = user
        if sort not in ("equity", "pnl", "wr"):
            sort = "equity"
        rows = _leaderboard(sort, uid)
        me_rank = next((r["rank"] for r in rows if r["is_me"]), None)
        return {"paper": True, "sort": sort, "rows": rows, "my_rank": me_rank}

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if not _origin_allowed(origin):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except Exception:
            await websocket.close(code=4401)
            return
        try:
            if isinstance(raw, dict) and raw.get("initData"):
                tg_user = validate_init_data(str(raw["initData"]), bot.BOT_TOKEN, _max_age())
            elif isinstance(raw, dict) and raw.get("token"):
                uid = read_session(str(raw["token"]), bot.BOT_TOKEN)
                tg_user = {"id": uid}
            else:
                raise TelegramAuthError("Authentication required")
            uid, ud = _load_user(tg_user)
        except (TelegramAuthError, HTTPException):
            await websocket.close(code=4401)
            return
        try:
            while True:
                rows = await _position_rows(ud)
                await websocket.send_json({
                    "type": "tick",
                    "paper": True,
                    "balance": ud.get("balance"),
                    "vault": round(_num(ud.get("apex_vault")), 4),
                    "realized_pnl": round(_num(ud.get("realized_pnl")), 4),
                    "unrealized_pnl": round(sum(r["pnl"] for r in rows), 4),
                    "positions": rows,
                    "apex_enabled": bool(ud.get("apex_mode")),
                    "ts": time.time(),
                })
                try:
                    msg = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                    if isinstance(msg, dict) and msg.get("type") == "close":
                        break
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            return
        except Exception:
            logger.debug("terminal websocket closed", exc_info=True)
            try:
                await websocket.close()
            except Exception:
                pass

    return app


_server = None


async def start_server() -> None:
    """Start uvicorn on the current event loop. Called from the bot's post_init."""
    global _server
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    config = uvicorn.Config(
        create_app(),
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = False
    _server = server
    asyncio.create_task(server.serve())
    logger.info("Terminal API listening on 0.0.0.0:%s", port)


async def stop_server() -> None:
    global _server
    if _server is not None:
        _server.should_exit = True
        _server = None
