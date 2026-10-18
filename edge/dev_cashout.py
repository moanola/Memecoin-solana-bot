"""Dev cash-out watcher.

Patterns (all from parsed transactions, not a dedicated on-chain account):
- several seller wallets send SOL to one hub in a short window
- that hub, or the creator's funder, is the fee payer on the sellers' dumps
- Pool.protocol_fees / creator_fees fell since the previous observation
  (fees held on the pool until they are swept — verified Pool fields)

A pre-dump alert requires a strong pattern: 3 or more sellers consolidating
within a few seconds, or the hub paying gas for at least 2 of those sells.
"""
from __future__ import annotations


def detect_dev_cashout(flows: list[dict], creator: str | None = None,
                       creator_funder: str | None = None, window_s: float = 3.0,
                       min_sellers: int = 3) -> dict:
    """`flows` items: ts, seller, fee_payer, sol_to, sol_amount, kind.

    kind is sell, sol_transfer, or fee_sweep.
    """
    sells = [f for f in flows or [] if f.get("kind") == "sell" and f.get("seller")]
    transfers = [f for f in flows or [] if f.get("kind") in {"sol_transfer", "sell"} and f.get("sol_to")]
    fee_sweep = any(f.get("kind") == "fee_sweep" or f.get("fee_sweep") for f in flows or [])

    # Consolidation: group SOL receipts by destination, then by time burst.
    by_hub: dict[str, list] = {}
    for row in transfers:
        sol = float(row.get("sol_amount") or 0)
        if sol <= 0 or not row.get("sol_to"):
            continue
        if row.get("seller") and row["sol_to"] == row["seller"]:
            continue
        by_hub.setdefault(row["sol_to"], []).append(row)

    best_hub = None
    best_sellers: list[str] = []
    for hub, rows in by_hub.items():
        rows = sorted(rows, key=lambda r: float(r.get("ts") or 0))
        sellers = []
        for i, row in enumerate(rows):
            t0 = float(row.get("ts") or 0)
            burst = [r for r in rows[i:] if float(r.get("ts") or 0) - t0 <= window_s]
            who = []
            for item in burst:
                seller = item.get("seller") or item.get("from")
                if seller and seller != hub and seller not in who:
                    who.append(seller)
            if len(who) > len(sellers):
                sellers = who
        if len(sellers) > len(best_sellers):
            best_sellers = sellers
            best_hub = hub

    consolidated = len(best_sellers) >= min_sellers
    gas_sellers = []
    payer_candidates = {a for a in (best_hub, creator_funder, creator) if a}
    for sell in sells:
        payer = sell.get("fee_payer")
        seller = sell.get("seller")
        if payer and seller and payer != seller and payer in payer_candidates:
            if seller not in gas_sellers:
                gas_sellers.append(seller)
    gas_paid = len(gas_sellers) >= 2

    # Creator (or the funder) receiving the consolidated SOL is the hub pattern
    # described for the creator's funder collecting seller proceeds.
    hub_is_insider = bool(best_hub and best_hub in {creator, creator_funder})
    alert = bool(consolidated or gas_paid or (fee_sweep and (consolidated or gas_paid)))
    # A fee sweep alone is not a dump. Require it together with flow, or a
    # strong flow by itself.
    if fee_sweep and not consolidated and not gas_paid:
        alert = False
    reasons = []
    if consolidated:
        reasons.append(f"{len(best_sellers)} sellers consolidated SOL to a hub within {window_s:.0f}s")
    if gas_paid:
        reasons.append(f"hub/funder paid gas for {len(gas_sellers)} seller dumps")
    if fee_sweep and alert:
        reasons.append("pool protocol/creator fees were swept")
    if hub_is_insider and consolidated:
        reasons.append("hub is the creator or the creator funder")
    return {
        "alert": alert,
        "reason": "; ".join(reasons),
        "hub": best_hub if alert else best_hub,
        "sellers": best_sellers if consolidated else [],
        "gas_paid_by_hub": gas_paid,
        "consolidated": consolidated,
        "fee_sweep": bool(fee_sweep),
        "hub_is_insider": hub_is_insider,
        "penalty": -18 if alert else 0,
    }


def flows_from_transactions(txns: list, mint: str, fee_sweep: bool = False) -> list[dict]:
    """Build cash-out flows from Helius-style transactions of a mint."""
    flows = []
    if fee_sweep:
        flows.append({"kind": "fee_sweep", "fee_sweep": True, "ts": 0})
    for tx in txns or []:
        if not isinstance(tx, dict):
            continue
        ts = float(tx.get("timestamp") or 0)
        payer = tx.get("feePayer") or ""
        sellers = set()
        for transfer in tx.get("tokenTransfers") or []:
            if transfer.get("mint") != mint:
                continue
            src = transfer.get("fromUserAccount") or ""
            if src:
                sellers.add(src)
        if not sellers:
            continue
        for native in tx.get("nativeTransfers") or []:
            try:
                sol = abs(float(native.get("amount") or 0)) / 1e9
            except (TypeError, ValueError):
                continue
            if sol < 0.02:
                continue
            src = native.get("fromUserAccount") or ""
            dst = native.get("toUserAccount") or ""
            if src in sellers and dst and dst != src:
                flows.append({
                    "kind": "sell",
                    "ts": ts,
                    "seller": src,
                    "fee_payer": payer,
                    "sol_to": dst,
                    "sol_amount": sol,
                    "from": src,
                })
    return flows
