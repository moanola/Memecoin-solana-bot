"""Environment flags for the edge features. Read on each call so tests can override."""
import os


def _on(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def custom_pairs() -> bool:
    return _on("EDGE_CUSTOM_PAIRS")


def kol_exits() -> bool:
    return _on("EDGE_KOL_EXITS")


def launch_group() -> bool:
    return _on("EDGE_LAUNCH_GROUP")


def launch_group_exit_pct() -> float:
    return _float("EDGE_LAUNCH_GROUP_EXIT_PCT", 40.0)


def dev_cashout() -> bool:
    return _on("EDGE_DEV_CASHOUT")


def dev_cashout_apex_exit() -> bool:
    return _on("EDGE_DEV_CASHOUT_APEX_EXIT")


def rug_memory() -> bool:
    return _on("EDGE_RUG_MEMORY")


def rug_drop_pct() -> float:
    return _float("EDGE_RUG_DROP_PCT", 90.0)


def rug_window_min() -> float:
    return _float("EDGE_RUG_WINDOW_MIN", 30.0)


def copycat() -> bool:
    return _on("EDGE_COPYCAT")


def holder_velocity() -> bool:
    return _on("EDGE_HOLDER_VELOCITY")


def holder_reentry_min_retention() -> float:
    return _float("EDGE_HOLDER_REENTRY_MIN_RETENTION", 25.0)


def market_mood() -> bool:
    return _on("EDGE_MARKET_MOOD")


def exit_plan() -> bool:
    return _on("EDGE_EXIT_PLAN")


def exit_default_preset() -> str:
    name = os.getenv("EDGE_EXIT_DEFAULT_PRESET", "standard").strip().lower()
    return name or "standard"


def helius_per_min() -> int:
    return max(1, _int("EDGE_HELIUS_PER_MIN", 8))
