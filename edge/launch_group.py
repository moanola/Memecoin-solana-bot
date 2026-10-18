"""Cluster the earliest buyers and measure how much of that bag has been sold.

Signals used together (a pair of wallets links when they share the slot and
one extra fingerprint):
- same slot
- a native transfer to a published Jito tip account
- the same SOL funder
- identical fee and compute-unit consumption

Jito tip accounts are the eight addresses published by Jito. A Helius `source`
of JITO is also accepted. Linking wallets this way is a heuristic: it is not
a proof that the transactions landed in one Jito bundle.

APEX only treats the sold-percent as an exit when `confident` is true. A full
page of newest-first history that does not reach the pair's creation time is
not confident — the cluster may not be the launch group.
"""
from __future__ import annotations

# https://jito-labs.gitbook.io/mev/searcher-resources/json-rpc-api-reference/bundles
JITO_TIP_ACCOUNTS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}


def tx_has_jito_tip(tx: dict) -> bool:
    source = str(tx.get("source") or "").upper()
    if source == "JITO" or tx.get("jito_tip"):
        return True
    for native in tx.get("nativeTransfers") or []:
        if native.get("toUserAccount") in JITO_TIP_ACCOUNTS and float(native.get("amount") or 0) > 0:
            return True
    return False


def _funder(tx: dict, buyer: str) -> str | None:
    if tx.get("funder"):
        return tx.get("funder")
    best = None
    best_amt = 0.0
    for native in tx.get("nativeTransfers") or []:
        if native.get("toUserAccount") != buyer:
            continue
        if native.get("fromUserAccount") in JITO_TIP_ACCOUNTS:
            continue
        try:
            sol = abs(float(native.get("amount") or 0)) / 1e9
        except (TypeError, ValueError):
            continue
        if sol > best_amt:
            best_amt = sol
            best = native.get("fromUserAccount")
    return best


def early_buy_rows(txns: list, mint: str) -> list[dict]:
    """One row per buy of `mint` (fee payer received the mint)."""
    rows = []
    for tx in txns or []:
        if not isinstance(tx, dict):
            continue
        buyer = tx.get("feePayer") or tx.get("buyer") or ""
        if not buyer:
            continue
        amount = 0.0
        for transfer in tx.get("tokenTransfers") or []:
            if transfer.get("mint") == mint and transfer.get("toUserAccount") == buyer:
                try:
                    amount += float(transfer.get("tokenAmount") or 0)
                except (TypeError, ValueError):
                    continue
        if amount <= 0 and tx.get("token_amount"):
            amount = float(tx.get("token_amount") or 0)
            buyer = tx.get("buyer") or buyer
        if amount <= 0:
            continue
        # A sell also has the fee payer sending the mint. Net must be a buy.
        sent = 0.0
        for transfer in tx.get("tokenTransfers") or []:
            if transfer.get("mint") == mint and transfer.get("fromUserAccount") == buyer:
                try:
                    sent += float(transfer.get("tokenAmount") or 0)
                except (TypeError, ValueError):
                    continue
        if sent >= amount and tx.get("tokenTransfers"):
            continue
        rows.append({
            "wallet": buyer,
            "slot": tx.get("slot"),
            "ts": tx.get("timestamp") or 0,
            "fee": tx.get("fee"),
            "compute_units": tx.get("computeUnitsConsumed") or tx.get("compute_units"),
            "funder": _funder(tx, buyer),
            "jito": tx_has_jito_tip(tx),
            "amount": amount - sent,
            "signature": tx.get("signature"),
        })
    rows.sort(key=lambda r: (r["slot"] is None, r["slot"] if r["slot"] is not None else 0, r["ts"] or 0))
    return rows


def _linked(a: dict, b: dict) -> bool:
    if a["wallet"] == b["wallet"]:
        return False
    same_slot = a.get("slot") is not None and a.get("slot") == b.get("slot")
    jito = bool(a.get("jito") and b.get("jito"))
    funder = bool(a.get("funder") and a.get("funder") == b.get("funder"))
    fees = (
        a.get("fee") is not None
        and a.get("fee") == b.get("fee")
        and a.get("compute_units") is not None
        and a.get("compute_units") == b.get("compute_units")
    )
    if same_slot and (jito or funder or fees):
        return True
    # A Jito tip plus the same funder still links when the burst crosses a slot.
    if jito and funder:
        return True
    return False


