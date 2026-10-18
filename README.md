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

Data sources: DexScreener, pump.fun frontend API, RugCheck, Helius (optional),
GeckoTerminal, CoinGecko (SOL price fallback), Twitter oEmbed, Anthropic (optional).

## Layout
| File | Purpose |
|---|---|
| `sol_trading_bot.py` | Main bot: handlers, scoring, sniper/APEX jobs, UI |
| `config.py` | Environment-driven settings and simulated-cost constants |
| `api_clients.py` | Shared HTTP client, SOL price, Helius helpers |
| `access.py` | Single access-control gate for every handler |
| `slippage.py` | Simulated fee / price-impact model |
| `text_safety.py` | Markdown escaping, LLM prompt sanitising, advisory verdict merge |
| `safe_bot.py` | Telegram bot that resends as plain text on Markdown parse errors |
| `persistence.py` | Supabase (or SQLite fallback) persistence + autosave |
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

## Deploy on Railway
1. New Project → Deploy from GitHub repo.
2. Railway builds with Nixpacks (`nixpacks.toml`: Python 3.11, start command
   `python sol_trading_bot.py`). The bot uses long polling, so no port or domain is needed.
3. Variables: at least `BOT_TOKEN` and `ADMIN_IDS`, plus Supabase (recommended).
4. Run **one** replica only. Two instances polling the same token conflict.
5. Optional: attach a volume at `/data` if you use the SQLite fallback.

## Notes
- State is held in memory and persisted on changes and by an autosave every 120s.
- Daily jobs: summary 23:59, monthly report 08:00 on the 1st, weekly filter
  analysis 09:00 on Sundays, calibration around midnight, all in `BOT_TIMEZONE`.
