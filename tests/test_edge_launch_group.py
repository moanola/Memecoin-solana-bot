"""Launch-group clustering and the APEX sold-percent gate. No network."""
from edge.launch_group import (
    JITO_TIP_ACCOUNTS,
    assess_launch_group,
    bag_sold_pct,
    exit_triggered,
)

MINT = "MintAAA111111111111111111111111111111111111"
TIP = next(iter(JITO_TIP_ACCOUNTS))
FUNDER = "Funder111"


def _buy(wallet, slot, ts, amount=10, jito=True, funder=FUNDER):
    natives = []
    if jito:
        natives.append({"toUserAccount": TIP, "fromUserAccount": wallet, "amount": 10000})
    if funder:
        natives.append({"toUserAccount": wallet, "fromUserAccount": funder, "amount": int(0.2 * 1e9)})
    return {
        "signature": wallet,
        "feePayer": wallet,
        "slot": slot,
        "timestamp": ts,
        "fee": 5000,
        "computeUnitsConsumed": 80000,
        "tokenTransfers": [
            {"mint": MINT, "tokenAmount": amount, "toUserAccount": wallet, "fromUserAccount": "pool"}
        ],
        "nativeTransfers": natives,
    }


def test_same_slot_jito_cluster_and_sold_percent():
    txns = [_buy("A", 10, 1000), _buy("B", 10, 1001), _buy("C", 10, 1002), _buy("Late", 99, 5000, jito=False, funder=None)]
    # newest-first, as Helius returns them
    group = assess_launch_group(list(reversed(txns)), MINT, balances={"A": 0, "B": 10, "C": 10}, created_at_ts=1000)
    assert group["found"] is True
    assert group["size"] == 3
    assert "Late" not in group["wallets"]
    assert group["sold_pct"] == 33.33
    assert group["confident"] is True
    assert exit_triggered(group, 40) is False
    dumped = assess_launch_group(list(reversed(txns)), MINT, balances={"A": 0, "B": 0, "C": 0}, created_at_ts=1000)
    assert exit_triggered(dumped, 40) is True


def test_unknown_balances_do_not_exit():
    members = [{"wallet": "A", "amount": 10}, {"wallet": "B", "amount": 10}]
    assert bag_sold_pct(members, None) == 0.0
    assert bag_sold_pct(members, {}) == 0.0
    # A provided map treats a missing wallet as fully sold.
    assert bag_sold_pct(members, {"A": 0}) == 100.0
    assert bag_sold_pct(members, {"A": 0, "B": 10}) == 50.0


def test_full_page_without_launch_is_not_confident():
    txns = [_buy(f"W{i}", 50, 9_000 + i) for i in range(100)]
    group = assess_launch_group(txns, MINT, balances={f"W{i}": 0 for i in range(100)}, created_at_ts=100, page_limit=100)
    assert group["found"] is True
    assert group["confident"] is False
    assert group["partial"] is True
    assert exit_triggered(group, 40) is False


def test_identical_fee_cluster_without_jito():
    txns = [
        _buy("A", 3, 10, jito=False, funder="F1"),
        _buy("B", 3, 11, jito=False, funder="F2"),
        _buy("C", 3, 12, jito=False, funder="F3"),
    ]
    group = assess_launch_group(txns, MINT, created_at_ts=10, page_limit=100)
    assert group["found"] is True
    assert group["size"] == 3
    assert group["jito"] is False
