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


async def test_unknown_exit_preset_is_422(api):
    client, _prices = api
    bot.users[UID] = _user()
    res = await client.post(
        "/api/trade/buy",
        headers=_headers(),
        json={"contract": MINT, "amount_usd": 25, "preset": "yolo"},
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list)
    assert "preset" in res.text.lower()
    assert MINT not in bot.users[UID]["holdings"]


async def test_early_sell_is_a_rule_break_not_a_streak(api):
    client, _prices = api
    bot.users[UID] = _user()
    bot.trade_log[UID] = []
    bought = await client.post(
        "/api/trade/buy", headers=_headers(),
        json={"contract": MINT, "amount_usd": 100, "preset": "standard"},
    )
    assert bought.status_code == 200, bought.text
    pos = await client.get("/api/positions", headers=_headers())
    row = pos.json()["positions"][0]
    assert row["pnl_net"] < 0
    sold = await client.post(
        "/api/trade/sell", headers=_headers(),
        json={"contract": MINT, "percent": 100},
    )
    assert sold.status_code == 200, sold.text
    ud = bot.users[UID]
    assert ud["streak"] == 0
    assert ud["broken"] >= 1
    assert ud.get("rule_breaks")
    me = (await client.get("/api/me", headers=_headers())).json()
    hist = (await client.get("/api/history", headers=_headers())).json()["trades"]
    assert hist[0]["closed_at"].endswith("Z")
    assert sum(t["realized_pnl"] for t in hist) == pytest.approx(me["realized_pnl"], abs=0.05)
    assert hist[0]["invested"] == pytest.approx(100, abs=1)


async def test_partial_then_flat_history_matches_header(api, monkeypatch):
    client, prices = api
    bot.users[UID] = _user()
    bot.trade_log[UID] = []
    await client.post(
        "/api/trade/buy", headers=_headers(),
        json={"contract": MINT, "amount_usd": 100, "preset": "runner"},
    )
    prices.price = 0.0008
    await client.post(
        "/api/trade/sell", headers=_headers(),
        json={"contract": MINT, "percent": 40},
    )
    assert MINT in bot.users[UID]["holdings"]
    await client.post(
        "/api/trade/sell", headers=_headers(),
        json={"contract": MINT, "percent": 100},
    )
    me = (await client.get("/api/me", headers=_headers())).json()
    hist = (await client.get("/api/history", headers=_headers())).json()["trades"]
    assert len(hist) == 1
    assert hist[0]["invested"] == pytest.approx(100, abs=1)
    assert sum(t["realized_pnl"] for t in hist) == pytest.approx(me["realized_pnl"], abs=0.05)


async def test_leaderboard_live_mark_and_win_streak(api):
    client, _prices = api
    bot.users[UID] = _user(balance=900)
    bot.users[UID]["best_streak"] = 4
    bot.trade_log[UID] = [
        {"symbol": "A", "realized_pnl": -1, "closed_at": "2026-01-01T00:00:00Z"},
        {"symbol": "B", "realized_pnl": -1, "closed_at": "2026-01-02T00:00:00Z"},
        {"symbol": "C", "realized_pnl": 5, "closed_at": "2026-01-03T00:00:00Z"},
        {"symbol": "D", "realized_pnl": -1, "closed_at": "2026-01-04T00:00:00Z"},
    ]
    bot.users[UID]["holdings"] = {
        MINT: {"symbol": "PEPE", "amount": 100, "total_invested": 10, "avg_price": 0.1, "mood": ""},
    }
    bot._token_cache[MINT] = {"ts": time.time(), "data": {"price": 0.5}}
    board = await client.get("/api/leaderboard?sort=equity", headers=_headers())
    row = next(r for r in board.json()["rows"] if r["is_me"])
    assert row["equity"] == pytest.approx(950, abs=0.05)
    assert row["win_rate"] == 25.0
    assert row["streak"] == 1


async def test_apex_off_is_not_halted_and_open_position_has_heat(api):
    client, _prices = api
    ud = _user(balance=5_000)
    ud["apex_mode"] = False
    ud["apex_vault"] = 0.0
    bot.users[UID] = ud
    off = (await client.get("/api/apex", headers=_headers())).json()
    assert off["state"] == "off"
    assert off["halted"] is False
    ud["apex_mode"] = True
    ud["apex_vault"] = 80.0
    ud["apex_daily_pnl"] = 0.0
    ud["apex_session_start_bal"] = 100.0
    ud["holdings"] = {
        MINT: {
            "symbol": "LARPSCAN", "amount": 20, "total_invested": 20, "avg_price": 1,
            "mood": "APEX", "stop_loss_pct": 22, "apex_trail_pct": 0.22,
        },
    }
    on = (await client.get("/api/apex", headers=_headers())).json()
    assert on["positions"] == 1
    assert on["heat_pct"] == pytest.approx(20.0, abs=0.2)
    assert on["win_rate"] is None
    detail = await client.get(f"/api/tokens/{MINT}", headers=_headers())
    assert detail.status_code == 200, detail.text
    rules = detail.json()["position"]["apex_exit"]["rules"]
    assert any("Trail" in r for r in rules)
    assert any("2" in r for r in rules)


