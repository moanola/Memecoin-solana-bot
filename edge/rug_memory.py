"""Remember creator and funder wallets and penalise the next launch they touch.

The store is a plain dict. persistence.save_kv / load_kv write it under the
key `rug_memory` (SQLite `kv`, or Supabase `bot_kv` when that table exists).
A rug is a fast drop, an LP pull, or a confident launch-group dump.
"""
from __future__ import annotations

import time

_KEY = "rug_memory"
_state = {
    "wallets": {},   # wallet -> {rugs: int, mints: [], last_reason, last_ts}
    "mints": {},     # mint -> {creator, funder, first_ts, rugged, reason}
    "snapshots": {}, # mint -> {price, liq, ts}
}


def reset() -> None:
    _state["wallets"].clear()
    _state["mints"].clear()
    _state["snapshots"].clear()


def snapshot() -> dict:
    return {
        "wallets": {k: dict(v) for k, v in _state["wallets"].items()},
        "mints": {k: dict(v) for k, v in _state["mints"].items()},
        "snapshots": {k: dict(v) for k, v in _state["snapshots"].items()},
    }


def load(blob: dict | None) -> None:
    reset()
    if not isinstance(blob, dict):
        return
    for key in ("wallets", "mints", "snapshots"):
        raw = blob.get(key) or {}
        if isinstance(raw, dict):
            _state[key].update({str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)})


def note_scan(mint: str, creator: str | None, funder: str | None, ts: float | None = None) -> None:
    if not mint:
        return
    row = _state["mints"].setdefault(mint, {
        "creator": None, "funder": None, "first_ts": ts or time.time(), "rugged": False, "reason": "",
    })
    if creator:
        row["creator"] = creator
        _touch(creator, mint)
    if funder:
        row["funder"] = funder
        _touch(funder, mint)


def _touch(wallet: str, mint: str) -> None:
    entry = _state["wallets"].setdefault(wallet, {"rugs": 0, "mints": [], "last_reason": "", "last_ts": 0})
    if mint not in entry["mints"]:
        entry["mints"].append(mint)
        entry["mints"] = entry["mints"][-50:]


def rug_reason(prev: dict | None, now: dict, drop_pct: float = 90.0, window_min: float = 30.0) -> str | None:
    if not prev or not now:
        return None
    try:
        old_price = float(prev.get("price") or 0)
        new_price = float(now.get("price") or 0)
        dt_min = (float(now.get("ts") or 0) - float(prev.get("ts") or 0)) / 60.0
    except (TypeError, ValueError):
        return None
    if old_price > 0 and new_price >= 0 and 0 <= dt_min <= window_min:
        change = (new_price - old_price) / old_price * 100.0
        if change <= -abs(drop_pct):
            return "fast_drop"
    try:
        old_liq = float(prev.get("liq") or 0)
        new_liq = float(now.get("liq") or 0)
    except (TypeError, ValueError):
        old_liq = new_liq = 0.0
    if old_liq >= 1_000 and new_liq < old_liq * 0.2:
        return "lp_pull"
    if now.get("launch_group_confident") and float(now.get("launch_group_sold_pct") or 0) >= 70:
        return "group_dump"
    return None


def observe(mint: str, info: dict, drop_pct: float = 90.0, window_min: float = 30.0,
            ts: float | None = None) -> str | None:
    """Update the price snapshot and mark a rug when the rule matches."""
    now_ts = ts if ts is not None else time.time()
    current = {
        "price": info.get("price") or 0,
        "liq": info.get("liq") or 0,
        "ts": now_ts,
        "launch_group_sold_pct": info.get("launch_group_sold_pct") or 0,
        "launch_group_confident": bool(info.get("launch_group_confident")),
    }
    prev = _state["snapshots"].get(mint)
    reason = rug_reason(prev, current, drop_pct, window_min)
    window_s = float(window_min) * 60.0
    if prev is None:
        _state["snapshots"][mint] = current
    else:
        try:
            age = now_ts - float(prev.get("ts") or now_ts)
            prev_price = float(prev.get("price") or 0)
            new_price = float(current.get("price") or 0)
        except (TypeError, ValueError):
            age, prev_price, new_price = window_s + 1, 0.0, 0.0
        # Keep the anchor inside the window so a grind is still measured from
        # the earlier price. A new high, or an expired anchor, starts a new one.
        if age > window_s or (new_price > prev_price > 0):
            _state["snapshots"][mint] = current
    if reason:
        mark_rug(mint, reason, now_ts)
        _state["snapshots"][mint] = current
    return reason


def mark_rug(mint: str, reason: str, ts: float | None = None) -> None:
    row = _state["mints"].setdefault(mint, {
        "creator": None, "funder": None, "first_ts": ts or time.time(), "rugged": False, "reason": "",
    })
    row["rugged"] = True
    row["reason"] = reason
    when = ts or time.time()
    for wallet in (row.get("creator"), row.get("funder")):
        if not wallet:
            continue
        entry = _state["wallets"].setdefault(wallet, {"rugs": 0, "mints": [], "last_reason": "", "last_ts": 0})
        if mint not in entry["mints"]:
            entry["mints"].append(mint)
        # Count this mint once.
        already = entry.get("_rugged_mints") or []
        if mint not in already:
            already.append(mint)
            entry["_rugged_mints"] = already[-50:]
            entry["rugs"] = int(entry.get("rugs") or 0) + 1
        entry["last_reason"] = reason
        entry["last_ts"] = when


def lookup(creator: str | None, funder: str | None) -> dict:
    hits = []
    rugs = 0
    for wallet, role in ((creator, "creator"), (funder, "funder")):
        entry = _state["wallets"].get(wallet or "")
        if entry and int(entry.get("rugs") or 0) > 0:
            hits.append({"wallet": wallet, "role": role, "rugs": entry["rugs"], "reason": entry.get("last_reason") or ""})
            rugs += int(entry["rugs"])
    penalty = 0
    if any(h["role"] == "creator" for h in hits):
        penalty -= 15
    elif hits:
        penalty -= 8
    if rugs >= 3:
        penalty -= 5
    note = ""
    if hits:
        note = "Prior rug wallet: " + ", ".join(f"{h['role']} {h['rugs']} rug(s)" for h in hits)
    return {"hits": hits, "penalty": penalty, "note": note}


def apply_to_info(info: dict, mint: str) -> dict:
    creator = info.get("creator") or info.get("dev_wallet")
    funder = info.get("creator_funder") or info.get("funder")
    note_scan(mint, creator, funder)
    result = lookup(creator, funder)
    info["rug_memory_penalty"] = result["penalty"]
    info["rug_memory_note"] = result["note"]
    info["rug_memory_hits"] = len(result["hits"])
    return result
