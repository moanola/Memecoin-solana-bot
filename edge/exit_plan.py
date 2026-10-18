"""Exit plan required on manual paper buys, plus a rule-break log.

A plan has three legs: take-profit (multiple of entry), invalidation
(percent below entry), and a time stop (minutes). Presets fill anything the
caller leaves out. Changing a leg away from the chosen preset is an override.
Selling by hand before any leg is hit is a rule break; its cost is the loss
on that sell (0 when the sell was still green).

APEX, sniper, and copy fills are not manual and do not get this plan. They
keep their own exits.
"""
from __future__ import annotations

import time
from datetime import datetime

PRESETS = {
    "scalp": {"tp_x": 1.5, "tp_pct": 1.0, "invalidation_pct": 12.0, "time_stop_min": 30.0},
    "standard": {"tp_x": 2.0, "tp_pct": 0.5, "invalidation_pct": 18.0, "time_stop_min": 120.0},
    "runner": {"tp_x": 3.0, "tp_pct": 0.33, "invalidation_pct": 25.0, "time_stop_min": 360.0},
}

MANUAL_EXCLUDED_MOODS = {"APEX", "AI-Sniper", "APEX-DCA", "Sniper", "Copy Trade"}


def is_manual(mood: str | None, vault_buy: bool = False) -> bool:
    if vault_buy:
        return False
    return (mood or "") not in MANUAL_EXCLUDED_MOODS


def resolve_plan(raw: dict | None = None, preset: str | None = None) -> dict:
    name = (preset or (raw or {}).get("preset") or "standard").strip().lower()
    if name not in PRESETS:
        name = "standard"
    plan = dict(PRESETS[name])
    plan["preset"] = name
    raw = raw or {}
    for key in ("tp_x", "tp_pct", "invalidation_pct", "time_stop_min"):
        if raw.get(key) is not None and raw.get(key) != "":
            plan[key] = float(raw[key])
    plan["tp_x"] = max(1.05, float(plan["tp_x"]))
    plan["tp_pct"] = min(1.0, max(0.05, float(plan["tp_pct"])))
    plan["invalidation_pct"] = min(90.0, max(3.0, float(plan["invalidation_pct"])))
    plan["time_stop_min"] = min(60 * 24 * 7, max(5.0, float(plan["time_stop_min"])))
    return plan


def overrides_against(plan: dict, preset: str | None = None) -> list[str]:
    name = preset or plan.get("preset") or "standard"
    base = PRESETS.get(name) or PRESETS["standard"]
    changed = []
    for key in ("tp_x", "tp_pct", "invalidation_pct", "time_stop_min"):
        if abs(float(plan[key]) - float(base[key])) > 1e-6:
            changed.append(key)
    return changed


def attach(ud: dict, holding: dict, raw: dict | None, mood: str | None, vault_buy: bool) -> dict | None:
    """Store a plan on a new manual position. Returns the plan or None."""
    from edge.flags import exit_default_preset, exit_plan
    if not exit_plan() or not is_manual(mood, vault_buy):
        return None
    if holding.get("exit_plan") and not raw:
        return holding["exit_plan"]
    preset = None
    if raw and raw.get("preset"):
        preset = raw.get("preset")
    elif not raw:
        preset = exit_default_preset()
    plan = resolve_plan(raw, preset)
    holding["exit_plan"] = plan
    changed = overrides_against(plan, plan["preset"])
    if changed:
        ud.setdefault("rule_overrides", []).append({
            "ts": time.time(),
            "symbol": holding.get("symbol"),
            "contract": holding.get("contract"),
            "preset": plan["preset"],
            "fields": changed,
            "plan": dict(plan),
            "outcome_pnl": None,
        })
        if len(ud["rule_overrides"]) > 200:
            ud["rule_overrides"] = ud["rule_overrides"][-200:]
    return plan


