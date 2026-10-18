"""
slippage.py — simulated execution-cost model for paper trades.

Price impact uses a constant-product (x*y=k) estimate. DexScreener reports
total pool liquidity in USD (both sides), so the quote-side reserve is ~liq/2.
For a trade of size x (USD) against quote reserve R, the fraction of value
lost to price impact is x / (R + x) — the same for buys and sells.

The effective slippage is never below the old flat floor (0.5%), so small
trades in deep pools behave exactly as before.
"""
from config import SIM_DEX_FEE_PCT, SIM_GAS_USD, SIM_SLIPPAGE_PCT

MAX_SLIPPAGE_PCT = 0.99


def price_impact_pct(trade_usd: float, liq_usd: float | None) -> float:
    """Constant-product price impact as a fraction (0..1). 0 if liquidity unknown."""
    try:
        trade_usd = float(trade_usd or 0)
        liq_usd = float(liq_usd or 0)
    except (TypeError, ValueError):
        return 0.0
    if trade_usd <= 0 or liq_usd <= 0:
        return 0.0
    reserve = liq_usd / 2.0
    return trade_usd / (reserve + trade_usd)


def slippage_pct(trade_usd: float, liq_usd: float | None, floor: float = SIM_SLIPPAGE_PCT) -> float:
    """Effective slippage: max(floor, price impact), capped below 100%."""
    return min(MAX_SLIPPAGE_PCT, max(floor, price_impact_pct(trade_usd, liq_usd)))


def trade_cost_usd(trade_usd: float, liq_usd: float | None) -> float:
    """Total simulated cost of one trade: DEX fee + slippage + flat gas."""
    trade_usd = max(0.0, float(trade_usd or 0))
    return round(trade_usd * (SIM_DEX_FEE_PCT + slippage_pct(trade_usd, liq_usd)) + SIM_GAS_USD, 4)
