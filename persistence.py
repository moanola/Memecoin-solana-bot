"""
persistence.py — Supabase-backed persistence for AURACLE_XBOT
=============================================================
Uses Supabase free tier (no Railway Volume needed).

SETUP (one time):
  1. Go to https://supabase.com → create free account → New Project
  2. Project → SQL Editor → run this SQL:

       CREATE TABLE IF NOT EXISTS bot_users (
           uid     BIGINT PRIMARY KEY,
           data    TEXT    NOT NULL,
           updated BIGINT  NOT NULL
       );
       CREATE TABLE IF NOT EXISTS bot_trade_log (
           uid     BIGINT PRIMARY KEY,
           data    TEXT    NOT NULL,
           updated BIGINT  NOT NULL
       );

       ALTER TABLE bot_users     ENABLE ROW LEVEL SECURITY;
       ALTER TABLE bot_trade_log ENABLE ROW LEVEL SECURITY;
       -- No policies are created: anon/authenticated roles get no access.
       -- The service_role key bypasses RLS, so only this server can read/write.

  3. Project → Settings → API
     Copy "Project URL" and the "service_role" secret key.
     Keep it server-side only (Railway Variables) — never in the repo or a client.
  4. Railway → your service → Variables:
       SUPABASE_URL  = https://xxxx.supabase.co
       SUPABASE_KEY  = your-service-role-key

No Volume needed. See README.md for details.

Live state is registered by the bot via register_state() — this module never
imports sol_trading_bot (doing so from `python sol_trading_bot.py` created a
second, empty copy of the module, so autosave saw no users).
"""

import itertools
import json
import logging
import os
import threading
import time
from datetime import datetime, date

