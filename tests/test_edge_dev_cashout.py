"""Dev cash-out patterns. No network."""
from edge.dev_cashout import detect_dev_cashout, flows_from_transactions

CREATOR = "Creator"
FUNDER = "Funder"
HUB = "Hub"


def test_three_sellers_to_one_hub_alerts():
    flows = [
        {"kind": "sell", "ts": 10, "seller": "S1", "fee_payer": "S1", "sol_to": HUB, "sol_amount": 1},
        {"kind": "sell", "ts": 11, "seller": "S2", "fee_payer": "S2", "sol_to": HUB, "sol_amount": 1},
        {"kind": "sell", "ts": 12, "seller": "S3", "fee_payer": "S3", "sol_to": HUB, "sol_amount": 1},
    ]
    found = detect_dev_cashout(flows, creator=CREATOR, creator_funder=FUNDER)
    assert found["alert"] is True
    assert found["hub"] == HUB


def test_hub_paying_gas_alerts():
    flows = [
        {"kind": "sell", "ts": 10, "seller": "S1", "fee_payer": HUB, "sol_to": HUB, "sol_amount": 0.4},
        {"kind": "sell", "ts": 40, "seller": "S2", "fee_payer": HUB, "sol_to": None, "sol_amount": 0},
    ]
    found = detect_dev_cashout(flows, creator=CREATOR, creator_funder=FUNDER)
    assert found["alert"] is True
    assert "gas" in found["reason"]


def test_fee_sweep_alone_does_not_alert():
    found = detect_dev_cashout([{"kind": "fee_sweep", "ts": 1}], creator=CREATOR)
    assert found["alert"] is False


def test_flows_from_helius_style_transactions():
    mint = "Mint"
    txns = [
        {
            "timestamp": 5,
            "feePayer": "S1",
            "tokenTransfers": [
                {"mint": mint, "tokenAmount": 9, "fromUserAccount": "S1", "toUserAccount": "pool"}
            ],
            "nativeTransfers": [
                {"amount": int(1.5e9), "fromUserAccount": "pool", "toUserAccount": "S1"},
                {"amount": int(1.4e9), "fromUserAccount": "S1", "toUserAccount": HUB},
            ],
        }
    ]
    flows = flows_from_transactions(txns, mint, fee_sweep=True)
    kinds = {row["kind"] for row in flows}
    assert "sell" in kinds
    assert "fee_sweep" in kinds
