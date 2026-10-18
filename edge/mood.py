"""Market mood from MemeFees, with a DexScreener/GeckoTerminal fallback.

Primary (verified response shape, October 2026, no API key):
- https://memefees.com/api/v1/pad-daily?pad=pump-fun&days=14
  columns include day, fees_usd, volume_usd. Fees and volume are DefiLlama's,
  labelled source=defillama. MemeFees asks for attribution and a link.
- https://memefees.com/api/v1/market-share
  one row per pad; pump.fun share_7d_pct is the fee share.

If those payloads are missing, a GeckoTerminal pumpswap pool page can supply
a volume sum only. Share is then unknown and the gauge says so. The gauge
never places a trade.
"""
from __future__ import annotations

import time

MEMEFEES_DAILY = "https://memefees.com/api/v1/pad-daily?pad=pump-fun&days=14"
MEMEFEES_SHARE = "https://memefees.com/api/v1/market-share"
GECKO_POOLS = "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pumpswap/pools?page=1"
ATTRIBUTION = "MemeFees (memefees.com). Fees and volume: DefiLlama."

_cache = {"ts": 0.0, "mood": None}


def reset_cache() -> None:
    _cache["ts"] = 0.0
    _cache["mood"] = None


def _num(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows
    columns = payload.get("columns") or []
    if isinstance(rows, list) and columns and rows and isinstance(rows[0], list):
        return [dict(zip(columns, row)) for row in rows]
    return []


def parse_pad_daily(payload: dict) -> list[dict]:
    out = []
    for row in _rows(payload):
        day = row.get("day") or row.get("date")
        fees = _num(row.get("fees_usd"))
        volume = _num(row.get("volume_usd"))
        if not day:
            continue
        out.append({
            "day": str(day),
            "fees_usd": fees,
            "volume_usd": volume,
            "launches": _num(row.get("launches")),
            "source": row.get("source") or "",
        })
    out.sort(key=lambda r: r["day"])
    return out


def parse_share(payload: dict, pad: str = "pump-fun") -> float | None:
    for row in _rows(payload):
        if str(row.get("pad") or "") == pad:
            return _num(row.get("share_7d_pct"))
    return None


def parse_gecko_pools(payload: dict) -> float | None:
    data = []
    if isinstance(payload, dict):
        data = payload.get("data") or []
    total = 0.0
    seen = False
    for pool in data:
        attrs = (pool or {}).get("attributes") or {}
        vol = attrs.get("volume_usd") or {}
        if isinstance(vol, dict):
            number = _num(vol.get("h24"))
        else:
            number = _num(vol)
        if number is not None:
            total += number
            seen = True
    return total if seen else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def gauge_from_series(days: list[dict], share_7d: float | None = None,
                      source: str = "memefees") -> dict:
    """Map the last complete day against the prior median.

    Cold markets shrink APEX size and lower the heat ceiling. Hot markets do
    the opposite, with the heat ceiling capped so it cannot exceed 95%.
    """
    usable = [d for d in days if d.get("fees_usd") is not None]
    latest = usable[-1] if usable else None
    prior = usable[:-1] if len(usable) > 1 else []
    fees_med = _median([d["fees_usd"] for d in prior if d.get("fees_usd") is not None])
    vol_med = _median([d["volume_usd"] for d in prior if d.get("volume_usd") is not None])
    score = 50.0
    fees = latest.get("fees_usd") if latest else None
    volume = latest.get("volume_usd") if latest else None
    if fees is not None and fees_med:
        ratio = fees / fees_med
        if ratio >= 1.3:
            score += 20
        elif ratio >= 1.1:
            score += 10
        elif ratio <= 0.7:
            score -= 20
        elif ratio <= 0.85:
            score -= 10
    if volume is not None and vol_med:
        vratio = volume / vol_med
        if vratio >= 1.25:
            score += 8
        elif vratio <= 0.75:
            score -= 8
    if share_7d is not None:
        if share_7d >= 45:
            score += 10
        elif share_7d >= 30:
            score += 4
        elif share_7d < 20:
            score -= 10
    score = max(0.0, min(100.0, score))
    if score >= 70:
        label, size_mult, heat_scale = "HOT", 1.15, 1.08
    elif score >= 55:
        label, size_mult, heat_scale = "WARM", 1.05, 1.0
    elif score >= 40:
        label, size_mult, heat_scale = "NEUTRAL", 1.0, 1.0
    else:
        label, size_mult, heat_scale = "COLD", 0.70, 0.80
    return {
        "label": label,
        "score": round(score, 1),
        "size_mult": size_mult,
        "heat_scale": heat_scale,
        "fees_usd": fees,
        "volume_usd": volume,
        "share_7d_pct": share_7d,
        "day": latest.get("day") if latest else None,
        "source": source,
        "attribution": ATTRIBUTION if source == "memefees" else source,
        "paper": True,
    }


def gauge_from_gecko_volume(volume_h24: float | None) -> dict:
    """Fallback when MemeFees is unreachable. Share is unknown."""
    score = 50.0
    if volume_h24 is None:
        label, size_mult, heat_scale = "UNKNOWN", 1.0, 1.0
        score = 50.0
    elif volume_h24 >= 50_000_000:
        label, size_mult, heat_scale, score = "WARM", 1.05, 1.0, 60.0
    elif volume_h24 <= 5_000_000:
        label, size_mult, heat_scale, score = "COLD", 0.70, 0.80, 30.0
    else:
        label, size_mult, heat_scale, score = "NEUTRAL", 1.0, 1.0, 50.0
    return {
        "label": label,
        "score": score,
        "size_mult": size_mult,
        "heat_scale": heat_scale,
        "fees_usd": None,
        "volume_usd": volume_h24,
        "share_7d_pct": None,
        "day": None,
        "source": "geckoterminal",
        "attribution": "GeckoTerminal pumpswap pool volume (fallback). Fee share unavailable.",
        "paper": True,
    }


def remember(mood: dict) -> dict:
    _cache["ts"] = time.time()
    _cache["mood"] = dict(mood)
    return _cache["mood"]


def cached(max_age_s: float = 900) -> dict | None:
    mood = _cache.get("mood")
    if not mood:
        return None
    if time.time() - float(_cache.get("ts") or 0) > max_age_s:
        return mood  # stale is still better than nothing; callers may refresh
    return mood


def size_multiplier() -> float:
    from edge.flags import market_mood
    if not market_mood():
        return 1.0
    mood = _cache.get("mood") or {}
    try:
        return float(mood.get("size_mult") or 1.0)
    except (TypeError, ValueError):
        return 1.0


def heat_scale() -> float:
    from edge.flags import market_mood
    if not market_mood():
        return 1.0
    mood = _cache.get("mood") or {}
    try:
        return float(mood.get("heat_scale") or 1.0)
    except (TypeError, ValueError):
        return 1.0


async def refresh(max_age_s: float = 900) -> dict:
    """Fetch mood. Uses the shared HTTP client. Failures keep the last gauge."""
    from edge.flags import market_mood
    if not market_mood():
        return remember({
            "label": "OFF", "score": 50, "size_mult": 1.0, "heat_scale": 1.0,
            "fees_usd": None, "volume_usd": None, "share_7d_pct": None, "day": None,
            "source": "disabled", "attribution": "", "paper": True,
        })
    fresh = _cache.get("mood")
    if fresh and time.time() - float(_cache.get("ts") or 0) < max_age_s and fresh.get("source") != "disabled":
        return fresh
    try:
        from api_clients import get_http
        client = await get_http()
        daily = await client.get(MEMEFEES_DAILY, timeout=8)
        share = await client.get(MEMEFEES_SHARE, timeout=8)
        if daily.status_code == 200 and share.status_code == 200:
            days = parse_pad_daily(daily.json())
            if days:
                return remember(gauge_from_series(days, parse_share(share.json())))
    except Exception:
        pass
    try:
        from api_clients import get_http
        client = await get_http()
        gecko = await client.get(GECKO_POOLS, timeout=8, headers={"Accept": "application/json"})
        if gecko.status_code == 200:
            return remember(gauge_from_gecko_volume(parse_gecko_pools(gecko.json())))
    except Exception:
        pass
    if _cache.get("mood"):
        return _cache["mood"]
    return remember(gauge_from_gecko_volume(None))