import httpx

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
_HEADERS = {
    "apikey":        _SUPABASE_KEY,
    "Authorization": f"Bearer {_SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

_USE_SQLITE = not (_SUPABASE_URL and _SUPABASE_KEY)

if _USE_SQLITE:
    import sqlite3
    _DATA_DIR = "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__))
    DB_PATH   = os.path.join(_DATA_DIR, "auracle_bot.db")
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        uid     INTEGER PRIMARY KEY,
        data    TEXT    NOT NULL,
        updated REAL    NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trade_log (
        uid     INTEGER NOT NULL,
        data    TEXT    NOT NULL,
        updated REAL    NOT NULL,
        PRIMARY KEY (uid)
    );
    CREATE TABLE IF NOT EXISTS kv (
        key     TEXT PRIMARY KEY,
        data    TEXT    NOT NULL,
        updated REAL    NOT NULL
    );
    """
else:
    DB_PATH = None


class _BotEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        if isinstance(obj, date):
            return {"__date__": obj.isoformat()}
        if isinstance(obj, set):
            return {"__set__": list(obj)}
        return super().default(obj)


def _bot_decoder(d: dict):
    if "__datetime__" in d:
        return datetime.fromisoformat(d["__datetime__"])
    if "__date__" in d:
        return date.fromisoformat(d["__date__"])
    if "__set__" in d:
        return set(d["__set__"])
    return d


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_BotEncoder)


def _loads(s: str):
    return json.loads(s, object_hook=_bot_decoder)


def _sb_upsert(table: str, uid: int, data_str: str):
    try:
        r = httpx.post(
            f"{_SUPABASE_URL}/rest/v1/{table}",
            headers={**_HEADERS, "Prefer": "resolution=merge-duplicates"},
            content=json.dumps({"uid": uid, "data": data_str, "updated": int(time.time())}),
            timeout=10,
        )
        if r.status_code not in (200, 201):
            logger.error("Supabase UPSERT %s/%s: %s %s", table, uid, r.status_code, r.text[:200])
    except Exception as e:
        logger.error("Supabase UPSERT %s/%s error: %s", table, uid, e)


def _sb_all(table: str) -> list:
    """
    Fetch ALL rows from a Supabase table using Range-based pagination.
    Supabase REST API returns max 1000 rows per request without a Range header.
    Without pagination, bots with >1000 users silently lose data on restart.
    """
    results = []
    page_size = 1000
    offset = 0
    while True:
        try:
            r = httpx.get(
                f"{_SUPABASE_URL}/rest/v1/{table}",
                headers={
                    **_HEADERS,
                    "Range-Unit": "items",
                    "Range": f"{offset}-{offset + page_size - 1}",
                    "Prefer": "count=none",
                },
                params={"select": "uid,data"},
                timeout=15,
            )
            if r.status_code not in (200, 206):
                logger.error("Supabase ALL %s (offset %d): %s %s", table, offset, r.status_code, r.text[:200])
                break
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < page_size:
                break   # last page
            offset += page_size
        except Exception as e:
            logger.error("Supabase ALL %s (offset %d): %s", table, offset, e)
            break
    return results


class _ClosingConn:
    """sqlite3's own context manager commits but never closes — this does both."""
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn.__enter__()

    def __exit__(self, *exc):
        try:
            return self.conn.__exit__(*exc)
        finally:
            self.conn.close()


def _sqlite_conn():
    return _ClosingConn(_sqlite_raw_conn())


def _sqlite_raw_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: allows concurrent reads + one writer without "database is locked"
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    if _USE_SQLITE:
        try:
            with _sqlite_conn() as conn:
                conn.executescript(_SCHEMA)
            logger.info("SQLite DB ready at %s", DB_PATH)
        except Exception as e:
            logger.error("SQLite init failed: %s", e)
            raise
    else:
        logger.info("Supabase persistence active: %s", _SUPABASE_URL)


def load_all(users: dict, trade_log: dict):
    init_db()
    loaded = 0
    if _USE_SQLITE:
        try:
            with _sqlite_conn() as conn:
                for row in conn.execute("SELECT uid, data FROM users"):
                    try:
                        users[row["uid"]] = _loads(row["data"])
                        loaded += 1
                    except Exception as e:
                        logger.error("Load user %s: %s", row["uid"], e)
                for row in conn.execute("SELECT uid, data FROM trade_log"):
                    try:
                        trade_log[row["uid"]] = _loads(row["data"])
                    except Exception as e:
                        logger.error("Load trade_log %s: %s", row["uid"], e)
        except Exception as e:
            logger.error("load_all sqlite: %s", e)
    else:
        for row in _sb_all("bot_users"):
            try:
                users[row["uid"]] = _loads(row["data"])
                loaded += 1
            except Exception as e:
                logger.error("Load user %s: %s", row["uid"], e)
        for row in _sb_all("bot_trade_log"):
            try:
                trade_log[row["uid"]] = _loads(row["data"])
            except Exception as e:
                logger.error("Load trade_log %s: %s", row["uid"], e)
    logger.info("Loaded %d users (%s)", loaded, "sqlite" if _USE_SQLITE else "supabase")


# ── Ordering guard ───────────────────────────────────────────────────────────
# Writes run on a thread pool, so two snapshots of the same uid could finish
# out of order. Each snapshot gets a sequence number; a write is skipped if a
# newer snapshot for that key has already been written.
_seq = itertools.count(1)
_last_written: dict = {}
_write_lock = threading.Lock()


def _write_user(uid: int, data_str: str) -> None:
    if _USE_SQLITE:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (uid, data, updated) VALUES (?, ?, ?)",
                (uid, data_str, time.time())
            )
    else:
        _sb_upsert("bot_users", uid, data_str)


def _write_trade_log(uid: int, data_str: str) -> None:
    if _USE_SQLITE:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trade_log (uid, data, updated) VALUES (?, ?, ?)",
                (uid, data_str, time.time())
            )
    else:
        _sb_upsert("bot_trade_log", uid, data_str)


def _ordered_write(kind: str, uid: int, seq: int, data_str: str) -> None:
    """Run in a worker thread. data_str is an immutable snapshot."""
    key = (kind, uid)
    try:
        with _write_lock:
            if _last_written.get(key, 0) > seq:
                return  # a newer snapshot already landed
        (_write_user if kind == "user" else _write_trade_log)(uid, data_str)
        with _write_lock:
            if _last_written.get(key, 0) < seq:
                _last_written[key] = seq
    except Exception as e:
        logger.error("save_%s(%s): %s", kind, uid, e)


def _schedule(kind: str, uid: int, obj) -> None:
    """
    Snapshot obj NOW (on the calling thread / event loop) by serialising it to
    a JSON string, then hand only that string to the thread pool. The live dict
    can keep changing without corrupting the write or raising
    "dictionary changed size during iteration" in the worker.
    """
    try:
        data_str = _dumps(obj)
    except Exception as e:
        logger.error("save_%s(%s) serialise failed: %s", kind, uid, e)
        return
    seq = next(_seq)
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        # No running loop — called from sync context (e.g. startup migration)
        _ordered_write(kind, uid, seq, data_str)
    else:
        # Fire-and-forget: errors are logged in _ordered_write; autosave_job
        # also re-persists every user periodically.
        loop.run_in_executor(None, _ordered_write, kind, uid, seq, data_str)


