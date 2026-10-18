"""Custom pairs, signed reserves, multi-hop volume. No network."""
import json
from pathlib import Path

import pytest

from edge.b58 import b58decode, b58encode_pubkey
from edge.quotes import (
    POOL_DISCRIMINATOR,
    USDC,
    WSOL,
    annotate_dex_pair,
    classify_quote,
    decode_pumpswap_pool,
    effective_quote_reserves,
    identify_instruction,
    observe_pool_fees,
    reset_fee_state,
    route_kind,
    spot_price_usd,
    summarize_swap_volume,
    INSTRUCTION_DISCRIMINATORS,
)
from edge.b58 import b58encode

FIXTURES = Path(__file__).parent / "fixtures"
APPLX = "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp"


def test_wsol_base58_roundtrip():
    raw = b58decode(WSOL)
    assert len(raw) == 32
    assert b58encode_pubkey(raw) == WSOL


def test_classify_quote_kinds():
    assert classify_quote(WSOL) == "sol"
    assert classify_quote(USDC) == "stable"
    assert classify_quote("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB") == "stable"
    assert classify_quote(APPLX) == "custom"
    assert classify_quote("NotAListedMint111111111111111111111111111") == "unlisted"


def test_instruction_discriminators_and_unknown_bytes():
    assert identify_instruction(INSTRUCTION_DISCRIMINATORS["multi_hop_swap"]) == "multi_hop_swap"
    assert identify_instruction(INSTRUCTION_DISCRIMINATORS["buy"]) == "buy"
    assert identify_instruction(bytes([1, 2, 3, 4, 5, 6, 7, 8])) is None
    assert identify_instruction(b"short") is None


def test_signed_virtual_reserves_and_spot():
    quote = b58decode(APPLX)
    assert len(quote) == 32
    body = bytearray(280)
    body[67:99] = quote
    virtual = (-400).to_bytes(16, "little", signed=True)
    body[237:253] = virtual
    body[263:271] = (50).to_bytes(8, "little")
    body[271:279] = (10).to_bytes(8, "little")
    decoded = decode_pumpswap_pool(POOL_DISCRIMINATOR + bytes(body))
    assert decoded["quote_mint"] == APPLX
    assert decoded["quote_kind"] == "custom"
    assert decoded["virtual_quote_reserves"] == -400
    assert effective_quote_reserves(1_000, decoded["virtual_quote_reserves"]) == 600
    assert effective_quote_reserves(10, -50) == 0
    # 600 quote units (0 decimals) at $2, 1000 base units (0 decimals) -> $1.20
    assert spot_price_usd(1000, 600, 0, 0, 2.0) == pytest.approx(1.2)


def test_fee_sweep_needs_two_observations():
    reset_fee_state()
    first = observe_pool_fees("pair", 100, 40)
    assert first["fee_sweep"] is False
    second = observe_pool_fees("pair", 80, 40)
    assert second["fee_sweep"] is True
    reset_fee_state()


def test_short_pool_omits_virtual_reserves():
    quote = b58decode(USDC)
    body = bytearray(100)
    body[67:99] = quote
    decoded = decode_pumpswap_pool(POOL_DISCRIMINATOR + bytes(body))
    assert decoded["virtual_quote_reserves"] == 0
    assert decoded["virtual_quote_reserves_missing"] is True


def test_custom_quote_volume_and_multi_hop():
    mint = "MintAAA111111111111111111111111111111111111"
    wallet = "Buyer111"
    hop = "HopMint11111111111111111111111111111111111"
    disc = b58encode(INSTRUCTION_DISCRIMINATORS["multi_hop_swap"])
    txns = [
        {
            "feePayer": wallet,
            "description": "",
            "instructions": [{"data": disc}],
            "tokenTransfers": [
                {"mint": mint, "tokenAmount": 10, "toUserAccount": wallet, "fromUserAccount": "pool"},
                {"mint": APPLX, "tokenAmount": 5, "fromUserAccount": wallet, "toUserAccount": "pool"},
                {"mint": hop, "tokenAmount": 3, "fromUserAccount": wallet, "toUserAccount": "mid"},
                {"mint": hop, "tokenAmount": 3, "toUserAccount": wallet, "fromUserAccount": "mid"},
            ],
            "nativeTransfers": [],
        }
    ]
    assert route_kind(txns[0]) == "multi_hop"
    summary = summarize_swap_volume(txns, mint, {APPLX: 2.0}, sol_usd=150.0, use_quote_usd=True)
    assert summary["volume_usd"] == pytest.approx(10.0)
    assert summary["quote_kind"] == "custom"
    assert summary["multi_hop_txs"] == 1
    assert summary["maker_count"] == 1
    sol_only = summarize_swap_volume(txns, mint, {APPLX: 2.0}, sol_usd=150.0, use_quote_usd=False)
    assert sol_only == {}


def test_dexscreener_does_not_treat_price_native_as_quote_units():
    pair = {
        "priceUsd": "0",
        "priceNative": "0.5",
        "baseToken": {"symbol": "DOG", "address": "base"},
        "quoteToken": {"symbol": "APPLX", "address": APPLX},
        "liquidity": {"base": 1000, "quote": 10},
    }
    meta = annotate_dex_pair(pair, quote_usd=2.0)
    assert meta["pair_label"] == "DOG/APPLX"
    assert meta["price_derived"] is True
    assert meta["derived_price_usd"] == pytest.approx(0.02)
    assert meta["price_indicative"] is True
    kept = annotate_dex_pair({**pair, "priceUsd": "1.25"}, quote_usd=2.0)
    assert kept["derived_price_usd"] == pytest.approx(1.25)
    assert kept["price_derived"] is False


def test_fixture_file_loads():
    # The KOL fixture is shared; this just guards the fixtures directory.
    assert json.loads((FIXTURES / "helius_kol.json").read_text())
