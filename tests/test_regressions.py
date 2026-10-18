"""Regressions from the live-data terminal pass. No network."""
import asyncio
from datetime import datetime, timedelta

import pytest

import slippage
from edge.exit_plan import evaluate, resolve_plan, sell_fraction
from edge.quotes import annotate_dex_pair


def test_bonding_curve_uses_lamports_and_dev_pct_is_unknown_without_field():
    import sol_trading_bot as bot

    # 42.5 SOL in lamports sits halfway from 30 to 55.
    assert bot.pumpfun_curve_pct({"virtual_sol_reserves": 42_500_000_000}) == 50.0
    assert bot.pumpfun_curve_pct({"virtual_sol_reserves": 30_000_000_000}) == 0.0
    assert bot.pumpfun_curve_pct({"complete": True, "virtual_sol_reserves": 1}) == 100.0
    # v3 omits creator holdings. 0% would be a lie.
    assert bot.pumpfun_dev_pct({"total_supply": 1_000_000_000_000_000}) is None
    # Raw units, 6 decimals, supply 1e15 → 10%.
    assert bot.pumpfun_dev_pct({
        "creator_token_holdings": 1e14,
        "total_supply": 1e15,
    }) == 10.0
    assert bot.PUMPFUN_COINS_PARAMS["sort"] == "created_timestamp"
    assert bot._pumpfun_host_unusable(530) is True
    assert bot._pumpfun_host_unusable(400) is True
    assert bot._pumpfun_host_unusable(200) is False


async def test_pumpfun_feed_sort_and_dead_host(monkeypatch):
    import sol_trading_bot as bot

    class Resp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body

        def json(self):
            if self.status_code >= 500:
                raise ValueError("not json")
            return self._body

    calls = []

    class Client:
        async def get(self, url, params=None, headers=None, timeout=None):
            calls.append((url, dict(params or {})))
            if "frontend-api-v3" in url:
                return Resp(400, {"error": "Must be one of: created_timestamp"})
            if "frontend-api.pump.fun" in url:
                return Resp(530, None)
            return Resp(200, [])

    async def fake_http():
        return Client()

    monkeypatch.setattr(bot, "get_http", fake_http)
    out = await bot.sniper_scan()
    assert out == []
    pump_calls = [c for c in calls if "pump.fun" in c[0]]
    assert pump_calls
    assert all(c[1].get("sort") == "created_timestamp" for c in pump_calls)
    assert any(c[0].startswith("https://frontend-api.pump.fun") for c in pump_calls)


async def test_pumpfun_v3_list_parses_curve(monkeypatch):
    import sol_trading_bot as bot

    class Resp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body

        def json(self):
            return self._body

    class Client:
        async def get(self, url, params=None, headers=None, timeout=None):
            if "frontend-api-v3" in url:
                assert params["sort"] == "created_timestamp"
                return Resp(200, [{
                    "mint": "MintPump111111111111111111111111111111",
                    "virtual_sol_reserves": 42_500_000_000,
                    "reply_count": 4,
                    "twitter": "https://x.com/coin",
                    "name": "Coin",
                    "symbol": "COIN",
                    "total_supply": 1_000_000_000_000_000,
                }])
            return Resp(200, [])

    async def fake_http():
        return Client()

    monkeypatch.setattr(bot, "get_http", fake_http)
    out = await bot.sniper_scan()
    assert len(out) == 1
    assert out[0]["_pf_curve"] == 50.0
    assert out[0]["_pf_dev_pct"] is None
    assert out[0]["_pf_virtual_sol_lamports"] == 42_500_000_000