def save_user(uid: int, ud: dict):
    """Non-blocking save of a JSON snapshot of ud (taken synchronously)."""
    _schedule("user", uid, ud)


def save_trade_log(uid: int, log: list):
    """Non-blocking save of a JSON snapshot of log (taken synchronously)."""
    _schedule("trade_log", uid, log)


def save_all(uid: int, ud: dict, log: list):
    save_user(uid, ud)
    save_trade_log(uid, log)


_kv_savers: list = []
_kv_warned = False


def register_kv_saver(fn) -> None:
    """autosave_job calls each saver. Used for rug memory and the copycat index."""
    if fn not in _kv_savers:
        _kv_savers.append(fn)


def save_kv(key: str, obj) -> None:
    """Persist one JSON blob. SQLite table `kv`, or Supabase `bot_kv`."""
    global _kv_warned
    try:
        data_str = _dumps(obj)
    except Exception as exc:
        logger.error("save_kv(%s) serialise failed: %s", key, exc)
        return
    if _USE_SQLITE:
        try:
            init_db()
            with _sqlite_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kv (key, data, updated) VALUES (?, ?, ?)",
                    (key, data_str, time.time()),
                )
        except Exception as exc:
            logger.error("save_kv sqlite %s: %s", key, exc)
        return
    try:
        response = httpx.post(
            f"{_SUPABASE_URL}/rest/v1/bot_kv",
            headers={**_HEADERS, "Prefer": "resolution=merge-duplicates"},
            content=json.dumps({"key": key, "data": data_str, "updated": int(time.time())}),
            timeout=10,
        )
        if response.status_code not in (200, 201):
            if not _kv_warned:
                logger.error(
                    "Supabase bot_kv upsert failed (%s). Create the table from README. %s",
                    response.status_code, response.text[:160],
                )
                _kv_warned = True
    except Exception as exc:
        logger.error("save_kv supabase %s: %s", key, exc)


def load_kv(key: str):
    """Return the decoded blob, or None when the key or table is missing."""
    global _kv_warned
    if _USE_SQLITE:
        try:
            init_db()
            with _sqlite_conn() as conn:
                row = conn.execute("SELECT data FROM kv WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            return _loads(row["data"])
        except Exception as exc:
            logger.error("load_kv sqlite %s: %s", key, exc)
            return None
    try:
        response = httpx.get(
            f"{_SUPABASE_URL}/rest/v1/bot_kv",
            headers=_HEADERS,
            params={"select": "data", "key": f"eq.{key}"},
            timeout=10,
        )
        if response.status_code != 200:
            if not _kv_warned:
                logger.error("Supabase bot_kv read failed (%s)", response.status_code)
                _kv_warned = True
            return None
        rows = response.json()
        if not rows:
            return None
        return _loads(rows[0]["data"])
    except Exception as exc:
        logger.error("load_kv supabase %s: %s", key, exc)
        return None


# ── Live state registry ──────────────────────────────────────────────────────
# The bot registers references to its in-memory dicts at startup. autosave_job
# reads these instead of importing sol_trading_bot.
_state: dict = {
    "users": None,
    "trade_log": None,
    "extras": {},   # persisted key in ud -> runtime dict keyed by uid
}


def register_state(users: dict, trade_log: dict, extras: dict | None = None) -> None:
    """
    users / trade_log: the bot's live dicts (uid -> data).
    extras: {"_persisted_watchlist": _apex_watchlist, ...} — runtime dicts keyed
    by uid that are copied into ud[key] before each autosave.
    """
    _state["users"] = users
    _state["trade_log"] = trade_log
    _state["extras"] = dict(extras or {})


async def autosave_job(context):
    users = _state["users"]
    trade_log = _state["trade_log"]
    if users is None:
        logger.error("autosave_job: register_state() was never called — nothing saved")
        return
    saved = 0
    for uid, ud in list(users.items()):
        try:
            # ── Snapshot runtime dicts into ud so they survive restarts ───────
            for key, runtime in _state["extras"].items():
                if uid in runtime:
                    ud[key] = runtime[uid]
            save_user(uid, ud)
            if trade_log is not None and uid in trade_log:
                save_trade_log(uid, trade_log[uid])
            saved += 1
        except Exception as e:
            logger.error("autosave uid %s: %s", uid, e)
    for saver in list(_kv_savers):
        try:
            saver()
        except Exception as exc:
            logger.error("autosave kv saver: %s", exc)
    logger.debug("Autosave: %d users saved", saved)
