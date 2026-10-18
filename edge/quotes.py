"""Custom-pair pricing, signed PumpSwap reserves, and quote-asset volume.

Verified against:
- https://pump.fun/docs/custom-pairs (Supported Pair Assets, updated 2026-10-09)
- pump-fun/pump-public-docs idl/pump_amm.json (program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA)
  Pool.virtual_quote_reserves is i128 and may be negative. Official pricing is
  effective_quote_reserves = vault_amount + virtual_quote_reserves.
  Pool.protocol_fees and Pool.creator_fees sit on the account until collected.
- The same IDL lists buy, buy_exact_quote_in, buy_exact_quote_in_v2, sell,
  sell_v2, and multi_hop_swap. It does not list a v3 trade instruction or a
  synthetic-migration instruction. Those names from the Oct 2026 write-ups are
  not decoded here.

DexScreener priceNative is the chain-native price (SOL on Solana), not the
quote-token price. USD spot for a non-SOL quote is computed from pool reserves
times the quote asset's USD price, not from priceNative * quote_usd.
"""
from __future__ import annotations

import base64
from collections import Counter

from edge.b58 import b58decode, b58encode_pubkey
from edge.supported_quotes import SUPPORTED_QUOTES

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLES = {USDC, USDT}

PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
POOL_DISCRIMINATOR = bytes([241, 154, 109, 4, 17, 177, 109, 188])

# Anchor discriminators copied from the public pump_amm IDL.
INSTRUCTION_DISCRIMINATORS = {
    "buy": bytes([102, 6, 61, 18, 1, 218, 235, 234]),
    "buy_exact_quote_in": bytes([198, 46, 21, 82, 180, 217, 232, 112]),
    "buy_exact_quote_in_v2": bytes([194, 171, 28, 70, 104, 77, 91, 47]),
    "sell": bytes([51, 230, 133, 164, 1, 127, 131, 173]),
    "sell_v2": bytes([93, 246, 130, 60, 231, 233, 64, 178]),
    "multi_hop_swap": bytes([43, 100, 73, 19, 233, 246, 111, 148]),
}

# body offsets (after the 8-byte account discriminator), from the Pool struct.
_OFF_QUOTE_MINT = 67
_OFF_VIRTUAL = 237
_OFF_PROTOCOL_FEES = 263
_OFF_CREATOR_FEES = 271


def classify_quote(mint: str | None) -> str:
    """sol, stable, custom (on the Supported Pair Assets list), or unlisted.

    An unlisted mint may be a Secondary Pair Asset (a pump.fun coin used as
    the quote). The docs say that status is fixed at the parent coin's launch
    and is not published on the supported list, so it is not asserted here.
    """
    if not mint:
        return "unknown"
    if mint == WSOL:
        return "sol"
    if mint in STABLES:
        return "stable"
    if mint in SUPPORTED_QUOTES:
        return "custom"
    return "unlisted"


def identify_instruction(data: bytes | None) -> str | None:
    """Return a verified pump_amm instruction name, or None.

    Unknown leading bytes — including anything described as a v3 trade or a
    synthetic migration — are not guessed.
    """
    if not data or len(data) < 8:
        return None
    head = data[:8]
    for name, disc in INSTRUCTION_DISCRIMINATORS.items():
        if head == disc:
            return name
    return None


def decode_instruction_data(data) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if not isinstance(data, str) or not data:
        return None
    try:
        return b58decode(data)
    except ValueError:
        pass
    try:
        return base64.b64decode(data, validate=False)
    except Exception:
        return None


def route_kind(tx: dict) -> str:
    """single, multi_hop, or unknown from parsed instruction bytes when present."""
    blobs = []
    for key in ("instructions", "innerInstructions"):
        for ix in tx.get(key) or []:
            if isinstance(ix, dict):
                blobs.append(ix.get("data"))
                for inner in ix.get("instructions") or []:
                    if isinstance(inner, dict):
                        blobs.append(inner.get("data"))
    names = set()
    for blob in blobs:
        name = identify_instruction(decode_instruction_data(blob))
        if name:
            names.add(name)
    if "multi_hop_swap" in names:
        return "multi_hop"
    if names:
        return "single"
    # Helius sometimes sets source/type without raw bytes.
    source = str(tx.get("source") or "").upper()
    desc = str(tx.get("description") or "").lower()
    if "multi" in desc and "hop" in desc:
        return "multi_hop"
    if source or tx.get("type"):
        return "unknown"
    return "unknown"


