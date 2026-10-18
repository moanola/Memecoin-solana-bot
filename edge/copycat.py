"""Group lookalike launches and point alerts at the original.

Similarity is the ticker (alnum, case-insensitive), a token-set name ratio,
or an image identity. Image identity is a caller-supplied hash. `ahash_bits`
is an average hash over an 8x8 luminance grid when pixels are already decoded.
Downloading image bytes is intentionally not done here.

The original is the earliest mint, then the one with clean funding, then the
one with higher holder growth.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_index: dict[str, dict] = {}


def reset_index() -> None:
    _index.clear()


def snapshot_index() -> dict:
    return {k: dict(v) for k, v in _index.items()}


def load_index(rows: dict | None) -> None:
    _index.clear()
    for key, row in (rows or {}).items():
        if isinstance(row, dict) and row.get("mint"):
            _index[key] = dict(row)


def _ticker(symbol: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (symbol or "").lower())


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()


def name_similar(a: str, b: str) -> float:
    left, right = _name_key(a), _name_key(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def ahash_bits(grid: list[int], size: int = 8) -> str:
    """Average hash. `grid` is size*size luminance samples, 0-255."""
    if len(grid) < size * size:
        raise ValueError("grid shorter than size*size")
    sample = [int(v) for v in grid[: size * size]]
    avg = sum(sample) / len(sample)
    bits = "".join("1" if v >= avg else "0" for v in sample)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hash_distance(a: str | None, b: str | None) -> int | None:
    if not a or not b or len(a) != len(b):
        return None
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except ValueError:
        return None


def same_image(a: dict, b: dict) -> bool:
    if a.get("image") and b.get("image") and a["image"] == b["image"]:
        return True
    dist = hash_distance(a.get("image_hash"), b.get("image_hash"))
    return dist is not None and dist <= 8


def _similar(a: dict, b: dict) -> bool:
    if a.get("mint") == b.get("mint"):
        return True
    ta, tb = _ticker(a.get("symbol") or ""), _ticker(b.get("symbol") or "")
    if ta and ta == tb:
        return True
    if name_similar(a.get("name") or "", b.get("name") or "") >= 0.84:
        return True
    if same_image(a, b) and (name_similar(a.get("name") or "", b.get("name") or "") >= 0.55 or ta[:3] == tb[:3]):
        return True
    return False


def register_launch(info: dict, mint: str) -> None:
    if not mint:
        return
    if len(_index) > 400 and mint not in _index:
        oldest = sorted(_index.values(), key=lambda row: float(row.get("created_at") or 0))[:40]
        for row in oldest:
            _index.pop(row.get("mint"), None)
    _index[mint] = {
        "mint": mint,
        "symbol": info.get("symbol") or "",
        "name": info.get("name") or "",
        "image": info.get("token_image") or info.get("image") or "",
        "image_hash": info.get("image_hash") or "",
        "created_at": info.get("created_at") or info.get("pair_created_at") or 0,
        "clean_funding": bool(info.get("clean_funding", not info.get("dev_cashout") and not info.get("rug_memory_penalty"))),
        "holder_growth": float(info.get("holders_per_hour") or info.get("holder_growth") or 0),
    }


def pick_original(members: list[dict]) -> dict:
    def key(row: dict):
        created = float(row.get("created_at") or 0) or 10**13
        dirty = 0 if row.get("clean_funding", True) else 1
        growth = -float(row.get("holder_growth") or 0)
        return (created, dirty, growth, row.get("mint") or "")

    return min(members, key=key)


def resolve(info: dict, mint: str) -> dict:
    """Label `mint` against the in-memory index. Registers it first."""
    register_launch(info, mint)
    me = _index.get(mint)
    if not me:
        return {"role": "unknown", "original": None, "copies": []}
    members = [row for row in _index.values() if _similar(me, row)]
    # Keep the group tight: require similarity to the seed, already done.
    if len(members) <= 1:
        return {
            "role": "original",
            "original": mint,
            "original_symbol": me.get("symbol"),
            "copies": [],
            "copy_count": 0,
            "block_alert": False,
        }
    original = pick_original(members)
    copies = [row["mint"] for row in members if row["mint"] != original["mint"]]
    role = "original" if mint == original["mint"] else "copy"
    return {
        "role": role,
        "original": original["mint"],
        "original_symbol": original.get("symbol") or "",
        "copies": copies,
        "copy_count": len(copies),
        "block_alert": role == "copy",
        "label": "OG" if role == "original" else f"COPY of ${original.get('symbol') or '?'}",
    }


def apply_to_info(info: dict, mint: str) -> dict:
    result = resolve(info, mint)
    info["copycat_role"] = result["role"]
    info["copycat_original"] = result.get("original")
    info["copycat_original_symbol"] = result.get("original_symbol")
    info["copycat_copy_count"] = result.get("copy_count") or 0
    info["copycat_label"] = result.get("label") or ""
    info["copycat_block_alert"] = bool(result.get("block_alert"))
    return result