def test_partial_close_history_matches_running_realized(monkeypatch):
    import sol_trading_bot as bot

    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)
    uid = 991001
    bot.users.pop(uid, None)
    bot.trade_log.pop(uid, None)
    ud = bot.get_user(uid, "acct")
    ud["balance"] = 1_000.0
    ud["realized_pnl"] = 0.0
    ud["holdings"]["Mint"] = {
        "symbol": "DOG", "name": "Dog", "chain": "solana",
        "amount": 1_000.0, "avg_price": 0.1,
        "total_invested": 100.0, "buy_cost": 100.0,
        "total_sold": 0.0, "realized_total": 0.0, "entry_fees": 0.0,
        "bought_at": datetime.now(), "mood": "", "auto_sells": [],
    }
    try:
        bot.sell_core(ud, uid, "Mint", 40.0, 0.08, "manual", liq=1_000_000)
        assert "Mint" in ud["holdings"]
        assert ud["holdings"]["Mint"]["buy_cost"] == 100.0
        left = ud["holdings"]["Mint"]["amount"] * 0.08
        bot.sell_core(ud, uid, "Mint", left, 0.08, "manual", liq=1_000_000)
        assert "Mint" not in ud["holdings"]
        log = bot.trade_log[uid]
        assert len(log) == 1
        assert log[0]["invested"] == pytest.approx(100.0, abs=0.05)
        assert log[0]["realized_pnl"] == pytest.approx(ud["realized_pnl"], abs=0.02)
        assert log[0]["realized_pnl"] == pytest.approx(log[0]["returned"] - log[0]["invested"], abs=0.05)
        # Last leg alone is not the position PnL.
        assert log[0]["returned"] > 0
    finally:
        bot.users.pop(uid, None)
        bot.trade_log.pop(uid, None)


def test_take_profit_sells_plan_slice_and_marks_leg(monkeypatch):
    import sol_trading_bot as bot

    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)
    monkeypatch.setenv("EDGE_EXIT_PLAN", "true")
    plan = resolve_plan({"preset": "standard"})
    assert sell_fraction(plan, "tp") == 0.5
    assert sell_fraction(resolve_plan({"preset": "runner"}), "tp") == pytest.approx(0.33)
    assert sell_fraction(plan, "invalidation") == 1.0
    uid = 991002
    bot.users.pop(uid, None)
    bot.trade_log.pop(uid, None)
    ud = bot.get_user(uid, "tp")
    ud["balance"] = 0.0
    ud["holdings"]["C"] = {
        "symbol": "DOG", "name": "Dog", "chain": "solana",
        "amount": 100.0, "avg_price": 1.0,
        "total_invested": 100.0, "buy_cost": 100.0,
        "total_sold": 0.0, "realized_total": 0.0,
        "bought_at": datetime.now() - timedelta(minutes=5),
        "mood": "", "exit_plan": dict(plan), "auto_sells": [],
    }
    try:
        first = bot.apply_exit_plan_leg(ud, uid, "C", 2.0, liq=1_000_000)
        assert first["why"] == "tp"
        assert first["fraction"] == 0.5
        assert "C" in ud["holdings"]
        assert ud["holdings"]["C"]["amount"] == pytest.approx(50.0, abs=0.01)
        assert ud["holdings"]["C"]["exit_plan"]["tp_done"] is True
        assert evaluate(ud["holdings"]["C"]["exit_plan"], ud["holdings"]["C"], 2.2) is None
        assert bot.apply_exit_plan_leg(ud, uid, "C", 2.2, liq=1_000_000) is None
    finally:
        bot.users.pop(uid, None)
        bot.trade_log.pop(uid, None)


async def test_fallback_never_upgrades_score_verdict(monkeypatch):
    import sol_trading_bot as bot

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    info = {
        "symbol": "T", "mc": 50_000, "liq": 20_000, "age_h": 1.0,
        "buy_pct_h1": 60, "ch_h1": 5, "ch_m5": 1, "chain": "solana",
    }
    ud = {"sniper_filters": {"buy_amount": 50}, "balance": 1_000, "sniper_log": []}
    wait = {"score": 60, "verdict": "WAIT", "flags": [], "strengths": [], "warnings": []}
    ai = await bot.ai_analyze_token(info, wait, ud)
    assert ai["verdict"] == "WAIT"
    assert bot.verdict_allows_auto_buy(ai, wait) is False
    skipped = {"score": 80, "verdict": "SKIP", "flags": [], "strengths": ["x"], "warnings": []}
    ai_skip = await bot.ai_analyze_token(info, skipped, ud)
    assert ai_skip["verdict"] == "SKIP"
    assert bot.verdict_allows_auto_buy(ai_skip, skipped) is False
    snipe = {"score": 80, "verdict": "SNIPE", "flags": [], "strengths": ["x"], "warnings": []}
    ai_snipe = await bot.ai_analyze_token(info, snipe, ud)
    assert ai_snipe["verdict"] == "SNIPE"
    assert bot.verdict_allows_auto_buy(ai_snipe, snipe) is True
    assert "High MC" not in " ".join(ai_snipe.get("red_flags") or [])