def decode_pumpswap_pool(data: bytes) -> dict | None:
    """Decode a PumpSwap Pool account. Shorter legacy accounts omit new fields.

    virtual_quote_reserves is read as a signed i128. Missing bytes mean 0,
    which the official docs say is the right reading for pools written before
    the field existed.
    """
    if not data or len(data) < 8 or data[:8] != POOL_DISCRIMINATOR:
        return None
    body = data[8:]
    if len(body) < _OFF_QUOTE_MINT + 32:
        return None

    def pubkey(offset: int) -> str | None:
        if len(body) < offset + 32:
            return None
        return b58encode_pubkey(body[offset:offset + 32])

    out = {
        "layout": "pump_amm_pool",
        "verified_layout": True,
        "creator": pubkey(3),
        "base_mint": pubkey(35),
        "quote_mint": pubkey(_OFF_QUOTE_MINT),
        "quote_kind": classify_quote(pubkey(_OFF_QUOTE_MINT)),
        "virtual_quote_reserves": 0,
        "virtual_quote_reserves_missing": len(body) < _OFF_VIRTUAL + 16,
        "protocol_fees": None,
        "creator_fees": None,
        "is_holder_reward": None,
    }
    if len(body) >= _OFF_VIRTUAL + 16:
        out["virtual_quote_reserves"] = int.from_bytes(
            body[_OFF_VIRTUAL:_OFF_VIRTUAL + 16], "little", signed=True
        )
    if len(body) >= 263:
        out["is_holder_reward"] = bool(body[262])
    if len(body) >= _OFF_PROTOCOL_FEES + 8:
        out["protocol_fees"] = int.from_bytes(body[_OFF_PROTOCOL_FEES:_OFF_PROTOCOL_FEES + 8], "little")
    if len(body) >= _OFF_CREATOR_FEES + 8:
        out["creator_fees"] = int.from_bytes(body[_OFF_CREATOR_FEES:_OFF_CREATOR_FEES + 8], "little")
    return out


def effective_quote_reserves(vault_raw: int, virtual_quote: int) -> int:
    """vault + signed virtual reserves.

    The program promises the sum is non-negative and fits in a u64. A negative
    result is clamped to 0 so a bad account cannot invent a price.
    """
    try:
        total = int(vault_raw) + int(virtual_quote)
    except (TypeError, ValueError):
        return 0
    if total < 0:
        return 0
    if total > 2**64 - 1:
        return 2**64 - 1
    return total


def spot_price_usd(base_raw: int, quote_effective_raw: int, base_decimals: int,
                   quote_decimals: int, quote_usd: float) -> float:
    """Constant-product spot of the base token in USD, using effective quote reserves."""
    try:
        if base_raw <= 0 or quote_effective_raw <= 0 or quote_usd <= 0:
            return 0.0
        base_ui = base_raw / (10 ** int(base_decimals))
        quote_ui = quote_effective_raw / (10 ** int(quote_decimals))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if base_ui <= 0:
        return 0.0
    return (quote_ui / base_ui) * float(quote_usd)


def quote_usd_of(mint: str, prices: dict, sol_usd: float) -> float | None:
    kind = classify_quote(mint)
    if kind == "sol":
        return float(sol_usd) if sol_usd and sol_usd > 0 else None
    if kind == "stable":
        return 1.0
    px = prices.get(mint) if prices else None
    try:
        px = float(px)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None


