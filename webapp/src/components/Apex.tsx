import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { money, signed } from "../format";
import { haptic } from "../telegram";
import type { ApexStatus } from "../types";

export function Apex({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<ApexStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setStatus(await api.apex());
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : "APEX unavailable"));
  }, []);

  async function run(fn: () => Promise<ApexStatus>) {
    setBusy(true);
    setError(null);
    try {
      setStatus(await fn());
      haptic("success");
      onChanged();
    } catch (err) {
      haptic("error");
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  if (!status) return <div className="text-mute text-sm">{error || "Loading APEX…"}</div>;
  const heat = Math.max(0, Math.min(100, status.heat_pct));
  return (
    <div className="space-y-3">
      <div>
        <div className="text-[11px] tracking-[0.18em] uppercase text-mute">Autonomous</div>
        <h1 className="text-xl font-semibold">APEX</h1>
      </div>
      <div className="card p-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-mute">Status</div>
            <div className="text-2xl font-semibold capitalize">{status.state}</div>
          </div>
          <button
            disabled={busy}
            onClick={() => run(() => api.apexToggle(!status.enabled))}
            className={`px-4 py-2 rounded-full text-sm font-semibold ${status.enabled ? "bg-loss text-white" : "bg-gain text-[#062117]"}`}
          >
            {status.enabled ? "Disable" : "Enable"}
          </button>
        </div>
        {status.mood && (
          <div className="mt-4 rounded-xl border border-line p-3">
            <div className="text-[11px] uppercase tracking-wider text-mute text-center">Market mood</div>
            <MoodGauge score={status.mood.score} label={status.mood.label} />
            <div className="mt-1 text-xs text-mute num text-center">
              size ×{status.mood.size_mult} · heat ×{status.mood.heat_scale}
              {status.mood.share_7d_pct != null ? ` · pump.fun ${status.mood.share_7d_pct.toFixed(1)}%` : ""}
            </div>
            <div className="mt-1 text-[10px] text-mute text-center">{status.mood.attribution}</div>
          </div>
        )}
        <div className="mt-4 text-[11px] uppercase tracking-wider text-mute">Capital heat {heat.toFixed(0)}%</div>
        <div className="mt-1 h-2 rounded-full bg-panel2 overflow-hidden">
          <div className="h-full bg-cyan" style={{ width: `${heat}%` }} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Cell k="Vault" v={money(status.vault)} />
          <Cell k="Today" v={signed(status.daily_pnl)} />
          <Cell k="Positions" v={String(status.positions)} />
          <Cell k="Win rate" v={status.win_rate == null ? "—" : `${status.win_rate}%`} />
          <Cell k="Phase" v={status.phase} />
          <Cell k="Closed" v={String(status.trades)} />
          {status.positions > 0 && status.trades === 0 && (
            <div className="col-span-2 text-[11px] text-mute">
              Open position is live. Win rate counts closed APEX trades. Heat is vault capital in the market
              {status.deployed ? ` (${money(status.deployed)} deployed)` : ""}.
            </div>
          )}
        </div>
      </div>
      <div className="card p-4 space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-mute">Fund vault from balance</div>
        <div className="grid grid-cols-3 gap-2">
          {[50, 100, 250].map((n) => (
            <button key={n} disabled={busy} onClick={() => run(() => api.vault("fund", n))} className="border border-line rounded-xl py-2 num text-sm">
              ${n}
            </button>
          ))}
        </div>
        <button disabled={busy} onClick={() => run(() => api.vault("withdraw", status.vault || 0))} className="text-xs text-mute underline">
          Withdraw vault to balance
        </button>
      </div>
      <div className="card p-4 space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-mute">
          Profit split to balance · now {Math.round(status.profit_split * 100)}%
        </div>
        <div className="grid grid-cols-4 gap-2">
          {[25, 50, 75, 100].map((n) => (
            <button key={n} disabled={busy} onClick={() => run(() => api.split(n))} className={`rounded-xl py-2 text-sm border ${Math.round(status.profit_split * 100) === n ? "border-cyan text-cyan" : "border-line"}`}>
              {n}%
            </button>
          ))}
        </div>
        <p className="text-xs text-mute">Same vault and split the Telegram APEX menu uses. APEX still trades only from the vault.</p>
      </div>
      {error && <div className="text-sm text-loss">{error}</div>}
    </div>
  );
}

function MoodGauge({ score, label }: { score: number; label: string }) {
  const s = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const r = 62;
  const cx = 80;
  const cy = 78;
  const start = Math.PI;
  const end = Math.PI + (s / 100) * Math.PI;
  const x1 = cx + r * Math.cos(start);
  const y1 = cy + r * Math.sin(start);
  const x2 = cx + r * Math.cos(end);
  const y2 = cy + r * Math.sin(end);
  const large = s > 50 ? 1 : 0;
  const color = label === "HOT" || label === "WARM" ? "var(--gain)" : label === "COLD" ? "var(--loss)" : "var(--cyan)";
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 160 100" className="w-full max-w-[240px]" role="img" aria-label={`${label} ${Math.round(s)}`}>
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="rgba(160,176,198,0.2)" strokeWidth="10" strokeLinecap="round" />
        {s > 0 && (
          <path d={`M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />
        )}
        <line x1={cx} y1={cy} x2={x2} y2={y2} stroke="var(--text)" strokeWidth="2" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="3" fill="var(--text)" />
        <text x="80" y="72" textAnchor="middle" fontSize="18" fill="var(--text)" fontFamily="IBM Plex Mono, ui-monospace, monospace">
          {Math.round(s)}
        </text>
      </svg>
      <div className="text-sm font-semibold -mt-1">{label}</div>
    </div>
  );
}

function Cell({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-mute">{k}</div>
      <div className="num">{v}</div>
    </div>
  );
}