def test_custom_pairs_skip_non_solana():
    pair = {
        "chainId": "ethereum",
        "priceUsd": "1",
        "baseToken": {"symbol": "DOG", "address": "base"},
        "quoteToken": {"symbol": "APPLX", "address": "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp"},
    }
    meta = annotate_dex_pair(pair, quote_usd=2.0)
    assert meta["quote_kind"] == ""
    assert meta["price_indicative"] is False
    # Missing chainId still classifies, so Solana cards without the field keep working.
    sol = annotate_dex_pair({k: v for k, v in pair.items() if k != "chainId"}, quote_usd=2.0)
    assert sol["quote_kind"] == "custom"


def test_zero_liquidity_refuses_unless_curve_reserves_cover_it():
    assert slippage.tradable_liquidity_usd(0, None) is None
    assert slippage.tradable_liquidity_usd(None, None) is None
    # Floor behaviour for a percent request is unchanged.
    assert slippage.slippage_pct(500, 0) == slippage.SIM_SLIPPAGE_PCT
    # Quote-side reserves are doubled so impact uses that side as liq/2.
    assert slippage.tradable_liquidity_usd(0, 4_000) == 8_000


async def test_do_buy_refuses_zero_liq_and_accepts_curve(monkeypatch):
    import sol_trading_bot as bot

    async def no_fetch(_mint):
        return None

    async def sol_px():
        return 100.0

    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_fetch_pumpfun_virtual_sol", no_fetch)
    monkeypatch.setattr(bot, "get_sol_price", sol_px)

    async def dead(_contract, force=False, max_age=None):
        return {"price": 0.001, "liq": 0, "mc": 10_000, "symbol": "Z", "name": "Z", "chain": "solana"}

    monkeypatch.setattr(bot, "get_token", dead)
    uid = 991003
    bot.users.pop(uid, None)
    ud = bot.get_user(uid, "liq")
    ud["balance"] = 500.0
    try:
        refused = await bot.do_buy_core(ud, uid, "MintZero", 20.0)
        assert isinstance(refused, str)
        assert "liquidity" in refused.lower()
        assert "MintZero" not in ud["holdings"]

        async def curved(_contract, force=False, max_age=None):
            return {
                "price": 0.001, "liq": 0, "mc": 10_000, "symbol": "C", "name": "C", "chain": "solana",
                "virtual_sol_reserves": 40_000_000_000,
            }

        monkeypatch.setattr(bot, "get_token", curved)
        ud["balance"] = 500.0
        bought = await bot.do_buy_core(ud, uid, "MintCurve", 20.0)
        assert isinstance(bought, tuple)
        assert ud["holdings"]["MintCurve"]["liq_at_buy"] > 0
    finally:
        bot.users.pop(uid, None)


def test_mood_cache_honours_ttl():
    import time
    import edge.mood as mood

    mood.reset_cache()
    mood.remember({"label": "HOT", "score": 80, "size_mult": 1.15, "heat_scale": 1.08, "source": "memefees"})
    assert mood.cached(max_age_s=900)["label"] == "HOT"
    mood._cache["ts"] = time.time() - 1_000
    assert mood.cached(max_age_s=900) is None
    mood.reset_cache()


def test_apex_heat_uses_vault_not_main_balance():
    import sol_trading_bot as bot

    ud = {
        "balance": 5_000.0,
        "apex_vault": 80.0,
        "holdings": {
            "c": {"mood": "APEX", "total_invested": 20.0},
            "m": {"mood": "", "total_invested": 400.0},
        },
    }
    # 20 / (80 + 20) = 20%. The $5,000 cash balance must not dilute this to ~0.
    assert bot.apex_capital_heat(ud) == pytest.approx(0.20)