def annotate_dex_pair(pair: dict, quote_usd: float | None = None) -> dict:
    """Labels for a DexScreener pair. Does not treat priceNative as quote units.

    When priceUsd is missing and liquidity.base / liquidity.quote are present,
    a USD spot is derived as (quote_ui / base_ui) * quote_usd. That path is
    marked price_derived. Otherwise the DexScreener USD price is kept.
    Custom and unlisted quotes are price_indicative: the pump.fun docs say a
    value routed through more than one pool is indicative only.
    """
    quote = pair.get("quoteToken") or {}
    base = pair.get("baseToken") or {}
    qaddr = quote.get("address") or ""
    qsym = quote.get("symbol") or "?"
    bsym = base.get("symbol") or "?"
    chain = str(pair.get("chainId") or pair.get("chain") or "").strip().lower()
    # Custom-pair labels are a Solana / pump.fun concept. An EVM pair whose
    # quote address happens to decode like a listed mint must not be tagged.
    if chain and chain not in {"solana", "sol"}:
        kind = ""
        indicative = False
    else:
        kind = classify_quote(qaddr)
        indicative = kind in {"custom", "unlisted"}
    try:
        price_usd = float(pair.get("priceUsd") or 0)
    except (TypeError, ValueError):
        price_usd = 0.0
    derived = 0.0
    if price_usd <= 0 and quote_usd and quote_usd > 0:
        liq = pair.get("liquidity") or {}
        try:
            base_amt = float(liq.get("base") or 0)
            quote_amt = float(liq.get("quote") or 0)
        except (TypeError, ValueError):
            base_amt = quote_amt = 0.0
        if base_amt > 0 and quote_amt > 0:
            derived = (quote_amt / base_amt) * float(quote_usd)
    price = derived if derived > 0 else price_usd
    return {
        "quote_symbol": qsym,
        "quote_address": qaddr,
        "quote_kind": kind,
        "pair_label": f"{bsym}/{qsym}",
        "price_indicative": indicative,
        "price_derived": derived > 0,
        "derived_price_usd": price if price > 0 else None,
    }


_fee_state: dict[str, dict] = {}


def reset_fee_state() -> None:
    _fee_state.clear()


def observe_pool_fees(pair: str, protocol_fees, creator_fees) -> dict:
    """A drop in protocol_fees or creator_fees is a fee sweep.

    Those u64 fields are on the verified Pool account. The IDL also has
    collect_coin_creator_fee. Comparing two observations is the defensive
    check used here; a single snapshot never counts as a sweep.
    """
    prev = _fee_state.get(pair)
    current = {"protocol_fees": protocol_fees, "creator_fees": creator_fees}
    sweep = False
    if prev is not None:
        for key in ("protocol_fees", "creator_fees"):
            before = prev.get(key)
            after = current.get(key)
            if before is not None and after is not None and after < before:
                sweep = True
    _fee_state[pair] = current
    return {"fee_sweep": sweep, "protocol_fees": protocol_fees, "creator_fees": creator_fees}


