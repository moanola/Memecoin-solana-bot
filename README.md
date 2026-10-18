# APEX SNIPER BOT: Solana memecoin paper-trading bot (Telegram)

A Telegram bot for **paper trading** memecoins (mainly Solana, plus a few EVM
chains for display). Users get a simulated balance, paste contract addresses to
get token cards (score, RugCheck security, holder/KOL signals), and can buy and
sell at live DexScreener prices. An optional autonomous "APEX" mode and a
5-minute sniper scan take simulated entries and manage exits (trailing stops,
profit locks, daily loss limit, re-entry watchlist).

**It never touches real funds.** There are no wallets, private keys, signing
or on-chain swaps. All trades are simulated. Simulated costs are a 0.25% DEX
fee, plus slippage of max(0.5%, constant-product price impact of the trade
size vs pool liquidity), plus $0.002 gas.

## Features
- Telegram UI: `/start`, `/menu`, inline-button menus; paste a CA to scan it.
- Group mode: CA calls in groups, `/lb` leaderboard, `/stats @user`,
  `/pnl <symbol|CA>`, `/gpnl <12h|1d|7d|14d>` PnL image cards.
- Sniper (auto / advisory) scanning DexScreener boosts/profiles + pump.fun.
- APEX autonomous mode with risk controls and nightly self-calibration.
- KOL wallet tracking via Helius (alerts + score boost; no copy trading).
- Optional Claude verdict on token cards. It is **advisory only**: it can make
  the rule-based verdict more cautious but never upgrade it.
- Daily / weekly / monthly reports, competitions, PnL cards (Pillow/matplotlib).
- Admin: `/admin` (approve/deny access, ban, broadcast, pause sniper, ...).
- Mobile terminal: a Telegram Mini App and an installable PWA on the same
  paper account (token feed, chart, quick buy/sell, live positions, APEX, leaderboard).
- Edge signals (each behind a flag, on by default). See **Edge features** below.

