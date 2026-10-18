"""Holder velocity and early-buyer retention.

holders/hour uses a holder or maker count and the pair age. Retention uses the
first ~70 unique buyers in a swap list and asks whether their net flow is
still positive. That is only valid when the list reaches the launch (the
caller passes a short page). A full newest-first page is not the first 70
buyers, so retention stays unknown and does not move the score.
"""
from __future__ import annotations

from edge.quotes import WSOL


def holders_per_hour(holder_count, age_h) -> float | None:
    try:
        count = float(holder_count)
        age = float(age_h)
    except (TypeError, ValueError):
        return None
    # 0 means "not counted yet", not a real empty holder set.
    if count <= 0 or age <= 0:
        return None
    # Avoid exploding on a token that is seconds old.
    return round(count / max(age, 1 / 60), 2)


def retention_from_swaps(swaps: list[dict], limit: int = 70) -> float | None:
    """Percent of the first `limit` buyers with net tokens still positive.

    Each swap is `{wallet, side, amount}` in chronological order.
    side is buy or sell. Returns None when there is no buy.
    """
    first: list[str] = []
    seen = set()
    bought = {}
    for swap in swaps or []:
        wallet = swap.get("wallet")
        if not wallet:
            continue
        side = swap.get("side")
        if side == "buy" and wallet not in seen:
            seen.add(wallet)
            first.append(wallet)
            if len(first) >= limit:
                break
    if not first:
        return None
    nets = {wallet: 0.0 for wallet in first}
    bought = {wallet: 0.0 for wallet in first}
    for swap in swaps or []:
        wallet = swap.get("wallet")
        if wallet not in nets:
            continue
        try:
            amount = float(swap.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if swap.get("side") == "buy":
            nets[wallet] += amount
            bought[wallet] += amount
        elif swap.get("side") == "sell":
            nets[wallet] -= amount
    holding = 0
    for wallet in first:
        base = bought[wallet]
        if base <= 0:
            continue
        if nets[wallet] > base * 0.1:
            holding += 1
    return round(holding / len(first) * 100.0, 2)


def swaps_from_transactions(txns: list, mint: str) -> list[dict]:
    """Chronological buy/sell rows from Helius-style transactions (newest-first)."""
    rows = []
    ordered = list(reversed(txns or []))
    for tx in ordered:
        if not isinstance(tx, dict):
            continue
        wallet = tx.get("feePayer") or ""
        if not wallet:
            continue
        inn = out = 0.0
        for transfer in tx.get("tokenTransfers") or []:
            if transfer.get("mint") != mint:
                continue
            try:
                amount = float(transfer.get("tokenAmount") or 0)
            except (TypeError, ValueError):
                continue
            if transfer.get("toUserAccount") == wallet:
                inn += amount
            if transfer.get("fromUserAccount") == wallet:
                out += amount
        if inn > out and inn > 0:
            rows.append({"wallet": wallet, "side": "buy", "amount": inn - out, "ts": tx.get("timestamp") or 0})
        elif out > inn and out > 0:
            rows.append({"wallet": wallet, "side": "sell", "amount": out - inn, "ts": tx.get("timestamp") or 0})
        _ = WSOL  # quote asset is irrelevant to retention of the base mint
    return rows


def score_delta(holders_per_h, retention_pct) -> tuple[int, list[str]]:
    delta = 0
    notes = []
    if holders_per_h is not None:
        if holders_per_h >= 80:
            delta += 6
            notes.append(f"{holders_per_h:.0f} holders/hour")
        elif holders_per_h >= 30:
            delta += 3
            notes.append(f"{holders_per_h:.0f} holders/hour")
        elif holders_per_h < 8:
            delta -= 3
            notes.append(f"slow holder growth ({holders_per_h:.0f}/hour)")
    if retention_pct is not None:
        if retention_pct >= 60:
            delta += 6
            notes.append(f"{retention_pct:.0f}% of early buyers still holding")
        elif retention_pct < 30:
            delta -= 6
            notes.append(f"only {retention_pct:.0f}% of early buyers still holding")
    return delta, notes


def reentry_allowed(info: dict, min_retention: float) -> tuple[bool, str]:
    """Extra watchlist gate. Unknown retention does not block."""
    retention = info.get("holder_retention_pct")
    if retention is None:
        return True, ""
    try:
        retention = float(retention)
    except (TypeError, ValueError):
        return True, ""
    if retention < float(min_retention):
        return False, f"early-buyer retention {retention:.0f}% < {min_retention:.0f}%"
    return True, f"early-buyer retention {retention:.0f}%"
