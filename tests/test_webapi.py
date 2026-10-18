"""Terminal API: auth gate, balance, paper buy/sell. No network."""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx
import pytest

os.environ["TERMINAL_FEED_LOOP"] = "0"

import sol_trading_bot as bot
import webapi
from slippage import trade_cost_usd

TOKEN = os.environ["BOT_TOKEN"]
UID = 4242
MINT = "TestMint1111111111111111111111111111111"


def _init_data(uid=UID, username="neo", auth_date=None) -> str:
    if auth_date is None:
        auth_date = int(time.time())
    user = json.dumps({"id": uid, "username": username, "first_name": "Neo"}, separators=(",", ":"))
    fields = {"auth_date": str(auth_date), "query_id": "AAE", "user": user}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def _headers(uid=UID):
    return {"Authorization": "tma " + _init_data(uid)}


def _user(balance=1000.0, approved=True):
    return {
        "username": "neo",
        "balance": balance,
        "starting_balance": balance,
        "savings": 0.0,
        "holdings": {},
        "realized_pnl": 0.0,
        "total_fees_paid": 0.0,
        "daily_trades": 0,
        "last_day": None,
        "daily_limit": None,
        "max_positions": None,
        "risk_pct": None,
        "planned": 0,
        "impulse": 0,
        "followed": 0,
        "broken": 0,
        "streak": 0,
        "best_streak": 0,
        "consec_losses": 0,
        "trade_hours": {},
        "auto_save_pct": None,
        "access_approved": approved,
        "apex_mode": False,
        "apex_vault": 0.0,
        "quick_buy_amount": 100.0,
        "sniper_filters": {"buy_amount": 20},
    }


class _Price:
    def __init__(self):
        self.price = 0.001

    async def get_token(self, contract, force=False, max_age=None):
        if contract != MINT:
            return None
        return {
            "symbol": "PEPE",
            "name": "Pepe",
            "chain": "solana",
            "price": self.price,
            "mc": 50_000,
            "liq": 20_000,
            "pair_addr": "pair",
            "dex": "raydium",
            "vol_h1": 1000,
            "vol_h24": 5000,
            "ch_m5": 1.2,
            "ch_h1": 4.0,
            "ch_h24": -2.0,
            "age_h": 3.0,
            "buy_pct": 60,
            "buys": 100,
            "sells": 40,
            "token_image": "",
            "no_mint": True,
            "no_freeze": True,
            "lp_burn": 100,
            "top10_pct": 12,
            "rug_risks": [],
        }


@pytest.fixture
async def api(monkeypatch):
    bot.users.clear()
    bot.trade_log.clear()
    webapi._feed.clear()
    monkeypatch.setattr(bot, "save_user", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_trade_log", lambda *a, **k: None)

    async def _scan():
        return []

    monkeypatch.setattr(bot, "sniper_scan", _scan)
    prices = _Price()
    monkeypatch.setattr(bot, "get_token", prices.get_token)
    app = webapi.create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, prices
    bot.users.clear()
    bot.trade_log.clear()
    webapi._feed.clear()


async def test_me_requires_auth_and_access(api):
    client, _prices = api
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/health")).status_code == 200

    bot.users[UID] = _user(approved=False)
    denied = await client.get("/api/me", headers=_headers())
    assert denied.status_code == 403

    stranger = 99
    missing = await client.get("/api/me", headers=_headers(stranger))
    assert missing.status_code == 403
    assert stranger not in bot.users

    broken = await client.get("/api/me", headers={"Authorization": "tma not-valid"})
    assert broken.status_code == 401


async def test_balance_buy_sell_and_leaderboard(api):
    client, prices = api
    bot.users[UID] = _user()
    bot.trade_log[UID] = []

    me = await client.get("/api/me", headers=_headers())
    assert me.status_code == 200
    body = me.json()
    assert body["paper"] is True
    assert body["balance"] == 1000.0
    assert body["balance_set"] is True

    bought = await client.post(
        "/api/trade/buy",
        headers=_headers(),
        json={"contract": MINT, "amount_usd": 100},
    )
    assert bought.status_code == 200, bought.text
    fee = trade_cost_usd(100, 20_000)
    ud = bot.users[UID]
    assert ud["total_fees_paid"] == pytest.approx(fee, abs=0.001)
    assert ud["balance"] == pytest.approx(1000 - 100 - fee, abs=0.01)
    assert MINT in ud["holdings"]
    assert ud["holdings"][MINT]["symbol"] == "PEPE"

    prices.price = 0.002
    pos = await client.get("/api/positions", headers=_headers())
    assert pos.status_code == 200
    row = pos.json()["positions"][0]
    assert row["price_live"] is True
    assert row["x"] == pytest.approx(2.0, abs=0.01)
    assert row["pnl"] == pytest.approx(100.0, abs=0.5)

    sold = await client.post(
        "/api/trade/sell",
        headers=_headers(),
        json={"contract": MINT, "percent": 100},
    )
    assert sold.status_code == 200, sold.text
    payload = sold.json()
    assert payload["closed"] is True
    assert payload["realized"] > 0
    assert MINT not in bot.users[UID]["holdings"]
    # Sell also pays the simulated fee, so proceeds are below the gross 2x value.
    assert payload["received"] < 200

    hist = await client.get("/api/history", headers=_headers())
    trades = hist.json()["trades"]
    assert len(trades) == 1
    assert trades[0]["symbol"] == "PEPE"
    assert trades[0]["realized_pnl"] > 0

    bot.users[7] = _user(balance=100)
    bot.users[7]["username"] = "other"
    bot.users[7]["access_approved"] = True
    bot.trade_log[7] = [{
        "symbol": "X", "contract": "c", "realized_pnl": -5, "invested": 10,
        "returned": 5, "x": 0.5, "hold_h": 1, "reason": "manual",
    }]
    board = await client.get("/api/leaderboard?sort=pnl", headers=_headers())
    assert board.status_code == 200
    rows = board.json()["rows"]
    assert rows[0]["is_me"] is True
    assert rows[0]["pnl"] > rows[1]["pnl"]


async def test_feed_and_apex_toggle(api):
    client, _prices = api
    bot.users[UID] = _user()
    webapi.record_scan(MINT, {
        "symbol": "PEPE", "name": "Pepe", "chain": "solana",
        "price": 0.001, "mc": 40000, "liq": 8000, "ch_h1": 12,
    }, {"score": 71, "verdict": "WAIT", "flags": [], "warnings": [], "strengths": ["liq"]})

    feed = await client.get("/api/feed", headers=_headers())
    assert feed.status_code == 200
    tokens = feed.json()["tokens"]
    assert tokens[0]["contract"] == MINT
    assert tokens[0]["score"] == 71

    toggled = await client.post("/api/apex/toggle", headers=_headers(), json={"enabled": True})
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is True
    assert bot.users[UID]["apex_mode"] is True

    funded = await client.post(
        "/api/apex/vault",
        headers=_headers(),
        json={"action": "fund", "amount": 250},
    )
    assert funded.status_code == 200
    assert bot.users[UID]["apex_vault"] == pytest.approx(250, abs=0.01)
    assert bot.users[UID]["balance"] < 800
