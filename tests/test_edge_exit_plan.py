"""Exit plans and the rule-break log. No network."""
from datetime import datetime, timedelta

import pytest

from edge.exit_plan import (
    attach,
    evaluate,
    format_report,
    is_manual,
    nightly_report,
    note_early_sell,
    overrides_against,
    resolve_plan,
)


def test_presets_and_clamps():
    scalp = resolve_plan({"preset": "scalp"})
    assert scalp["tp_x"] == 1.5
    assert scalp["time_stop_min"] == 30
    clamped = resolve_plan({"preset": "nope", "tp_x": 1.0, "invalidation_pct": 99, "time_stop_min": 1, "tp_pct": 2})
    assert clamped["preset"] == "standard"
    assert clamped["tp_x"] == 1.05
    assert clamped["invalidation_pct"] == 90
    assert clamped["time_stop_min"] == 5
    assert clamped["tp_pct"] == 1.0
    assert overrides_against(resolve_plan({"preset": "standard", "tp_x": 2.4})) == ["tp_x"]


def test_manual_moods_only():
    assert is_manual("") is True
    assert is_manual("APEX") is False
    assert is_manual("Sniper") is False
    assert is_manual("Copy Trade") is False
    assert is_manual("", vault_buy=True) is False


def test_evaluate_and_early_sell_cost():
    plan = resolve_plan({"preset": "standard"})
    holding = {"avg_price": 1.0, "bought_at": datetime.now() - timedelta(minutes=10), "symbol": "DOG", "contract": "c"}
    assert evaluate(plan, holding, 2.0) == "tp"
    assert evaluate(plan, holding, 0.8) == "invalidation"
    old = {"avg_price": 1.0, "bought_at": datetime.now() - timedelta(minutes=130)}
    assert evaluate(plan, old, 1.1) == "time_stop"
    assert evaluate(plan, holding, 1.2) is None
    ud = {}
    row = note_early_sell(ud, {**holding, "exit_plan": plan}, 1.2, -4.5, "manual")
    assert row["cost"] == -4.5
    assert ud["rule_breaks"]
    assert note_early_sell(ud, {**holding, "exit_plan": plan}, 2.1, 3, "manual") is None
    assert note_early_sell(ud, {**holding, "exit_plan": plan}, 0.5, -1, "exit_invalidation") is None


def test_attach_logs_override_and_nightly_report():
    ud = {}
    holding = {"symbol": "DOG", "contract": "c"}
    plan = attach(ud, holding, {"preset": "scalp", "tp_x": 1.8}, "", False)
    assert plan["tp_x"] == 1.8
    assert ud["rule_overrides"][0]["fields"] == ["tp_x"]
    assert attach(ud, {}, None, "APEX", False) is None
    note_early_sell(ud, {**holding, "exit_plan": plan, "avg_price": 1, "bought_at": datetime.now()}, 1.1, -2, "manual")
    report = nightly_report(ud, 0)
    assert report["breaks"] == 1
    assert report["break_cost"] == -2
    assert report["overrides"] == 1
    text = format_report(report)
    assert "RULE BREAKS" in text
    assert format_report({"breaks": 0, "overrides": 0}) == ""


async def test_do_buy_core_stores_plan_for_manual_only(monkeypatch):
    import sol_trading_bot as bot

    async def fake_get_token(contract, force=False, max_age=None):
        return {"price": 0.001, "liq": 1_000_000, "mc": 50_000, "symbol": "TEST", "name": "Test", "chain": "solana"}

    monkeypatch.setattr(bot, "get_token", fake_get_token)
    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)
    monkeypatch.setenv("EDGE_EXIT_PLAN", "true")
    uid = 999777
    bot.users.pop(uid, None)
    ud = bot.get_user(uid, "planner")
    ud["balance"] = 1_000.0
    try:
        await bot.do_buy_core(ud, uid, "MintPlan", 25.0, mood="", exit_plan={"preset": "scalp"})
        assert ud["holdings"]["MintPlan"]["exit_plan"]["preset"] == "scalp"
        ud["balance"] = 1_000.0
        await bot.do_buy_core(ud, uid, "MintApex", 25.0, mood="APEX")
        assert "exit_plan" not in ud["holdings"]["MintApex"]
    finally:
        bot.users.pop(uid, None)
        bot.trade_log.pop(uid, None)