def cluster_buyers(rows: list[dict], min_size: int = 3) -> list[dict] | None:
    """Largest linked cluster among the earliest rows. None if smaller than min_size."""
    if len(rows) < min_size:
        return None
    # Only the earliest slice: launch groups buy at the start, not hours later.
    earliest_slot = rows[0].get("slot")
    window = [r for r in rows if earliest_slot is None or r.get("slot") == earliest_slot]
    if len(window) < min_size:
        # Allow the next slot too when the burst crosses a slot boundary (~400ms).
        slots = []
        for row in rows:
            if row.get("slot") is not None and row["slot"] not in slots:
                slots.append(row["slot"])
            if len(slots) >= 2:
                break
        window = [r for r in rows if r.get("slot") in slots]
    if len(window) < min_size:
        return None
    parent = {r["wallet"]: r["wallet"] for r in window}

    def find(wallet: str) -> str:
        while parent[wallet] != wallet:
            parent[wallet] = parent[parent[wallet]]
            wallet = parent[wallet]
        return wallet

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_wallet = {}
    for row in window:
        by_wallet.setdefault(row["wallet"], row)
    wallets = list(by_wallet)
    for i, left in enumerate(wallets):
        for right in wallets[i + 1:]:
            if _linked(by_wallet[left], by_wallet[right]):
                union(left, right)
    groups: dict[str, list] = {}
    for wallet in wallets:
        groups.setdefault(find(wallet), []).append(by_wallet[wallet])
    best = max(groups.values(), key=len)
    if len(best) < min_size:
        return None
    return best


def bag_sold_pct(members: list[dict], balances: dict | None = None) -> float:
    """Percent of the clustered buy size that is no longer held.

    `balances` maps wallet -> current token amount. Missing wallets count as
    fully sold only when the map is provided and the key is absent. An empty
    map means balances are unknown and the sold percent is 0 (no false exit).
    """
    if not members:
        return 0.0
    if not balances:
        return 0.0
    initial = 0.0
    left = 0.0
    for member in members:
        initial += float(member.get("amount") or 0)
        wallet = member["wallet"]
        if wallet in balances:
            left += max(0.0, float(balances.get(wallet) or 0))
        else:
            left += 0.0
    if initial <= 0:
        return 0.0
    sold = max(0.0, initial - left) / initial * 100.0
    return round(min(100.0, sold), 2)


def assess_launch_group(txns: list, mint: str, balances: dict | None = None,
                        created_at_ts: float | None = None, page_limit: int = 100) -> dict:
    rows = early_buy_rows(txns, mint)
    members = cluster_buyers(rows) if rows else None
    page_full = len(txns or []) >= page_limit
    if not members:
        return {
            "found": False,
            "size": 0,
            "sold_pct": 0.0,
            "confident": False,
            "partial": page_full,
            "wallets": [],
        }
    oldest_ts = min(float(m.get("ts") or 0) for m in members)
    reaches_launch = False
    if created_at_ts and oldest_ts:
        reaches_launch = abs(oldest_ts - float(created_at_ts)) <= 180
    confident = (not page_full) or reaches_launch
    return {
        "found": True,
        "size": len(members),
        "sold_pct": bag_sold_pct(members, balances),
        "confident": bool(confident),
        "partial": bool(page_full and not reaches_launch),
        "wallets": [m["wallet"] for m in members],
        "slot": members[0].get("slot"),
        "jito": any(m.get("jito") for m in members),
        "common_funder": len({m.get("funder") for m in members if m.get("funder")}) == 1,
    }


def exit_triggered(assessment: dict, threshold_pct: float) -> bool:
    if not assessment or not assessment.get("confident"):
        return False
    try:
        return float(assessment.get("sold_pct") or 0) >= float(threshold_pct)
    except (TypeError, ValueError):
        return False
