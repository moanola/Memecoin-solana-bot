"""On-chain enrichment shared by the sniper, token cards, and APEX.

One Helius enhanced-transaction page feeds launch-group, dev cash-out, and
(when the page is short enough to reach the launch) early-buyer retention.
Calls are cached and capped per minute. No call is made without a key.
"""
from __future__ import annotations

import time

from edge import flags
from edge.dev_cashout import detect_dev_cashout, flows_from_transactions
from edge.holders import retention_from_swaps, swaps_from_transactions
from edge.launch_group import assess_launch_group

_cache: dict[str, dict] = {}
_budget = {"window": 0, "used": 0}
_lock_note = {"sem": None}


def reset_cache() -> None:
    _cache.clear()
    _budget["window"] = 0
    _budget["used"] = 0


def _allow() -> bool:
    now = int(time.time() // 60)
    if _budget["window"] != now:
        _budget["window"] = now
        _budget["used"] = 0
    if _budget["used"] >= flags.helius_per_min():
        return False
    _budget["used"] += 1
    return True


async def fetch_mint_transactions(mint: str, api_key: str, limit: int = 100) -> list:
    from api_clients import get_http
    client = await get_http()
    url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
    response = await client.get(url, params={"api-key": api_key, "limit": str(limit)}, timeout=8)
    if response.status_code == 429:
        return []
    if response.status_code != 200:
        return []
    body = response.json()
    return body if isinstance(body, list) else []


def apply_transactions(info: dict, mint: str, txns: list, created_at_ts: float | None = None) -> dict:
    """Pure application of one transaction page onto a token dict."""
    limit = 100
    if flags.launch_group():
        group = assess_launch_group(txns, mint, balances=info.get("launch_group_balances"),
                                    created_at_ts=created_at_ts, page_limit=limit)
        info["launch_group_found"] = bool(group.get("found"))
        info["launch_group_size"] = group.get("size") or 0
        info["launch_group_sold_pct"] = group.get("sold_pct")
        info["launch_group_confident"] = bool(group.get("confident"))
        info["launch_group_partial"] = bool(group.get("partial"))
    if flags.dev_cashout():
        flows = flows_from_transactions(txns, mint, fee_sweep=bool(info.get("fee_sweep")))
        cash = detect_dev_cashout(
            flows,
            creator=info.get("creator") or info.get("dev_wallet"),
            creator_funder=info.get("creator_funder") or info.get("funder"),
        )
        info["dev_cashout"] = bool(cash.get("alert"))
        info["dev_cashout_reason"] = cash.get("reason") or ""
        info["dev_cashout_hub"] = cash.get("hub")
    if flags.holder_velocity() and len(txns) < limit:
        retention = retention_from_swaps(swaps_from_transactions(txns, mint))
        if retention is not None:
            info["holder_retention_pct"] = retention
            info["holder_retention_window"] = "fetched_page"
    return info


async def enrich_onchain(mint: str, info: dict, api_key: str | None = None) -> dict:
    """Fill launch-group, cash-out, and retention. Cached for 3 minutes."""
    if not info or not mint:
        return info
    if not (flags.launch_group() or flags.dev_cashout() or flags.holder_velocity()):
        return info
    import os
    api_key = api_key if api_key is not None else os.environ.get("HELIUS_API_KEY", "")
    cached = _cache.get(mint)
    now = time.time()
    if cached and now - cached["ts"] < 180:
        info.update(cached["fields"])
        return info
    if not api_key or not _allow():
        return info
    try:
        txns = await fetch_mint_transactions(mint, api_key)
    except Exception:
        return info
    if not txns:
        return info
    before = {k: info.get(k) for k in (
        "launch_group_found", "launch_group_size", "launch_group_sold_pct",
        "launch_group_confident", "launch_group_partial", "dev_cashout",
        "dev_cashout_reason", "dev_cashout_hub", "holder_retention_pct",
    )}
    created = info.get("pair_created_at")
    apply_transactions(info, mint, txns, created_at_ts=created)
    fields = {}
    for key in before:
        if info.get(key) != before[key] or key in info:
            if key in info:
                fields[key] = info.get(key)
    _cache[mint] = {"ts": now, "fields": fields}
    return info
