"""Market mood gauge. No network — fixtures stand in for MemeFees."""
import json
from pathlib import Path

import edge.mood as mood

FIX = Path(__file__).parent / "fixtures"


def setup_function():
    mood.reset_cache()


def test_hot_gauge_from_memefees_fixture():
    days = mood.parse_pad_daily(json.loads((FIX / "memefees_daily.json").read_text()))
    share = mood.parse_share(json.loads((FIX / "memefees_share.json").read_text()))
    assert share == 50.22
    gauge = mood.gauge_from_series(days, share)
    assert gauge["label"] == "HOT"
    assert gauge["size_mult"] == 1.15
    assert gauge["heat_scale"] == 1.08
    assert gauge["source"] == "memefees"
    assert "DefiLlama" in gauge["attribution"]
    assert gauge["fees_usd"] == 180000


def test_cold_when_fees_collapse():
    days = [
        {"day": "d1", "fees_usd": 100, "volume_usd": 100},
        {"day": "d2", "fees_usd": 100, "volume_usd": 100},
        {"day": "d3", "fees_usd": 40, "volume_usd": 40},
    ]
    gauge = mood.gauge_from_series(days, 10)
    assert gauge["label"] == "COLD"
    assert gauge["size_mult"] == 0.70
    assert gauge["heat_scale"] == 0.80


def test_gecko_fallback_and_disabled_multiplier(monkeypatch):
    gauge = mood.gauge_from_gecko_volume(1_000_000)
    assert gauge["share_7d_pct"] is None
    assert gauge["source"] == "geckoterminal"
    mood.remember(gauge)
    monkeypatch.setenv("EDGE_MARKET_MOOD", "false")
    assert mood.size_multiplier() == 1.0
    assert mood.heat_scale() == 1.0
    monkeypatch.setenv("EDGE_MARKET_MOOD", "true")
    assert mood.size_multiplier() == gauge["size_mult"]


def test_gecko_pool_volume_sum():
    payload = {"data": [{"attributes": {"volume_usd": {"h24": "10"}}}, {"attributes": {"volume_usd": {"h24": "2.5"}}}]}
    assert mood.parse_gecko_pools(payload) == 12.5