def evaluate(plan: dict | None, holding: dict, price: float, now: datetime | None = None) -> str | None:
    """Return tp, invalidation, time_stop, or None when the plan is intact."""
    if not plan or price <= 0:
        return None
    avg = float(holding.get("avg_price") or 0)
    if avg <= 0:
        return None
    multiple = price / avg
    if multiple >= float(plan["tp_x"]) and not plan.get("tp_done"):
        return "tp"
    drop = (price - avg) / avg * 100.0
    if drop <= -float(plan["invalidation_pct"]):
        return "invalidation"
    bought = holding.get("bought_at")
    if isinstance(bought, datetime):
        now = now or datetime.now()
        held_min = (now - bought).total_seconds() / 60.0
        if held_min >= float(plan["time_stop_min"]):
            return "time_stop"
    return None


def sell_fraction(plan: dict | None, why: str | None) -> float:
    """Share of the position this exit leg sells. Take-profit uses tp_pct."""
    if not why:
        return 0.0
    if why != "tp":
        return 1.0
    try:
        pct = float((plan or {}).get("tp_pct") if (plan or {}).get("tp_pct") is not None else 1.0)
    except (TypeError, ValueError):
        pct = 1.0
    if pct != pct:  # NaN
        pct = 1.0
    return min(1.0, max(0.05, pct))


def note_early_sell(ud: dict, holding: dict, price: float, realized: float, reason: str) -> dict | None:
    """Log a manual sell that happened before the plan said to get out."""
    plan = holding.get("exit_plan")
    if not plan or reason not in {"manual", ""}:
        return None
    if evaluate(plan, holding, price) is not None:
        return None
    cost = round(min(float(realized or 0), 0.0), 4)
    row = {
        "ts": time.time(),
        "symbol": holding.get("symbol"),
        "contract": holding.get("contract"),
        "kind": "early_manual_sell",
        "pnl": round(float(realized or 0), 4),
        "cost": cost,
        "detail": "sold before TP, invalidation, and time stop",
    }
    ud.setdefault("rule_breaks", []).append(row)
    if len(ud["rule_breaks"]) > 200:
        ud["rule_breaks"] = ud["rule_breaks"][-200:]
    _stamp_override_outcome(ud, holding.get("contract"), realized)
    return row


def _stamp_override_outcome(ud: dict, contract: str | None, realized: float) -> None:
    if not contract:
        return
    for row in reversed(ud.get("rule_overrides") or []):
        if row.get("contract") == contract and row.get("outcome_pnl") is None:
            row["outcome_pnl"] = round(float(realized or 0), 4)
            break


def nightly_report(ud: dict, day_start_ts: float) -> dict:
    breaks = [b for b in ud.get("rule_breaks") or [] if float(b.get("ts") or 0) >= day_start_ts]
    overrides = [o for o in ud.get("rule_overrides") or [] if float(o.get("ts") or 0) >= day_start_ts]
    cost = round(sum(float(b.get("cost") or 0) for b in breaks), 4)
    pnl = round(sum(float(b.get("pnl") or 0) for b in breaks), 4)
    override_cost = round(sum(min(float(o.get("outcome_pnl") or 0), 0.0) for o in overrides if o.get("outcome_pnl") is not None), 4)
    return {
        "breaks": len(breaks),
        "break_pnl": pnl,
        "break_cost": cost,
        "overrides": len(overrides),
        "override_loss": override_cost,
        "rows": breaks[-8:],
    }


def format_report(report: dict) -> str:
    if not report or (not report.get("breaks") and not report.get("overrides")):
        return ""
    return (
        "📋 *RULE BREAKS TODAY*\n"
        f"Early sells: *{report['breaks']}*  ·  net PnL *${report['break_pnl']:,.2f}*\n"
        f"Loss cost of those sells: *${abs(report['break_cost']):,.2f}*\n"
        f"Plan overrides: *{report['overrides']}*  ·  closed-loss *${abs(report['override_loss']):,.2f}*"
    )
