"""
api_clients.py — shared HTTP client and external API helpers
(SOL/USD price via DexScreener/CoinGecko, Helius enrichment).

Extracted verbatim from sol_trading_bot.py; sol_trading_bot re-imports these
names so existing call sites are unchanged.
"""
import asyncio as _asyncio
import logging
import time as _time

import httpx

logger = logging.getLogger(__name__)

_http: httpx.AsyncClient | None = None

async def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8, limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))
    return _http


async def close_http() -> None:
    """Close the shared client (called from Application.post_shutdown)."""
    global _http
    if _http is not None and not _http.is_closed:
        await _http.aclose()
        logger.info("HTTP client closed cleanly.")
    _http = None


_sol_price_cache: dict = {"price": 0.0, "ts": 0.0}  # last-known SOL/USD (0.0 = never fetched), 60s TTL


async def get_sol_price() -> float:
    """Get current SOL/USD price. Cached for 60s.
    Source priority:
      1. DexScreener  — SOL/USDC pair (most accurate for trading)
      2. CoinGecko    — free public API, no key required
      3. Last known   — stale but better than a hardcoded guess
    Returns 0.0 only if no source has ever succeeded since startup; callers
    must treat <= 0 as "unknown".
    """
    now = _time.time()
    if now - _sol_price_cache["ts"] < 60:
        return _sol_price_cache["price"]

    client = await get_http()

    # ── Source 1: DexScreener ─────────────────────────────────────────────────
    try:
        r = await client.get(
            "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
            timeout=5,
        )
        if r.status_code == 200:
            pairs = r.json().get("pairs", [])
            sol_pairs = [p for p in pairs if p.get("quoteToken", {}).get("symbol") == "USDC"]
            if sol_pairs:
                price = float(sol_pairs[0].get("priceUsd", 0) or 0)
                if price > 0:
                    _sol_price_cache["price"] = price
                    _sol_price_cache["ts"]    = now
                    logger.debug("SOL price $%.2f (DexScreener)", price)
                    return price
    except Exception as e:
        logger.warning("SOL price DexScreener failed: %s", e)

    # ── Source 2: CoinGecko (free tier, no API key needed) ───────────────────
    try:
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "solana", "vs_currencies": "usd"},
            headers={"Accept": "application/json"},
            timeout=5,
        )
        if r.status_code == 200:
            price = float(r.json().get("solana", {}).get("usd", 0) or 0)
            if price > 0:
                _sol_price_cache["price"] = price
                _sol_price_cache["ts"]    = now
                logger.info("SOL price $%.2f (CoinGecko fallback)", price)
                return price
    except Exception as e:
        logger.warning("SOL price CoinGecko failed: %s", e)

    # ── Source 3: Last known cache (stale but non-zero) ───────────────────────
    if _sol_price_cache["price"] > 0:
        logger.warning("SOL price: all sources failed — using last known $%.2f", _sol_price_cache["price"])
    else:
        logger.warning("SOL price: all sources failed and no last-known price yet")
    return _sol_price_cache["price"]



async def get_helius_maker_pct(contract: str, api_key: str) -> dict:
    """
    Optional Helius enrichment — fetches last 100 txns and calculates:
      - maker_pct:    % of unique wallets that are net buyers
      - maker_count:  number of unique buyer wallets
      - top3_vol_pct: % of volume from top 3 wallets (wash trade signal)
    Returns empty dict gracefully if key missing / rate limited.
    """
    if not api_key:
        return {}
    try:
        client = await get_http()
        url = f"https://api.helius.xyz/v0/addresses/{contract}/transactions"
        params = {"api-key": api_key, "limit": "100", "type": "SWAP"}
        r = await client.get(url, params=params, timeout=8)
        if r.status_code == 429:
            logger.info("Helius rate limit hit — skipping maker enrichment")
            return {}
        if r.status_code != 200:
            return {}
        txns = r.json()
        if not isinstance(txns, list) or not txns:
            return {}

        buyer_vols:  dict = {}   # wallet → volume bought
        seller_vols: dict = {}   # wallet → volume sold

        for tx in txns:
            try:
                fee_payer = tx.get("feePayer", "")
                native_transfers = tx.get("nativeTransfers", []) or []
                token_transfers  = tx.get("tokenTransfers",  []) or []
                # Determine if this is a buy (feePayer received token) or sell
                is_buy = any(
                    t.get("toUserAccount") == fee_payer
                    for t in token_transfers
                    if t.get("mint") == contract
                )
                # Approximate volume from native SOL moved
                sol_moved = sum(
                    abs(t.get("amount", 0))
                    for t in native_transfers
                    if t.get("fromUserAccount") == fee_payer or t.get("toUserAccount") == fee_payer
                ) / 1e9  # lamports → SOL
                if is_buy:
                    buyer_vols[fee_payer]  = buyer_vols.get(fee_payer,  0) + sol_moved
                else:
                    seller_vols[fee_payer] = seller_vols.get(fee_payer, 0) + sol_moved
            except Exception:
                continue

        total_wallets = len(set(buyer_vols.keys()) | set(seller_vols.keys()))
        if total_wallets == 0:
            return {}

        maker_pct   = round(len(buyer_vols) / total_wallets * 100) if total_wallets > 0 else 50
        maker_count = len(buyer_vols)

        # Top 3 wallet concentration — sum buy+sell vol per wallet (don't overwrite)
        all_vols: dict = {}
        for _w, _v in buyer_vols.items():
            all_vols[_w] = all_vols.get(_w, 0) + _v
        for _w, _v in seller_vols.items():
            all_vols[_w] = all_vols.get(_w, 0) + _v
        total_vol = sum(all_vols.values()) or 1
        top3_vol  = sum(sorted(all_vols.values(), reverse=True)[:3])
        top3_vol_pct = round(top3_vol / total_vol * 100)

        return {
            "maker_pct":    maker_pct,
            "maker_count":  maker_count,
            "top3_vol_pct": top3_vol_pct,
        }
    except Exception as e:
        logger.debug(f"Helius maker enrichment failed: {e}")
        return {}

