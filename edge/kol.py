"""KOL sells, airdrop-vs-buy, side wallets, and score-boost decay.

Helius enhanced transactions expose `type` (SWAP, TRANSFER, …), `feePayer`,
`tokenTransfers`, and `nativeTransfers`. That is a parser schema, not an
on-chain enum. When `type` is missing the side is inferred from whether a
non-target asset left or entered the wallet in the same transaction.
Bag percent needs a running balance (this module's ledger). Without it the
sell is reported and the percent stays unknown.
"""
from __future__ import annotations

from edge.quotes import WSOL, _net_maps

FULL_EXIT_PCT = 95.0


def parse_wallet_transactions(txns: list, wallet: str, last_sig: str | None = None) -> list[dict]:
    """Newest-first events until last_sig (not included)."""
    events = []
    for tx in txns or []:
        if not isinstance(tx, dict):
            continue
        sig = tx.get("signature") or ""
        if last_sig and sig == last_sig:
            break
        typ = str(tx.get("type") or "").upper()
        incoming, outgoing, spent, received = _net_maps(tx, wallet, "")
        # _net_maps with empty target treats every mint as quote. Re-scan transfers.
        moves: dict[str, float] = {}
        for transfer in tx.get("tokenTransfers") or []:
            mint = transfer.get("mint") or ""
            if not mint or mint == WSOL:
                continue
            try:
                amount = float(transfer.get("tokenAmount") or 0)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            if transfer.get("toUserAccount") == wallet:
                moves[mint] = moves.get(mint, 0.0) + amount
            if transfer.get("fromUserAccount") == wallet:
                moves[mint] = moves.get(mint, 0.0) - amount
        sol_out = 0.0
        sol_in = 0.0
        for native in tx.get("nativeTransfers") or []:
            try:
                sol = abs(float(native.get("amount") or 0)) / 1e9
            except (TypeError, ValueError):
                continue
            if native.get("fromUserAccount") == wallet:
                sol_out += sol
            if native.get("toUserAccount") == wallet:
                sol_in += sol
        for mint, delta in moves.items():
            if abs(delta) < 1e-12:
                continue
            quote_left = any(a > 1e-12 for a in spent.values()) or sol_out > sol_in + 0.00002
            quote_arrived = any(a > 1e-12 for a in received.values()) or sol_in > sol_out + 0.00002
            if delta > 0:
                if typ == "SWAP" or (typ not in {"TRANSFER"} and quote_left):
                    via = "swap"
                    side = "buy"
                elif typ == "TRANSFER" or not quote_left:
                    via = "transfer"
                    side = "in"
                else:
                    via = "unknown"
                    side = "in"
                events.append({
                    "mint": mint,
                    "side": side,
                    "via": via,
                    "token_amount": delta,
                    "sol_spent": round(max(sol_out - sol_in, 0.0), 4) if side == "buy" else 0.0,
                    "sol_received": 0.0,
                    "signature": sig,
                    "timestamp": tx.get("timestamp") or 0,
                    "slot": tx.get("slot"),
                    "fee_payer": tx.get("feePayer") or "",
                    "wallet": wallet,
                    "bag_pct": None,
                    "partial": None,
                })
            else:
                if typ == "SWAP" or quote_arrived or typ not in {"TRANSFER"}:
                    via = "swap" if typ != "TRANSFER" else "transfer"
                    side = "sell" if via == "swap" or quote_arrived else "out"
                else:
                    via = "transfer"
                    side = "out"
                if typ == "TRANSFER" and not quote_arrived:
                    via = "transfer"
                    side = "out"
                events.append({
                    "mint": mint,
                    "side": "sell" if side != "out" else "out",
                    "via": via if side != "out" else "transfer",
                    "token_amount": abs(delta),
                    "sol_spent": 0.0,
                    "sol_received": round(max(sol_in - sol_out, 0.0), 4),
                    "signature": sig,
                    "timestamp": tx.get("timestamp") or 0,
                    "slot": tx.get("slot"),
                    "fee_payer": tx.get("feePayer") or "",
                    "wallet": wallet,
                    "bag_pct": None,
                    "partial": None,
                })
        # silence unused in the empty-target call; kept so a refactor notices
        _ = (incoming, outgoing)
    return events


def apply_bag_ledger(balances: dict, events: list[dict]) -> list[dict]:
    """Fill bag_pct from a per-mint balance, then update the balance.

    `events` must be oldest-first for the percent to match the bag before
    the sell. Callers that parse newest-first should reverse a batch that
    stops at a known signature.
    """
    for event in events:
        mint = event.get("mint") or ""
        amount = float(event.get("token_amount") or 0)
        bal = float(balances.get(mint) or 0)
        side = event.get("side")
        if side == "sell":
            if bal > 0 and amount > 0:
                pct = min(100.0, amount / bal * 100.0)
                event["bag_pct"] = round(pct, 2)
                event["partial"] = pct < FULL_EXIT_PCT
            balances[mint] = max(0.0, bal - amount)
        elif side in {"buy", "in"}:
            balances[mint] = bal + amount
    return events