async def test_concurrent_feed_refresh_is_one_scan(api, monkeypatch):
    import asyncio

    client, _prices = api
    bot.users[UID] = _user()
    webapi._feed_refresh_task = None
    calls = {"n": 0}

    async def slow():
        calls["n"] += 1
        await asyncio.sleep(0.3)
        return []

    monkeypatch.setattr(bot, "sniper_scan", slow)
    a, b = await asyncio.gather(
        client.get("/api/feed?refresh=true", headers=_headers()),
        client.get("/api/feed?refresh=true", headers=_headers()),
    )
    assert a.status_code == 200 and b.status_code == 200
    assert calls["n"] == 1


async def test_equity_includes_vault_and_open_partials(api):
    client, _prices = api
    ud = _user(balance=900)
    ud["apex_vault"] = 80.0
    ud["savings"] = 10.0
    ud["realized_pnl"] = -8.0
    ud["holdings"] = {
        MINT: {
            "symbol": "PEPE", "amount": 100, "total_invested": 10,
            "avg_price": 0.1, "mood": "APEX", "realized_total": -3.0,
        },
    }
    bot.users[UID] = ud
    bot.trade_log[UID] = [
        {"symbol": "A", "realized_pnl": -5, "closed_at": "2026-01-01T00:00:00Z"},
    ]
    bot._token_cache[MINT] = {"ts": time.time(), "data": {"price": 0.5}}
    me = (await client.get("/api/me", headers=_headers())).json()
    # 900 cash + 10 savings + 80 vault + 50 live mark
    assert me["equity"] == pytest.approx(1040, abs=0.05)
    board = await client.get("/api/leaderboard?sort=equity", headers=_headers())
    row = next(r for r in board.json()["rows"] if r["is_me"])
    assert row["equity"] == pytest.approx(1040, abs=0.05)
    # Closed log is -5. The open partial (-3) is in the header and on the board.
    assert row["pnl"] == pytest.approx(-8, abs=0.05)


async def test_zero_liq_hides_slippage_preview(api, monkeypatch):
    client, _prices = api
    bot.users[UID] = _user()

    async def zero(contract, force=False, max_age=None):
        return {
            "symbol": "Z", "name": "Zero", "chain": "solana", "price": 1e-6,
            "mc": 1_000, "liq": 0, "pair_addr": "p", "dex": "pumpfun",
            "age_h": 0.2, "buy_pct": 50, "rug_risks": [],
        }

    async def no_coin(_mint):
        return None

    monkeypatch.setattr(bot, "get_token", zero)
    monkeypatch.setattr(bot, "_fetch_pumpfun_coin", no_coin)
    detail = await client.get(f"/api/tokens/{MINT}", headers=_headers())
    assert detail.status_code == 200
    assert detail.json()["slippage"] is None


async def test_feed_skips_pairless_pumpfun(api, monkeypatch):
    client, _prices = api
    bot.users[UID] = _user()
    pumps = [
        {"tokenAddress": f"PUMP{i:02d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "source": "pumpfun", "_pf_curve": 20}
        for i in range(30)
    ]
    pairs = [
        {"tokenAddress": f"PAIR{i:02d}yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy", "source": "dexscreener"}
        for i in range(5)
    ]

    async def scan():
        return pumps + pairs

    async def gt(contract, force=False, max_age=None):
        if str(contract).startswith("PAIR"):
            return {
                "symbol": "P", "name": "P", "chain": "solana", "price": 0.01,
                "mc": 20_000, "liq": 8_000, "pair_addr": "px", "dex": "raydium",
                "age_h": 1, "buy_pct": 55, "rug_risks": [],
            }
        return None

    monkeypatch.setattr(bot, "sniper_scan", scan)
    monkeypatch.setattr(bot, "get_token", gt)
    webapi._feed.clear()
    webapi._feed_refresh_task = None
    res = await client.get("/api/feed?refresh=true", headers=_headers())
    assert res.status_code == 200
    tokens = res.json()["tokens"]
    assert len(tokens) == 5
    assert all(t["contract"].startswith("PAIR") for t in tokens)
