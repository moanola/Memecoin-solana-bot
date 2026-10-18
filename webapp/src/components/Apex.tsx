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
        <div className="mt-4 text-[11px] uppercase tracking-wider text-mute">Capital heat {heat.toFixed(0)}%</div>
        <div className="mt-1 h-2 rounded-full bg-panel2 overflow-hidden">
          <div className="h-full bg-cyan" style={{ width: `${heat}%` }} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Cell k="Vault" v={money(status.vault)} />
          <Cell k="Today" v={signed(status.daily_pnl)} />
          <Cell k="Positions" v={String(status.positions)} />
          <Cell k="Win rate" v={`${status.win_rate}%`} />
          <Cell k="Phase" v={status.phase} />
          <Cell k="Trades" v={String(status.trades)} />
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

function Cell({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-mute">{k}</div>
      <div className="num">{v}</div>
    </div>
  );
}
