"""Holder velocity and retention. No network."""
from edge.holders import holders_per_hour, reentry_allowed, retention_from_swaps, score_delta


def test_holders_per_hour_ignores_zero():
    assert holders_per_hour(0, 1) is None
    assert holders_per_hour(None, 1) is None
    assert holders_per_hour(70, 0) is None
    assert holders_per_hour(70, 1) == 70


def test_retention_of_first_buyers():
    swaps = []
    for i in range(4):
        swaps.append({"wallet": f"W{i}", "side": "buy", "amount": 10})
    swaps.append({"wallet": "W0", "side": "sell", "amount": 10})
    swaps.append({"wallet": "W1", "side": "sell", "amount": 9.5})
    assert retention_from_swaps(swaps) == 50.0


def test_score_and_reentry():
    delta, notes = score_delta(90, 70)
    assert delta == 12
    assert notes
    slow, _ = score_delta(2, 10)
    assert slow == -9
    assert reentry_allowed({}, 25) == (True, "")
    blocked, why = reentry_allowed({"holder_retention_pct": 10}, 25)
    assert blocked is False
    assert "10%" in why
    ok, _ = reentry_allowed({"holder_retention_pct": 40}, 25)
    assert ok is True
