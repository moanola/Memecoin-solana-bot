"""Point and flag adjustments. No-ops when the feature flag is off or the data is absent."""
from __future__ import annotations

from edge import flags
from edge.holders import holders_per_hour, score_delta


def holder_fields(info: dict) -> dict:
    per_hour = info.get("holders_per_hour")
    if per_hour is None:
        per_hour = holders_per_hour(
            info.get("holder_count") if info.get("holder_count") is not None else info.get("maker_count"),
            info.get("age_h"),
        )
    retention = info.get("holder_retention_pct")
    return {"holders_per_hour": per_hour, "holder_retention_pct": retention}


def apply_local(info: dict, mint: str) -> None:
    """Sync labels that do not need a network call. Safe to run on every scan."""
    if not info or not mint:
        return
    if flags.rug_memory():
        from edge.rug_memory import apply_to_info, observe
        apply_to_info(info, mint)
        observe(mint, info, flags.rug_drop_pct(), flags.rug_window_min())
    if flags.holder_velocity():
        fields = holder_fields(info)
        if fields["holders_per_hour"] is not None:
            info["holders_per_hour"] = fields["holders_per_hour"]
    if flags.copycat():
        from edge.copycat import apply_to_info as label_copy
        label_copy(info, mint)


def adjust(info: dict, score: int, strengths: list, warnings: list, flag_list: list) -> tuple:
    """Apply edge penalties and the holder-velocity delta. Returns the same lists."""
    score = int(score)
    if flags.rug_memory():
        penalty = int(info.get("rug_memory_penalty") or 0)
        if penalty:
            score += penalty
            note = info.get("rug_memory_note") or "Linked to a wallet from a rugged launch"
            warnings.append(note)
    if flags.dev_cashout() and info.get("dev_cashout"):
        score -= 18
        flag_list.append("🚨 Dev cash-out — " + (info.get("dev_cashout_reason") or "funds consolidating"))
    if flags.launch_group() and info.get("launch_group_found"):
        sold = info.get("launch_group_sold_pct")
        size = int(info.get("launch_group_size") or 0)
        if sold is not None and float(sold) >= 25:
            warnings.append(f"Launch group sold {float(sold):.0f}% of its bag ({size} wallets)")
        elif size >= 3:
            label = "possible " if not info.get("launch_group_confident") else ""
            warnings.append(f"{label}launch cluster of {size} wallets")
    if flags.copycat() and info.get("copycat_role") == "copy":
        symbol = info.get("copycat_original_symbol") or "original"
        flag_list.append(f"🚨 Copy of ${symbol}")
        score -= 15
    elif flags.copycat() and info.get("copycat_role") == "original" and int(info.get("copycat_copy_count") or 0) > 0:
        strengths.append(f"Original — {int(info['copycat_copy_count'])} copies launching")
    if flags.holder_velocity():
        fields = holder_fields(info)
        if fields["holders_per_hour"] is not None:
            info["holders_per_hour"] = fields["holders_per_hour"]
        delta, notes = score_delta(fields["holders_per_hour"], fields["holder_retention_pct"])
        score += delta
        for note in notes:
            if delta >= 0 and "slow" not in note and "only" not in note:
                strengths.append(note)
            elif "slow" in note or "only" in note:
                warnings.append(note)
            elif delta > 0:
                strengths.append(note)
    if flags.kol_exits() and info.get("kol_exit_note"):
        warnings.append(str(info["kol_exit_note"]))
    score = max(0, min(100, score))
    return score, strengths, warnings, flag_list