async def get_helius_pool_price(contract: str, pair_addr: str, api_key: str) -> dict:
    """
    Query Solana pool reserves directly via Helius RPC.
    Returns {price, liq, liq_drop_pct} in near-real-time (~400ms block time).
    Falls back gracefully if pool layout unreadable.
    """
    if not api_key or not pair_addr:
        return {}
    try:
        client   = await get_http()
        rpc_url  = f"https://mainnet.helius-rpc.com/?api-key={api_key}"

        # Step 1: get pool account info to find vault addresses
        pool_resp = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
            "params": [pair_addr, {"encoding": "jsonParsed", "commitment": "confirmed"}]
        }, timeout=5)
        if pool_resp.status_code != 200:
            return {}

        pool_data = pool_resp.json().get("result", {}).get("value")
        if not pool_data:
            return {}

        # Step 2: get token accounts for this pool
        # Use getTokenAccountsByOwner to find what the pool holds
        ta_resp = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 2,
            "method": "getTokenAccountsByOwner",
            "params": [pair_addr,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed", "commitment": "confirmed"}
            ]
        }, timeout=5)
        if ta_resp.status_code != 200:
            return {}

        accounts = ta_resp.json().get("result", {}).get("value", [])
        if not accounts:
            return {}

        # Parse token balances — find base (token) and quote (SOL wrapped / USDC)
        WSOL  = "So11111111111111111111111111111111111111112"
        USDC  = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        USDT  = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

        base_amt  = None
        quote_usd = None

        for acct in accounts:
            info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint    = info.get("mint", "")
            balance = float(info.get("tokenAmount", {}).get("uiAmount") or 0)

            if mint == contract:
                base_amt = balance
            elif mint == WSOL:
                # Use live SOL/USD price from cache (refreshed every 60s)
                sol_price = _sol_price_cache.get("price", 0.0)
                if sol_price <= 0:
                    continue   # SOL/USD unknown — caller falls back to DexScreener
                quote_usd = balance * sol_price
            elif mint in (USDC, USDT):
                quote_usd = balance

        if base_amt and base_amt > 0 and quote_usd and quote_usd > 0:
            price = quote_usd / base_amt
            liq   = quote_usd * 2  # total liq = 2× quote side
            return {"price": price, "liq": liq, "source": "helius_rpc"}

        return {}
    except Exception as e:
        logger.debug(f"Helius RPC pool price failed: {e}")
        return {}


async def get_helius_rug_signal(contract: str, api_key: str) -> dict:
    """
    Check last 5 transactions on the token for large liquidity removals.
    Returns {rug_detected: bool, reason: str}
    """
    if not api_key:
        return {"rug_detected": False}
    try:
        client = await get_http()
        url    = f"https://api.helius.xyz/v0/addresses/{contract}/transactions"
        r = await client.get(url, params={
            "api-key": api_key, "limit": "5",
            "type": "REMOVE_LIQUIDITY"
        }, timeout=5)
        if r.status_code != 200:
            return {"rug_detected": False}

        txns = r.json()
        if not isinstance(txns, list) or not txns:
            return {"rug_detected": False}

        # Any REMOVE_LIQUIDITY in last 5 txns = rug signal
        for tx in txns:
            desc = tx.get("description", "").lower()
            if "remove" in desc or "withdraw" in desc:
                return {
                    "rug_detected": True,
                    "reason": f"Liquidity removal detected on-chain"
                }
        return {"rug_detected": False}
    except Exception as e:
        logger.debug(f"Helius rug signal check failed: {e}")
        return {"rug_detected": False}


# ── Helius holder cache (5 min TTL) ──────────────────────────────────────────
_helius_holder_cache: dict = {}
HELIUS_HOLDER_CACHE_TTL = 300.0   # 5 minutes

