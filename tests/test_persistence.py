import asyncio
import json
import pathlib

import persistence


def test_persistence_does_not_import_bot_module():
    src = pathlib.Path(persistence.__file__).read_text()
    assert "import sol_trading_bot" not in src


async def test_save_user_snapshots_before_thread_pool(monkeypatch):
    written = []

    def slow_write(uid, data_str):
        written.append((uid, data_str))

    monkeypatch.setattr(persistence, "_write_user", slow_write)
    ud = {"balance": 100.0, "holdings": {"A": {"amount": 1}}}
    persistence.save_user(1, ud)
    # Mutate the live dict immediately after scheduling, before the worker runs.
    ud["balance"] = 0.0
    ud["holdings"]["B"] = {"amount": 2}
    await asyncio.sleep(0.2)
    assert len(written) == 1
    snap = json.loads(written[0][1])
    assert snap["balance"] == 100.0
    assert set(snap["holdings"]) == {"A"}


def test_older_snapshot_never_overwrites_newer(monkeypatch):
    written = []
    monkeypatch.setattr(persistence, "_write_user", lambda uid, s: written.append(s))
    persistence._last_written.clear()
    persistence._ordered_write("user", 5, 20, "new")
    persistence._ordered_write("user", 5, 10, "old")   # finished late
    assert written == ["new"]


async def test_autosave_uses_registered_live_state(monkeypatch):
    saved_users, saved_logs = {}, {}
    monkeypatch.setattr(persistence, "_write_user", lambda uid, s: saved_users.__setitem__(uid, json.loads(s)))
    monkeypatch.setattr(persistence, "_write_trade_log", lambda uid, s: saved_logs.__setitem__(uid, json.loads(s)))
    users = {1: {"balance": 5.0}, 2: {"balance": 7.0}}
    trade_log = {1: [{"symbol": "X"}]}
    watchlist = {2: {"MintW": {"status": "watching"}}}
    persistence.register_state(users, trade_log, extras={"_persisted_watchlist": watchlist})
    users[3] = {"balance": 9.0}            # added after registration: must still be seen
    await persistence.autosave_job(None)
    await asyncio.sleep(0.2)
    assert set(saved_users) == {1, 2, 3}
    assert saved_users[2]["_persisted_watchlist"] == {"MintW": {"status": "watching"}}
    assert saved_logs == {1: [{"symbol": "X"}]}


def test_bot_registers_its_live_dicts():
    import sol_trading_bot as bot
    bot._register_persistence_state()
    assert persistence._state["users"] is bot.users
    assert persistence._state["trade_log"] is bot.trade_log
    assert persistence._state["extras"]["_persisted_watchlist"] is bot._apex_watchlist


def test_sqlite_roundtrip(tmp_path, monkeypatch):
    if not persistence._USE_SQLITE:
        return
    persistence.init_db()
    persistence._last_written.clear()
    persistence._ordered_write("user", 77, 1, persistence._dumps({"balance": 1.5}))
    users, logs = {}, {}
    persistence.load_all(users, logs)
    assert users[77]["balance"] == 1.5
