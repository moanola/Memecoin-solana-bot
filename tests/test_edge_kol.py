"""KOL sells, airdrops, side wallets, and boost decay. No network."""
import json
from pathlib import Path

from edge.kol import (
    apply_bag_ledger,
    boost_points,
    parse_wallet_transactions,
    side_wallets_from_transfers,
    summarize_hot,
)

WALLET = "KolWallet111111111111111111111111111111111"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "helius_kol.json").read_text())


def test_parse_buy_sell_and_airdrop():
    events = parse_wallet_transactions(FIXTURE, WALLET)
    by_sig = {e["signature"]: e for e in events}
    assert by_sig["buysig"]["side"] == "buy"
    assert by_sig["buysig"]["via"] == "swap"
    assert by_sig["buysig"]["sol_spent"] == 2.0
    assert by_sig["sellsig"]["side"] == "sell"
    assert by_sig["airdropsig"]["side"] == "in"
    assert by_sig["airdropsig"]["via"] == "transfer"
    assert by_sig["airdropsig"]["sol_spent"] == 0.0


def test_bag_percent_on_partial_sell():
    events = parse_wallet_transactions(FIXTURE, WALLET)
    balances = {}
    apply_bag_ledger(balances, list(reversed(events)))
    sell = next(e for e in events if e["signature"] == "sellsig")
    assert sell["bag_pct"] == 40.0
    assert sell["partial"] is True
    assert balances["MintAAA111111111111111111111111111111111111"] == 60.0


def test_summarize_decays_boost_and_ignores_airdrop():
    buys = [{"label": "A", "side": "buy", "via": "swap", "sol_spent": 2}]
    full = summarize_hot(buys + [{"label": "A", "side": "sell", "bag_pct": 100}])
    assert full["factor"] == 0.0
    assert full["exited"] is True
    half = summarize_hot(buys + [{"label": "A", "side": "sell", "bag_pct": 40}])
    assert half["factor"] == 0.6
    unknown = summarize_hot(buys + [{"label": "A", "side": "sell", "bag_pct": None}])
    assert unknown["factor"] == 0.5
    airdrop = summarize_hot([{"label": "A", "side": "in", "via": "transfer", "sol_spent": 0}])
    assert airdrop["factor"] == 0.0
    assert airdrop["airdrop"] is True
    assert boost_points(20, full["factor"]) == 0
    assert boost_points(20, half["factor"]) == 12


def test_side_wallets_share_a_funder():
    kol = "KOL"
    transfers = [
        {"from": "Funder", "to": kol, "sol": 1.0},
        {"from": "Funder", "to": "Side", "sol": 0.8},
        {"from": kol, "to": "Paid", "sol": 0.2},
        {"from": "Dust", "to": "Side", "sol": 0.01},
    ]
    found = side_wallets_from_transfers(kol, transfers)
    assert found["funder"] == "Funder"
    assert "Side" in found["side_wallets"]
    assert "Paid" in found["funded_by_kol"]


def test_stops_at_last_signature():
    events = parse_wallet_transactions(FIXTURE, WALLET, last_sig="airdropsig")
    assert [e["signature"] for e in events] == ["sellsig"]


def test_sniper_score_drops_kol_bonus_when_factor_is_zero(monkeypatch):
    monkeypatch.setenv("EDGE_KOL_EXITS", "true")
    import sol_trading_bot as bot

    base = {
        "chain": "solana", "age_h": 0.4, "liq": 20_000, "mc": 30_000,
        "liq_pct": 8, "buy_pct": 60, "kol_buy_count": 2, "kol_sol_total": 3.0,
        "kol_labels": ["A", "B"],
    }
    full = bot.sniper_score({**base, "kol_boost_factor": 1.0})
    gone = bot.sniper_score({**base, "kol_boost_factor": 0.0, "kol_exit_note": "KOL exited — boost removed"})
    assert full["score"] - gone["score"] == 20
    assert any("exited" in w.lower() or "boost" in w.lower() for w in gone["warnings"])
