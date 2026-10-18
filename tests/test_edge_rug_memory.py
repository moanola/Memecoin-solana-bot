"""Rug-wallet memory and the kv round trip. No network."""
import edge.rug_memory as rug
from edge.runtime_state import flush, restore


def setup_function():
    rug.reset()


def test_fast_drop_marks_creator_and_penalises_the_next_mint():
    rug.note_scan("old", "Creator", "Funder", ts=1_000)
    rug.observe("old", {"price": 1.0, "liq": 5_000}, ts=1_000)
    reason = rug.observe("old", {"price": 0.05, "liq": 5_000}, ts=1_000 + 10 * 60)
    assert reason == "fast_drop"
    nxt = {}
    rug.apply_to_info({"creator": "Creator", "creator_funder": "Other"}, "new")
    # apply_to_info mutates the dict it is given
    info = {"creator": "Creator", "creator_funder": "Other"}
    rug.apply_to_info(info, "new")
    assert info["rug_memory_penalty"] == -15
    assert "creator" in info["rug_memory_note"]
    nxt = {"creator": "Fresh", "creator_funder": "Funder"}
    rug.apply_to_info(nxt, "newer")
    assert nxt["rug_memory_penalty"] == -8


def test_lp_pull_and_group_dump():
    rug.observe("lp", {"price": 1, "liq": 2_000}, ts=1)
    assert rug.observe("lp", {"price": 1, "liq": 100}, ts=2) == "lp_pull"
    rug.observe("gd", {"price": 1, "liq": 2_000, "launch_group_sold_pct": 10, "launch_group_confident": True}, ts=1)
    assert rug.observe(
        "gd",
        {"price": 1, "liq": 2_000, "launch_group_sold_pct": 80, "launch_group_confident": True},
        ts=2,
    ) == "group_dump"


def test_sqlite_roundtrip():
    rug.note_scan("m", "Creator", None, ts=1)
    rug.mark_rug("m", "fast_drop", ts=2)
    flush()
    rug.reset()
    assert rug.lookup("Creator", None)["penalty"] == 0
    restore()
    assert rug.lookup("Creator", None)["penalty"] == -15
