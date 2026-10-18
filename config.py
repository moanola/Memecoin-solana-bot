"""
config.py — environment-driven settings for APEX SNIPER BOT.

All secrets come from environment variables (Railway → Variables).
Nothing secret is hardcoded here.
"""
import os
from datetime import timezone, tzinfo

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var not set. Add it in Railway → Variables.")

# ── ADMIN ACCESS ──────────────────────────────────────────────────────────────
# Set ADMIN_IDS in Railway env vars as comma-separated Telegram user IDs.
# Example: ADMIN_IDS=123456789,987654321
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: set = {int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()}


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


# ── ACCESS CONTROL ────────────────────────────────────────────────────────────
# When ACCESS_CONTROL_ENABLED=true, new users must be approved by admin.
# Set ACCESS_ADMIN_USERNAME in Railway env vars (without @), e.g. auracle_x
# Admins (ADMIN_IDS) are always approved automatically.
ACCESS_ADMIN_USERNAME   = os.getenv("ACCESS_ADMIN_USERNAME", "auracle_x")
ACCESS_CONTROL_ENABLED  = os.getenv("ACCESS_CONTROL_ENABLED", "true").lower() == "true"

# ── LLM (optional) ────────────────────────────────────────────────────────────
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# ── Scheduling timezone for daily/weekly/monthly jobs ─────────────────────────
# IANA name, e.g. "UTC", "Europe/London", "America/New_York". Default UTC.
BOT_TIMEZONE_NAME = os.getenv("BOT_TIMEZONE", "UTC").strip() or "UTC"


def _load_tz(name: str) -> tzinfo:
    if name.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Unknown BOT_TIMEZONE %r — falling back to UTC", name)
        return timezone.utc


BOT_TZ: tzinfo = _load_tz(BOT_TIMEZONE_NAME)

# ── SIMULATED TRADING COSTS — mirrors real Solana DEX costs for accurate P&L ──
# Every buy and sell deducts these costs so paper trading results match live.
#
#   Gas (network fee)   : ~$0.002  flat per tx
#   DEX fee (PumpSwap)  : 0.25%    of trade size (LP fee)
#   Slippage            : max(0.5% floor, constant-product price impact of the
#                          trade vs pool liquidity) — see slippage.py
#
# Change SIM_FEES_ENABLED = False to disable for comparison.
SIM_FEES_ENABLED    = True
SIM_GAS_USD         = 0.002    # flat SOL network fee per transaction
SIM_DEX_FEE_PCT     = 0.0025   # 0.25% — PumpSwap/Raydium LP fee
SIM_SLIPPAGE_PCT    = 0.005    # 0.50% — slippage floor on micro-cap Solana tokens
SIM_TOTAL_PCT       = SIM_DEX_FEE_PCT + SIM_SLIPPAGE_PCT  # 0.75% per trade (minimum)

# Refresh the token price at fill time if the cached quote is older than this.
FILL_MAX_PRICE_AGE_S = float(os.getenv("FILL_MAX_PRICE_AGE_S", "5"))
