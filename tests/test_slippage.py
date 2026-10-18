import pytest

import slippage
from config import SIM_DEX_FEE_PCT, SIM_GAS_USD, SIM_SLIPPAGE_PCT


def test_small_trade_deep_pool_uses_floor():
    # $20 into a $1M pool: impact ~0.004% -> floor (old flat behaviour)
    assert slippage.slippage_pct(20, 1_000_000) == SIM_SLIPPAGE_PCT


def test_unknown_liquidity_uses_floor():
    assert slippage.slippage_pct(500, None) == SIM_SLIPPAGE_PCT
    assert slippage.slippage_pct(500, 0) == SIM_SLIPPAGE_PCT


def test_constant_product_impact():
    # $1,000 into a $10k pool -> quote reserve $5k -> 1000/6000
    assert slippage.price_impact_pct(1_000, 10_000) == pytest.approx(1 / 6)
    assert slippage.slippage_pct(1_000, 10_000) == pytest.approx(1 / 6)


def test_impact_grows_with_size_and_is_capped():
    a = slippage.slippage_pct(100, 20_000)
    b = slippage.slippage_pct(1_000, 20_000)
    c = slippage.slippage_pct(10_000, 20_000)
    assert SIM_SLIPPAGE_PCT <= a < b < c < 1
    assert slippage.slippage_pct(1e12, 1) <= slippage.MAX_SLIPPAGE_PCT


def test_trade_cost_matches_old_formula_when_floored():
    usd = 50.0
    old = round(usd * (SIM_DEX_FEE_PCT + SIM_SLIPPAGE_PCT) + SIM_GAS_USD, 4)
    assert slippage.trade_cost_usd(usd, 5_000_000) == old


async def test_do_buy_core_charges_price_impact(monkeypatch):
    import sol_trading_bot as bot

    calls = {}

    async def fake_get_token(contract, force=False, max_age=None):
        calls["max_age"] = max_age
        return {"price": 0.001, "liq": 4_000.0, "mc": 50_000.0, "symbol": "TEST",
                "name": "Test", "chain": "solana"}

    monkeypatch.setattr(bot, "get_token", fake_get_token)
    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)
    uid = 999001
    bot.users.pop(uid, None)
    ud = bot.get_user(uid, "tester")
    ud["balance"] = 1_000.0
    try:
        await bot.do_buy_core(ud, uid, "MintTest111", 500.0)
    finally:
        bot.users.pop(uid, None)
    expected_fee = slippage.trade_cost_usd(500.0, 4_000.0)   # 500/(2000+500) = 20% impact
    assert expected_fee > 500 * 0.1
    assert ud["total_fees_paid"] == pytest.approx(expected_fee)
    assert ud["balance"] == pytest.approx(1_000.0 - 500.0 - expected_fee, abs=1e-3)
    assert calls["max_age"] == bot.FILL_MAX_PRICE_AGE_S   # fresh quote requested at fill