def side_wallets_from_transfers(kol: str, transfers: list[dict], min_sol: float = 0.05) -> dict:
    """Link wallets that share the KOL's SOL funder, plus wallets the KOL funded.

    `transfers` are `{from, to, sol}`. This is funding-source tracing on
    parsed native transfers, not a proven on-chain identity link.
    """
    inbound = [
        t for t in transfers or []
        if t.get("to") == kol and float(t.get("sol") or 0) >= min_sol and t.get("from") and t.get("from") != kol
    ]
    if not inbound:
        funder = None
    else:
        counts: dict[str, float] = {}
        for row in inbound:
            counts[row["from"]] = counts.get(row["from"], 0.0) + float(row.get("sol") or 0)
        funder = max(counts, key=counts.get)
    sides = []
    funded_by_kol = []
    for row in transfers or []:
        sol = float(row.get("sol") or 0)
        if sol < min_sol:
            continue
        if funder and row.get("from") == funder and row.get("to") not in {kol, funder, None}:
            if row["to"] not in sides:
                sides.append(row["to"])
        if row.get("from") == kol and row.get("to") not in {kol, None}:
            if row["to"] not in funded_by_kol:
                funded_by_kol.append(row["to"])
    merged = list(dict.fromkeys(sides + funded_by_kol))
    return {"funder": funder, "side_wallets": merged, "funded_by_kol": funded_by_kol}


def summarize_hot(entries: list[dict]) -> dict:
    """Turn recent KOL hits into a boost factor in [0, 1].

    Buys via swap contribute. A later sell scales that contribution by the
    fraction of the bag still held. Tokens that arrived by transfer (airdrop)
    contribute nothing — they are the bait pattern, not a buy.
    """
    buys = [e for e in entries or [] if e.get("side", "buy") == "buy" and e.get("via", "swap") != "transfer"]
    airdrops = [e for e in entries or [] if e.get("via") == "transfer" or e.get("side") in {"in", "airdrop"}]
    exits = [e for e in entries or [] if e.get("side") == "sell"]
    if not buys and not exits and not airdrops:
        return {"live_buy_count": 0, "factor": 1.0, "note": "", "airdrop": False, "exited": False}

    # Weight each buy label. A sell with bag_pct None is treated as a full exit
    # of that label only when sol_received > 0 and no bag is known — defensive
    # callers should pass bag_pct. Here, unknown bag_pct on a sell decays that
    # label by half so we don't wipe a boost on an unparsed transfer.
    remaining = {}
    for buy in buys:
        label = buy.get("label") or buy.get("wallet") or "?"
        remaining[label] = remaining.get(label, 0.0) + float(buy.get("sol_spent") or 1.0)
    bought_weight = sum(remaining.values()) or float(len(buys) or 1)
    if not remaining and buys:
        for buy in buys:
            label = buy.get("label") or "?"
            remaining[label] = remaining.get(label, 0.0) + 1.0
        bought_weight = sum(remaining.values())

    exited_labels = set()
    for sell in exits:
        label = sell.get("label") or sell.get("wallet") or "?"
        pct = sell.get("bag_pct")
        if pct is None:
            keep = 0.5
        else:
            keep = max(0.0, 1.0 - float(pct) / 100.0)
        if label in remaining:
            remaining[label] *= keep
        if pct is not None and float(pct) >= FULL_EXIT_PCT:
            exited_labels.add(label)
    left = sum(max(0.0, v) for v in remaining.values())
    factor = 0.0 if bought_weight <= 0 else max(0.0, min(1.0, left / bought_weight))
    # Airdrop-only activity (no swap buy) must not boost.
    if not buys:
        factor = 0.0
    note = ""
    if exits and factor <= 0.05:
        note = "KOL exited — boost removed"
    elif exits and factor < 0.999:
        note = f"KOL boost decayed to {round(factor * 100)}% after a sell"
    elif airdrops and not buys:
        note = "KOL received tokens by transfer, not a buy"
    return {
        "live_buy_count": len([b for b in buys if (b.get("label") or b.get("wallet")) not in exited_labels]),
        "factor": round(factor, 4),
        "note": note,
        "airdrop": bool(airdrops) and not buys,
        "exited": bool(exits) and factor <= 0.05,
        "exit_count": len(exits),
    }


def boost_points(base_points: int, factor: float) -> int:
    try:
        return int(round(int(base_points) * max(0.0, min(1.0, float(factor)))))
    except (TypeError, ValueError):
        return int(base_points)