Data sources: DexScreener, pump.fun frontend API, RugCheck, Helius (optional),
GeckoTerminal, CoinGecko (SOL price fallback), Twitter oEmbed, Anthropic (optional),
[MemeFees](https://memefees.com) (pump.fun fees, volume, fee share; fees and volume are DefiLlama's).

## Edge features

Paper signals only. Nothing here signs a transaction. Logic lives in `edge/`
and is called from the bot, the API, and the terminal. Flags are read from the
environment on each use (`true` / `false`). Defaults are on.

| Flag | Default | What it does |
|---|---|---|
| `EDGE_CUSTOM_PAIRS` | `true` | Price, volume, and maker/wash stats when the quote is not SOL. Shows the pair on token cards and the terminal. |
| `EDGE_KOL_EXITS` | `true` | KOL sell alerts (partial/full, % of bag), airdrop-vs-buy, side wallets from a shared SOL funder, and decay of the KOL score boost. |
| `EDGE_LAUNCH_GROUP` | `true` | Cluster earliest buyers (same slot plus Jito tip, common funder, or identical fee and compute). |
| `EDGE_LAUNCH_GROUP_EXIT_PCT` | `40` | APEX exits when a *confident* launch group has sold at least this percent. |
| `EDGE_DEV_CASHOUT` | `true` | Pre-dump alert and a score penalty when seller SOL consolidates, or a hub pays sellers' gas. |
| `EDGE_DEV_CASHOUT_APEX_EXIT` | `true` | That alert is also an APEX exit. |
| `EDGE_RUG_MEMORY` | `true` | Remember creator/funder wallets and penalise a later launch linked to a rug. |
| `EDGE_RUG_DROP_PCT` | `90` | Fast-drop rug: price down this percent. |
| `EDGE_RUG_WINDOW_MIN` | `30` | Window for that drop. LP pull and a confident group dump also mark a rug. |
| `EDGE_COPYCAT` | `true` | Group lookalike name/ticker/image launches. Copies are labelled and not auto-bought. |
| `EDGE_HOLDER_VELOCITY` | `true` | Holders/hour and, when history reaches the launch, % of the first ~70 buyers still holding. |
| `EDGE_HOLDER_REENTRY_MIN_RETENTION` | `25` | Watchlist re-entry blocks only when retention is known and below this. |
| `EDGE_MARKET_MOOD` | `true` | Daily pump.fun mood. Scales APEX size and the heat ceiling. Shown on `/stats` and the terminal. |
| `EDGE_EXIT_PLAN` | `true` | Manual paper buys store a take-profit, invalidation, and time stop. The checker enforces them. |
| `EDGE_EXIT_DEFAULT_PRESET` | `standard` | `scalp` (1.5× / 12% / 30m), `standard` (2× / 18% / 120m), or `runner` (3× / 25% / 360m). |
| `EDGE_HELIUS_PER_MIN` | `8` | Cap on the shared launch-group / cash-out / retention Helius page. |

### Data sources and what was verified

- **Custom pairs.** [pump.fun/docs/custom-pairs](https://pump.fun/docs/custom-pairs) (page last updated 2026-10-09): any pump.fun coin can be the quote; buys route through the parent pool; holder rewards are paid in the paired asset. The Supported Pair Assets table is copied into `edge/supported_quotes.py`. A mint that is not on that list is labelled `unlisted`. Secondary Pair Asset status is fixed at the parent's launch and is **not** on the list, so the bot does not claim a mint is a secondary pair.
- **PumpSwap pool.** Public IDL `pump_amm.json`, program `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`. `Pool.virtual_quote_reserves` is a signed i128. Spot uses `vault + virtual` (clamped at 0), times the quote asset's USD price. `protocol_fees` and `creator_fees` sit on the account until collected; a sweep is a **drop versus the previous observation** of that pair, never a single snapshot. Verified instruction discriminators: `buy`, `buy_exact_quote_in`, `buy_exact_quote_in_v2`, `sell`, `sell_v2`, `multi_hop_swap`. The fetched IDL has **no v3 trade instruction and no synthetic-migration instruction**. Those names from the October 2026 write-ups are not decoded.
- **DexScreener `priceNative`** is the chain-native price (SOL), not quote-token units. It is not multiplied by the quote's USD price. USD is derived only when `priceUsd` is missing and both liquidity sides are present. Custom and unlisted quotes are marked indicative, matching the docs on multi-pool prices.
- **Jito tip accounts** are the eight addresses published by Jito. A Helius `source` of `JITO` is also accepted. Same-slot clustering is a heuristic, not proof of one bundle.
- **Helius enhanced transactions** (`type`, `feePayer`, `tokenTransfers`, `nativeTransfers`, `slot`, `fee`) are a parser schema. KOL bag percent needs the in-memory ledger. A shared SOL funder is not a proven identity link. Retention is computed only when the transaction page is shorter than the fetch limit; a full newest-first page is not treated as the first buyers, and it will not auto-exit a launch group.
- **Market mood.** `GET https://memefees.com/api/v1/pad-daily?pad=pump-fun&days=14` and `GET https://memefees.com/api/v1/market-share` (no key). Fees and volume are DefiLlama (`source=defillama`). Attribute MemeFees and link memefees.com. MemeFees-produced data is CC BY 4.0. If those endpoints fail, the gauge falls back to a GeckoTerminal pumpswap pool volume sum and says that fee share is unknown.

Rug-wallet memory and the copycat index are stored in the persistence `kv` blob (`rug_memory`, `copycat_index`), flushed by the existing autosave. Supabase needs:

```sql
CREATE TABLE IF NOT EXISTS bot_kv (
    key TEXT PRIMARY KEY, data TEXT NOT NULL, updated BIGINT NOT NULL);
ALTER TABLE bot_kv ENABLE ROW LEVEL SECURITY;
```

SQLite creates the same `kv` table on its own. If `bot_kv` is missing, the bot logs the error once and keeps running.

## Layout
| File | Purpose |
|---|---|
| `sol_trading_bot.py` | Main bot: handlers, scoring, sniper/APEX jobs, UI. Starts the API on the same loop |
| `edge/` | Paper-only edge signals (custom pairs, KOL exits, launch group, cash-out, rug memory, copycats, holders, mood, exit plans) |
| `webapi.py` | FastAPI terminal: balance, positions, feed, paper buy/sell, APEX, leaderboard, WebSocket |
| `telegram_auth.py` | Mini App initData and Login Widget checks (HMAC, auth_date) |
| `config.py` | Environment-driven settings and simulated-cost constants |
| `api_clients.py` | Shared HTTP client, SOL price, Helius helpers |
| `access.py` | Single access-control gate for every handler and the terminal |
| `slippage.py` | Simulated fee / price-impact model |
| `text_safety.py` | Markdown escaping, LLM prompt sanitising, advisory verdict merge |
| `safe_bot.py` | Telegram bot that resends as plain text on Markdown parse errors |
| `persistence.py` | Supabase (or SQLite fallback) persistence + autosave |
| `webapp/` | Vite + React PWA (static). Talks to the API; holds no trading logic |
| `tests/` | pytest suite (no network) |

## Environment variables
| Variable | Required | Default | Notes |
|---|---|---|---|
| `BOT_TOKEN` | **yes** |  | Telegram bot token from @BotFather |
| `ADMIN_IDS` | recommended | (none) | Comma-separated Telegram user IDs |
| `ACCESS_CONTROL_ENABLED` | no | `true` | New users need admin approval |
| `ACCESS_ADMIN_USERNAME` | no | `auracle_x` | Shown to users asking for access (no `@`) |
| `SUPABASE_URL` | no* | | `https://<project>.supabase.co` |
| `SUPABASE_KEY` | no* | | **service_role** key, server-side only (see below) |
| `HELIUS_API_KEY` | no | | Enables Helius enrichment, KOL tracking, faster APEX pricing |
| `ANTHROPIC_API_KEY` | no | | Enables the advisory Claude verdict |
| `ANTHROPIC_MODEL` | no | `claude-haiku-4-5-20251001` | Claude model id |
| `BOT_TIMEZONE` | no | `UTC` | IANA tz for daily/weekly/monthly jobs |
| `FILL_MAX_PRICE_AGE_S` | no | `5` | Re-fetch the quote at fill time if older than this |
| `PORT` | on Railway | `8080` | HTTP port for the terminal API. Railway sets this |
| `WEBAPP_URL` | for the Mini App |  | HTTPS URL of the PWA. Enables `/terminal` and the chat menu button |
| `WEBAPP_ORIGIN` | for the browser |  | CORS allow-list for the PWA origin. Comma-separated. Usually the same host as `WEBAPP_URL` |
| `INITDATA_MAX_AGE_S` | no | `86400` | Reject Telegram initData / login payloads older than this |

Frontend build (Vite, not read by the bot):

| Variable | Notes |
|---|---|
| `VITE_API_BASE` | Public Railway URL of this service, no trailing slash. Baked in at `npm run build` |
| `VITE_BOT_USERNAME` | Bot username without `@`. Shows the Telegram Login Widget outside the Mini App |

\* Without Supabase the bot uses SQLite at `/data/auracle_bot.db` (if `/data`
exists, e.g. a Railway volume) or next to the script. Without a volume, that
data is lost on every redeploy.

## Local setup
```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export BOT_TOKEN=...            # a test bot, not your production one
python sol_trading_bot.py
pytest                          # runs offline
```

## Supabase setup
1. Create a project at https://supabase.com.
2. SQL editor:
   ```sql
   CREATE TABLE IF NOT EXISTS bot_users (
       uid BIGINT PRIMARY KEY, data TEXT NOT NULL, updated BIGINT NOT NULL);
   CREATE TABLE IF NOT EXISTS bot_trade_log (
       uid BIGINT PRIMARY KEY, data TEXT NOT NULL, updated BIGINT NOT NULL);

   -- Lock the tables down: with RLS on and no policies, the public
   -- anon/authenticated roles can neither read nor write.
   ALTER TABLE bot_users     ENABLE ROW LEVEL SECURITY;
   ALTER TABLE bot_trade_log ENABLE ROW LEVEL SECURITY;
   ```
3. Project Settings → API: copy the Project URL and the **service_role** key.
   The service_role key bypasses RLS, so only this server can access the data.
   Keep it **server-side only**: put it in Railway Variables, never in the repo,
   a client app, or chat. If it leaks, rotate it in Supabase.
4. Set `SUPABASE_URL` and `SUPABASE_KEY` in Railway.

Do not use the `anon` key with RLS disabled: anyone who has it can read and
overwrite every user's data.

## Terminal architecture

The API is not a second service. `main()` still runs Telegram long polling, and
on startup it also serves FastAPI with uvicorn on `0.0.0.0:$PORT` **in that
same asyncio loop**. Route handlers call `do_buy_core`, `sell_core`,
`get_token`, `sniper_score`, `ai_analyze_token`, and the APEX vault fields
directly, so a buy in the terminal is the same paper fill the chat would make
(including the slippage model) and shows up in both places.

```
Telegram  ──polling──►  sol_trading_bot.py  ◄──shared dicts──►  webapi.py  :$PORT
                              │                                    ▲
                              │ sniper_job records scores          │ HTTPS
                              ▼                                    │
                         users / trade_log / token cache           │
                                                                   │
                        webapp/  (Vite build on Vercel or Pages) ──┘
                        Telegram Mini App  or  installed PWA
```

Auth, on every trading route:

1. `Authorization: tma <initData>` (Mini App) is checked with HMAC-SHA256 and
   the bot token, per Telegram's Mini App docs, and `auth_date` must be fresh.
2. Or `Authorization: Bearer <session>` from `POST /api/auth/login` (Login Widget).
3. The Telegram user id then goes through `access_allowed` — the same rule as
   `access.py`. Unapproved users get 403 and no user record is created.
   There is no unauthenticated buy/sell.

`/health` is public so Railway can probe the process. CORS only allows
`WEBAPP_ORIGIN`. The WebSocket at `/api/ws` pushes balance and open-position
PnL about every 5 seconds, using the same price cache as the bot.

## Deploy the API on Railway (with the bot)

1. New Project → Deploy from GitHub repo.
2. Railway builds with Nixpacks (`nixpacks.toml`: Python 3.11, start command
   `python sol_trading_bot.py`). That one process polls Telegram **and**
   listens on `$PORT`.
3. Settings → Networking → generate a public domain. Copy the `https://…up.railway.app`
   URL. This is `VITE_API_BASE` for the frontend, not `WEBAPP_URL`.
4. Variables: `BOT_TOKEN`, `ADMIN_IDS`, Supabase (recommended), and once the
   frontend exists:
   - `WEBAPP_URL` = `https://<your-frontend-host>` (no path)
   - `WEBAPP_ORIGIN` = the same origin
5. Run **one** replica only. Two instances polling the same token conflict,
   and they would also split the in-memory book.
6. Optional: attach a volume at `/data` if you use the SQLite fallback.
7. Health check path: `/health`.

## Deploy the frontend (Vercel or Cloudflare Pages)

The `webapp/` directory is a static Vite build. It does not contain the bot
token and cannot trade by itself.

```bash
cd webapp
cp .env.example .env.local    # set VITE_API_BASE and VITE_BOT_USERNAME
npm install
npm run build                 # output in webapp/dist
```

**Vercel:** New Project → this repo, Root Directory `webapp`, Framework Vite.
Add `VITE_API_BASE` and `VITE_BOT_USERNAME` as build env vars. `vercel.json`
rewrites unknown paths to `index.html`.

**Cloudflare Pages:** same root, build command `npm run build`, output `dist`.
`public/_redirects` is the SPA fallback.

Then set Railway `WEBAPP_URL` and `WEBAPP_ORIGIN` to that site (for example
`https://apex-terminal.vercel.app`) and redeploy the bot once so `/terminal`
and the menu button pick it up.

## Register the Mini App with BotFather

1. `/mybots` → your bot → **Bot Settings** → **Menu Button** → set the text
   (the process also calls `setChatMenuButton` when `WEBAPP_URL` is https).
2. **Configure Mini App** / `/newapp` and paste the same `WEBAPP_URL`.
   Telegram only accepts **https**.
3. For the Login Widget (browser, outside Telegram): `/setdomain` to the
   frontend host, without `https://`. Set `VITE_BOT_USERNAME` and rebuild.
4. Open the bot, tap the menu button or send `/terminal`. The button is a
   `WebAppInfo` link, so Telegram injects `initData` and the PWA signs in
   as that user. Access control still applies: `/start` and admin approval
   first if `ACCESS_CONTROL_ENABLED` is on.

## Install the PWA on Android

1. Open the frontend URL in **Chrome** (the Vercel/Pages host, not the Railway API).
2. Wait until the page loads. The build ships a web manifest, a service worker,
   and 192/512 icons, so Chrome treats it as installable.
3. Menu (⋮) → **Install app** or **Add to Home screen**. Confirm.
4. Launch **APEX** from the home screen. It opens standalone, full screen.
   Sign-in outside Telegram uses the Login Widget (`VITE_BOT_USERNAME` and
   BotFather `/setdomain`). Inside the Telegram menu button you are already signed in.
5. The service worker caches the app shell only. Prices and orders always come
   from the API.

## Local terminal

```bash
# bot + API (API on :8080, or $PORT)
export BOT_TOKEN=...
export WEBAPP_ORIGIN=http://127.0.0.1:5173
python sol_trading_bot.py

# frontend
cd webapp && npm install
echo 'VITE_API_BASE=http://127.0.0.1:8080' > .env.local
npm run dev
```

## Notes
- State is held in memory and persisted on changes and by an autosave every 120s.
- Daily jobs: summary 23:59, monthly report 08:00 on the 1st, weekly filter
  analysis 09:00 on Sundays, calibration around midnight, all in `BOT_TIMEZONE`.
- The terminal never adds a wallet or a signing path. Buys and sells are the
  bot's existing paper fills.
- A sell from the terminal updates the same position and trade log. It does not
  send the Telegram PnL image; that card is part of the chat UI.
- Token charts use GeckoTerminal candles when a pool is known, and fall back
  to the position's stored price history. The feed is whatever the sniper job
  last scored, plus an on-demand `sniper_scan` if that cache is empty.