def _net_maps(tx: dict, wallet: str, target_mint: str) -> tuple[float, float, dict, dict]:
    incoming = 0.0
    outgoing = 0.0
    spent: dict[str, float] = {}
    received: dict[str, float] = {}
    for transfer in tx.get("tokenTransfers") or []:
        mint = transfer.get("mint") or ""
        try:
            amount = float(transfer.get("tokenAmount") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0 or not mint:
            continue
        to_wallet = transfer.get("toUserAccount") == wallet
        from_wallet = transfer.get("fromUserAccount") == wallet
        if mint == target_mint:
            if to_wallet:
                incoming += amount
            if from_wallet:
                outgoing += amount
            continue
        if from_wallet:
            spent[mint] = spent.get(mint, 0.0) + amount
        if to_wallet:
            received[mint] = received.get(mint, 0.0) + amount
    sol_out = 0.0
    sol_in = 0.0
    for native in tx.get("nativeTransfers") or []:
        try:
            lamports = abs(float(native.get("amount") or 0))
        except (TypeError, ValueError):
            continue
        if native.get("fromUserAccount") == wallet:
            sol_out += lamports / 1e9
        if native.get("toUserAccount") == wallet:
            sol_in += lamports / 1e9
    # Wrapped SOL token legs already record the swap. Native dust is gas.
    if WSOL in spent or WSOL in received:
        pass
    elif sol_out - sol_in > 0.00002:
        spent[WSOL] = spent.get(WSOL, 0.0) + (sol_out - sol_in)
    elif sol_in - sol_out > 0.00002:
        received[WSOL] = received.get(WSOL, 0.0) + (sol_in - sol_out)
    return incoming, outgoing, spent, received


def _valued(amounts: dict, prices: dict, sol_usd: float, use_quote_usd: bool) -> tuple[float, bool]:
    total = 0.0
    unpriced = False
    for mint, amount in amounts.items():
        if not use_quote_usd and mint != WSOL:
            continue
        usd = quote_usd_of(mint, prices, sol_usd) if use_quote_usd or mint == WSOL else None
        if mint == WSOL and (not sol_usd or sol_usd <= 0):
            unpriced = True
            continue
        if usd is None:
            unpriced = True
            continue
        total += amount * usd
    return total, unpriced


def summarize_swap_volume(txns: list, mint: str, prices: dict | None = None,
                          sol_usd: float = 0.0, use_quote_usd: bool = True) -> dict:
    """Maker and wash stats.

    use_quote_usd values every net quote leg (custom pairs and multi-hop
    leftovers). When it is false, only native/wrapped SOL counts — the
    previous behaviour of get_helius_maker_pct.
    """
    prices = prices or {}
    buyer_vols: dict[str, float] = {}
    seller_vols: dict[str, float] = {}
    quote_hits: Counter = Counter()
    routes: Counter = Counter()
    unpriced = 0
    for tx in txns or []:
        if not isinstance(tx, dict):
            continue
        wallet = tx.get("feePayer") or ""
        if not wallet:
            continue
        incoming, outgoing, spent, received = _net_maps(tx, wallet, mint)
        routes[route_kind(tx)] += 1
        if incoming > outgoing and incoming > 0:
            net = {m: a - received.get(m, 0.0) for m, a in spent.items()}
            net = {m: a for m, a in net.items() if a > 1e-12}
            usd, missing = _valued(net, prices, sol_usd, use_quote_usd)
            if missing and usd <= 0:
                unpriced += 1
            if usd > 0:
                buyer_vols[wallet] = buyer_vols.get(wallet, 0.0) + usd
                for m in net:
                    quote_hits[m] += 1
        elif outgoing > incoming and outgoing > 0:
            net = {m: a - spent.get(m, 0.0) for m, a in received.items()}
            net = {m: a for m, a in net.items() if a > 1e-12}
            usd, missing = _valued(net, prices, sol_usd, use_quote_usd)
            if missing and usd <= 0:
                unpriced += 1
            if usd > 0:
                seller_vols[wallet] = seller_vols.get(wallet, 0.0) + usd
                for m in net:
                    quote_hits[m] += 1

    wallets = set(buyer_vols) | set(seller_vols)
    if not wallets:
        return {}
    all_vols: dict[str, float] = {}
    for wallet, vol in buyer_vols.items():
        all_vols[wallet] = all_vols.get(wallet, 0.0) + vol
    for wallet, vol in seller_vols.items():
        all_vols[wallet] = all_vols.get(wallet, 0.0) + vol
    total = sum(all_vols.values()) or 1.0
    top3 = sum(sorted(all_vols.values(), reverse=True)[:3])
    dominant = quote_hits.most_common(1)[0][0] if quote_hits else WSOL
    return {
        "maker_pct": round(len(buyer_vols) / len(wallets) * 100) if wallets else 50,
        "maker_count": len(buyer_vols),
        "top3_vol_pct": round(top3 / total * 100),
        "volume_usd": round(total, 4),
        "quote_mint": dominant,
        "quote_symbol": None,
        "quote_kind": classify_quote(dominant),
        "unpriced_legs": unpriced,
        "multi_hop_txs": int(routes.get("multi_hop", 0)),
        "priced_with_quote_usd": bool(use_quote_usd),
    }


def mints_needing_prices(txns: list, target_mint: str) -> list[str]:
    """Quote mints that are neither the target, SOL, nor a stable."""
    found = []
    seen = set()
    for tx in txns or []:
        for transfer in (tx or {}).get("tokenTransfers") or []:
            mint = transfer.get("mint") or ""
            if not mint or mint == target_mint or mint in seen:
                continue
            if classify_quote(mint) in {"custom", "unlisted"}:
                seen.add(mint)
                found.append(mint)
    return found