async def get_helius_top_holders(contract: str, api_key: str) -> dict:
    """
    Fetch accurate top-20 holder data via Helius RPC.
    Uses three parallel-ish calls:
      1. getTokenLargestAccounts  → top 20 token accounts + raw amounts
      2. getTokenSupply           → total supply for % calculation
      3. getMultipleAccounts      → resolve token accounts → owner wallets

    Returns:
      top10_pct    : float   — % held by top 10 real wallets
      top20_pct    : float
      holders_data : list[{address, pct, amount}]
      source       : "helius_rpc"

    Protocol addresses and obvious pools (>70% of supply) are excluded.
    Same multi-pass outlier filter applied as the RugCheck path.
    Falls back gracefully → returns {} on any error.
    """
    if not api_key:
        return {}

    # ── Cache check ───────────────────────────────────────────────────────────
    cached = _helius_holder_cache.get(contract)
    if cached and (_time.time() - cached["ts"]) < HELIUS_HOLDER_CACHE_TTL:
        return cached["data"]

    try:
        client  = await get_http()
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"

        # ── Step 1 & 2: largest accounts + total supply in parallel ──────────
        largest_resp, supply_resp = await _asyncio.gather(
            client.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [contract, {"commitment": "confirmed"}]
            }, timeout=8),
            client.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 2,
                "method": "getTokenSupply",
                "params": [contract, {"commitment": "confirmed"}]
            }, timeout=8),
            return_exceptions=True
        )

        if isinstance(largest_resp, Exception) or isinstance(supply_resp, Exception):
            return {}
        if largest_resp.status_code != 200 or supply_resp.status_code != 200:
            return {}

        largest_data = largest_resp.json().get("result", {}).get("value", [])
        supply_info  = supply_resp.json().get("result", {}).get("value", {})
        total_supply = float(supply_info.get("uiAmount") or 0)

        if not largest_data or total_supply <= 0:
            return {}

        # ── Step 3: resolve token accounts → owner wallets ───────────────────
        # getTokenLargestAccounts returns token account addresses, not owner wallets.
        # One getMultipleAccounts call resolves all 20 at once.
        token_acct_addrs = [e.get("address", "") for e in largest_data if e.get("address")]
        if not token_acct_addrs:
            return {}

        multi_resp = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 3,
            "method": "getMultipleAccounts",
            "params": [token_acct_addrs, {"encoding": "jsonParsed", "commitment": "confirmed"}]
        }, timeout=8)

        if multi_resp.status_code != 200:
            return {}

        acct_values = multi_resp.json().get("result", {}).get("value", [])

        # ── Known protocol addresses — always exclude ─────────────────────────
        _PROTO = {
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
            "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1",
            "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
            "4wTV81aCK4cYbJGYLTBZaC7DqHBnZ7VJ4C3MeH9zGD5P",
            "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            "7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqtj2G5",
            "FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo",
            "So11111111111111111111111111111111111111112",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        }

        # ── Build holder list ─────────────────────────────────────────────────
        holders = []
        seen_owners: set = set()   # deduplicate wallets with multiple token accounts
        for acct in acct_values:
            if not acct:
                continue
            parsed = acct.get("data", {}).get("parsed", {}).get("info", {})
            owner  = parsed.get("owner", "")
            amount = float(parsed.get("tokenAmount", {}).get("uiAmount") or 0)
            if not owner or amount <= 0 or owner in _PROTO or owner in seen_owners:
                continue
            seen_owners.add(owner)
            pct = round(amount / total_supply * 100, 2)
            # Skip obvious pool/bonding curve accounts (>70% of supply)
            if pct > 70.0:
                logger.debug(f"Helius holders: skipping {owner[:12]} ({pct}% — pool/BC)")
                continue
            holders.append({"address": owner, "pct": pct, "amount": amount})

        if not holders:
            return {}

        holders.sort(key=lambda x: -x["pct"])

        # ── Multi-pass outlier filter (same as RugCheck path) ─────────────────
        _removed = 0
        for _ in range(5):
            if len(holders) < 4:
                break
            top       = holders[0]["pct"]
            rest_pcts = [h["pct"] for h in holders[1:]]
            mean_rest = sum(rest_pcts) / len(rest_pcts) if rest_pcts else 0
            if top >= 8.0 and mean_rest > 0 and top / mean_rest > 5.0:
                logger.debug(f"Helius outlier removed: {holders[0]['address'][:12]} ({top}%)")
                holders = holders[1:]
                _removed += 1
            else:
                break

        top10_pct = round(sum(h["pct"] for h in holders[:10]), 1)
        top20_pct = round(sum(h["pct"] for h in holders[:20]), 1)

        result = {
            "top10_pct":    top10_pct,
            "top20_pct":    top20_pct,
            "holders_data": holders[:20],
            "total_supply": total_supply,
            "source":       "helius_rpc",
        }
        _helius_holder_cache[contract] = {"data": result, "ts": _time.time()}
        logger.debug(
            f"Helius holders {contract[:12]}: top10={top10_pct}% "
            f"({len(holders)} real holders, {_removed} pools removed)"
        )
        return result

    except Exception as e:
        logger.debug(f"Helius top holders failed {contract[:12]}: {e}")
        return {}
