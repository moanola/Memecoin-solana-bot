"""Short extra lines for the Telegram token card. Markdown-sensitive characters stripped."""
from __future__ import annotations

import re

_BAD = re.compile(r"[_*\[\]()`]")


def _s(value) -> str:
    return _BAD.sub("", str(value or ""))


def lines(info: dict) -> str:
    rows = []
    if info.get("pair_label"):
        kind = _s(info.get("quote_kind") or "")
        tail = " · indicative" if info.get("price_indicative") else ""
        rows.append(f"💱 Pair *{_s(info['pair_label'])}* ({kind}{tail})")
    if info.get("copycat_label"):
        rows.append("🪞 " + _s(info["copycat_label"]))
    if info.get("launch_group_found"):
        sold = info.get("launch_group_sold_pct")
        size = info.get("launch_group_size") or 0
        sure = "" if info.get("launch_group_confident") else "possible "
        sold_txt = f", {float(sold):.0f}% of that bag sold" if sold is not None else ""
        rows.append(f"📦 {sure}launch group {size} wallets{sold_txt}")
    if info.get("dev_cashout"):
        rows.append("💸 Dev cash-out: " + _s(info.get("dev_cashout_reason") or "funds moving to a hub"))
    if info.get("rug_memory_note"):
        rows.append("🧠 " + _s(info["rug_memory_note"]))
    if info.get("holders_per_hour") is not None:
        ret = info.get("holder_retention_pct")
        extra = f" · early hold {float(ret):.0f}%" if ret is not None else ""
        rows.append(f"👥 {float(info['holders_per_hour']):.0f} holders/hour{extra}")
    if info.get("kol_exit_note"):
        rows.append("👀 " + _s(info["kol_exit_note"]))
    if info.get("fee_sweep"):
        rows.append("🧹 Pool fees swept (protocol/creator fees dropped)")
    if not rows:
        return ""
    return "\n".join(rows) + "\n"
