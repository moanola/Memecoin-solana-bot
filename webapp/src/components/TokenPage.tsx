import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { age, money, pct, price, signed } from "../format";
import { haptic } from "../telegram";
import type { Candle, ExitPlan, TokenDetail } from "../types";
import { PriceChart } from "./Chart";
import { ScoreRing } from "./Score";

const PRESETS = [25, 50, 100, 250];
const SELLS = [25, 50, 75, 100];
const EXIT_PRESETS: Record<string, ExitPlan> = {
  scalp: { preset: "scalp", tp_x: 1.5, tp_pct: 1, invalidation_pct: 12, time_stop_min: 30 },
  standard: { preset: "standard", tp_x: 2, tp_pct: 0.5, invalidation_pct: 18, time_stop_min: 120 },
  runner: { preset: "runner", tp_x: 3, tp_pct: 0.33, invalidation_pct: 25, time_stop_min: 360 },
};

export function TokenPage({
  contract,
  quickBuy,
  balanceSet,
  onBack,
  onChanged,
}: {
  contract: string;
  quickBuy: number;
  balanceSet: boolean;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [token, setToken] = useState<TokenDetail | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [amount, setAmount] = useState(quickBuy || 100);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exitPreset, setExitPreset] = useState("standard");
  const [tpX, setTpX] = useState("2");
  const [invalidation, setInvalidation] = useState("18");
  const [timeStop, setTimeStop] = useState("120");

  function applyPreset(name: string) {
    const plan = EXIT_PRESETS[name];
    setExitPreset(name);
    setTpX(String(plan.tp_x));
    setInvalidation(String(plan.invalidation_pct));
    setTimeStop(String(plan.time_stop_min));
    haptic("light");
  }

  useEffect(() => {
    let gone = false;
    setError(null);
    Promise.all([api.token(contract), api.candles(contract)])
      .then(([detail, bars]) => {
        if (gone) return;
        setToken(detail);
        setCandles(bars.candles);
      })
      .catch((err: unknown) => {
        if (!gone) setError(err instanceof ApiError ? err.message : "Could not load token");
      });
    return () => {
      gone = true;
    };
  }, [contract]);

  async function reload() {
    const [detail, bars] = await Promise.all([api.token(contract), api.candles(contract)]);
    setToken(detail);
    setCandles(bars.candles);
    onChanged();
  }

  async function buy() {
    const usd = custom ? Number(custom) : amount;
    if (!usd || usd <= 0) return;
    setBusy("buy");
    setError(null);
    try {
      const res = await api.buy(contract, usd, {
        preset: exitPreset,
        tp_x: Number(tpX) || undefined,
        invalidation_pct: Number(invalidation) || undefined,
        time_stop_min: Number(timeStop) || undefined,
      });
      haptic("success");
      setNote(`Bought ${res.symbol} · fee ${money(res.fee)} · cash ${money(res.balance)}`);
      setCustom("");
      await reload();
    } catch (err) {
      haptic("error");
      setNote(null);
      setError(err instanceof ApiError ? err.message : "Buy failed");
    } finally {
      setBusy(null);
    }
  }

  async function sell(percent: number) {
    setBusy(`sell-${percent}`);
    setError(null);
    try {
      const res = await api.sell(contract, percent);
      haptic("success");
      setNote(
        res.closed
          ? `Closed ${res.symbol} · ${signed(res.realized)} · cash ${money(res.balance)}`
          : `Sold ${percent}% · received ${money(res.received)}`,
      );
      await reload();
    } catch (err) {
      haptic("error");
      setError(err instanceof ApiError ? err.message : "Sell failed");
    } finally {
      setBusy(null);
    }
  }

  if (error && !token) return <div className="card p-4 text-sm text-loss">{error}</div>;
  if (!token) return <div className="text-mute text-sm">Loading token…</div>;

  const up = token.ch_h24 >= 0;
  const ai = token.ai;
  return (
    <div className="space-y-3 pb-4">
      <button onClick={onBack} className="text-xs uppercase tracking-[0.16em] text-cyan">
        ← Back
      </button>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] tracking-[0.16em] uppercase text-mute">
            {token.chain || "solana"} · {token.dex || "dex"} · {age(token.age_h)}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">${token.symbol}</h1>
          <div className="text-sm text-mute truncate">{token.name}</div>
        </div>
        <ScoreRing score={token.score} size={52} />
      </div>
      <div className="flex items-end justify-between">
        <div className="num text-3xl">{price(token.price)}</div>
        <div className={up ? "text-gain num" : "text-loss num"}>{pct(token.ch_h24)} 24h</div>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <Stat label="MC" value={money(token.mc)} />
        <Stat label="Liq" value={money(token.liq)} />
        <Stat label="1h" value={pct(token.ch_h1)} tone={(token.ch_h1 || 0) >= 0 ? "up" : "down"} />
      </div>
      <EdgeNotes token={token} />
      <PriceChart candles={candles} />

      {ai && (
        <div className="card p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] tracking-[0.16em] uppercase text-mute">AI verdict</span>
            <span className="chip">{ai.verdict || "—"} · {ai.confidence ?? "—"}/10</span>
          </div>
          <p className="text-sm leading-relaxed">{ai.thesis}</p>
          <div className="flex flex-wrap gap-2 text-[11px]">
            {ai.rug_risk && <span className="chip">Rug {ai.rug_risk}</span>}
            {ai.momentum && <span className="chip">{ai.momentum}</span>}
          </div>
          {ai.red_flags.length > 0 && (
            <ul className="text-xs text-loss space-y-1">
              {ai.red_flags.map((f) => <li key={f}>{f}</li>)}
            </ul>
          )}
          {ai.green_flags.length > 0 && (
            <ul className="text-xs text-gain space-y-1">
              {ai.green_flags.map((f) => <li key={f}>{f}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="card p-3">
        <div className="text-[11px] tracking-[0.16em] uppercase text-mute mb-2">RugCheck</div>
        <div className="grid grid-cols-2 gap-y-1 text-sm">
          <Flag ok={token.rug.no_mint === true} label="Mint disabled" bad={token.rug.no_mint === false} />
          <Flag ok={token.rug.no_freeze === true} label="Freeze disabled" bad={token.rug.no_freeze === false} />
          <span className="text-mute">LP burn</span>
          <span className="num text-right">{token.rug.lp_burn == null ? "—" : `${token.rug.lp_burn}%`}</span>
          <span className="text-mute">Top 10</span>
          <span className="num text-right">{token.rug.top10_pct == null ? "—" : `${token.rug.top10_pct}%`}</span>
        </div>
        {token.rug.rate_limited && <div className="text-xs text-amber mt-2">RugCheck rate-limited — security fields may be stale.</div>}
        {token.rug.risks.slice(0, 3).map((r) => (
          <div key={r} className="text-xs text-loss mt-1">{r}</div>
        ))}
      </div>

      {token.position && (
        <div className="card p-3 flex justify-between items-center">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-mute">Open position</div>
            <div className="num">{money(token.position.value)}</div>
          </div>
          <div className={token.position.pnl >= 0 ? "text-gain num" : "text-loss num"}>
            {signed(token.position.pnl)}
          </div>
        </div>
      )}

      <div className="card p-3 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] tracking-[0.16em] uppercase text-mute">Paper buy</span>
          {token.slippage && (
            <span className="text-[11px] text-mute num">
              slip {token.slippage.slippage_pct}% on {money(token.slippage.sample_usd)}
            </span>
          )}
        </div>
        <div className="grid grid-cols-4 gap-2">
          {PRESETS.map((n) => (
            <button
              key={n}
              onClick={() => { setAmount(n); setCustom(""); haptic("light"); }}
              className={`rounded-xl py-2 text-sm num border ${!custom && amount === n ? "border-cyan text-cyan" : "border-line"}`}
            >
              ${n}
            </button>
          ))}
        </div>
        <input
          inputMode="decimal"
          placeholder="Custom USD"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          className="w-full bg-panel2 border border-line rounded-xl px-3 py-2 num outline-none"
        />
        <div className="text-[11px] tracking-[0.16em] uppercase text-mute">Exit plan before buy</div>
        <div className="grid grid-cols-3 gap-2">
          {Object.keys(EXIT_PRESETS).map((name) => (
            <button
              key={name}
              onClick={() => applyPreset(name)}
              className={`rounded-xl py-2 text-xs uppercase tracking-wider border ${exitPreset === name ? "border-cyan text-cyan" : "border-line text-mute"}`}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <label className="text-[10px] uppercase tracking-wider text-mute">
            TP ×
            <input value={tpX} inputMode="decimal" onChange={(e) => setTpX(e.target.value)} className="mt-1 w-full bg-panel2 border border-line rounded-xl px-2 py-2 num text-sm outline-none" />
          </label>
          <label className="text-[10px] uppercase tracking-wider text-mute">
            Invalidation %
            <input value={invalidation} inputMode="decimal" onChange={(e) => setInvalidation(e.target.value)} className="mt-1 w-full bg-panel2 border border-line rounded-xl px-2 py-2 num text-sm outline-none" />
          </label>
          <label className="text-[10px] uppercase tracking-wider text-mute">
            Time stop min
            <input value={timeStop} inputMode="decimal" onChange={(e) => setTimeStop(e.target.value)} className="mt-1 w-full bg-panel2 border border-line rounded-xl px-2 py-2 num text-sm outline-none" />
          </label>
        </div>
        <div className="text-[11px] text-mute">
          Paper only. The checker sells at the first of these. Selling earlier is logged as a rule break.
        </div>
        {!balanceSet && <div className="text-xs text-amber">Set a starting balance with /start in Telegram before buying.</div>}
        <button
          disabled={busy !== null || !balanceSet}
          onClick={buy}
          className="w-full rounded-xl py-3 font-semibold bg-gain text-[#062117] disabled:opacity-50"
        >
          {busy === "buy" ? "Filling…" : `Buy $${custom || amount}`}
        </button>
        {token.position && (
          <div className="grid grid-cols-4 gap-2">
            {SELLS.map((n) => (
              <button
                key={n}
                disabled={busy !== null}
                onClick={() => sell(n)}
                className="rounded-xl py-2 text-sm border border-loss/40 text-loss disabled:opacity-50"
              >
                {busy === `sell-${n}` ? "…" : `${n}%`}
              </button>
            ))}
          </div>
        )}
        {note && <div className="text-sm text-gain">{note}</div>}
        {error && <div className="text-sm text-loss">{error}</div>}
      </div>
      <div className="text-[11px] text-mute break-all num">{token.contract}</div>
    </div>
  );
}

function EdgeNotes({ token }: { token: TokenDetail }) {
  const rows: Array<{ tone: string; text: string }> = [];
  if (token.pair_label || token.quote_symbol) {
    rows.push({
      tone: "text-cyan",
      text: `Pair ${token.pair_label || token.quote_symbol}${token.price_indicative ? " · price indicative" : ""}${token.quote_kind ? ` · ${token.quote_kind}` : ""}`,
    });
  }
  if (token.copycat_label) rows.push({ tone: token.copycat_role === "copy" ? "text-loss" : "text-cyan", text: token.copycat_label });
  if (typeof token.launch_group_sold_pct === "number") {
    rows.push({
      tone: token.launch_group_sold_pct >= 25 ? "text-amber" : "text-mute",
      text: `Launch group sold ${token.launch_group_sold_pct.toFixed(0)}%${token.launch_group_size ? ` · ${token.launch_group_size} wallets` : ""}`,
    });
  }
  if (token.dev_cashout) rows.push({ tone: "text-loss", text: token.dev_cashout_reason || "Dev cash-out pattern" });
  if (token.rug_memory_note) rows.push({ tone: "text-loss", text: token.rug_memory_note });
  if (token.kol_exit_note) rows.push({ tone: "text-amber", text: token.kol_exit_note });
  if (token.fee_sweep) rows.push({ tone: "text-amber", text: "Pool fees swept since last read" });
  if (typeof token.holders_per_hour === "number") {
    const held = typeof token.holder_retention_pct === "number" ? ` · ${token.holder_retention_pct.toFixed(0)}% of early buyers still in` : "";
    rows.push({ tone: "text-mute", text: `${token.holders_per_hour.toFixed(1)} holders/hour${held}` });
  }
  if (token.position?.exit_plan) {
    const p = token.position.exit_plan;
    rows.push({ tone: "text-cyan", text: `Exit plan ${p.preset}: ${p.tp_x}× · −${p.invalidation_pct}% · ${p.time_stop_min}m` });
  }
  if (!rows.length) return null;
  return (
    <div className="card p-3 space-y-1">
      <div className="text-[11px] tracking-[0.16em] uppercase text-mute">Edge</div>
      {rows.map((row) => (
        <div key={row.text} className={`text-sm ${row.tone}`}>{row.text}</div>
      ))}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="card py-2">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`num text-sm ${tone === "up" ? "text-gain" : tone === "down" ? "text-loss" : ""}`}>{value}</div>
    </div>
  );
}

function Flag({ ok, bad, label }: { ok: boolean; bad: boolean; label: string }) {
  return (
    <>
      <span className="text-mute">{label}</span>
      <span className={`num text-right ${ok ? "text-gain" : bad ? "text-loss" : "text-mute"}`}>
        {ok ? "Yes" : bad ? "No" : "—"}
      </span>
    </>
  );
}
