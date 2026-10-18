import { age, money, pct } from "../format";
import type { FeedToken } from "../types";
import { ScoreRing } from "./Score";

export function Feed({
  tokens,
  loading,
  onOpen,
  onRefresh,
}: {
  tokens: FeedToken[];
  loading: boolean;
  onOpen: (contract: string) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] tracking-[0.18em] uppercase text-mute">Sniper feed</div>
          <h1 className="text-xl font-semibold tracking-tight">Live scan</h1>
        </div>
        <button
          className="text-xs uppercase tracking-wider text-cyan border border-line rounded-full px-3 py-1"
          onClick={onRefresh}
        >
          {loading ? "Scanning" : "Refresh"}
        </button>
      </div>
      {tokens.length === 0 && !loading && (
        <div className="card p-5 text-sm text-mute">
          Scanner is quiet. Refresh to pull the latest DexScreener and pump.fun pass, or wait for the bot's 5-minute sniper cycle.
        </div>
      )}
      <div className="space-y-3 lg:grid lg:grid-cols-2 lg:gap-3 lg:space-y-0">
      {tokens.map((t) => {
        const up = (t.ch_h1 || 0) >= 0;
        const warns = feedWarnings(t);
        return (
          <button
            key={t.contract}
            onClick={() => onOpen(t.contract)}
            className="card w-full text-left p-3 flex gap-3 items-center"
          >
            <div className="w-10 h-10 rounded-full bg-panel2 grid place-items-center overflow-hidden shrink-0 text-xs font-semibold">
              {t.image ? <img src={t.image} alt="" className="w-full h-full object-cover" /> : t.symbol.slice(0, 2)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="font-semibold truncate">${t.symbol}</span>
                <span className="text-[11px] text-mute uppercase">{t.chain || "sol"} · {age(t.age_h)}</span>
              </div>
              <div className="mt-1 flex gap-3 text-[12px] text-mute num">
                <span>MC {money(t.mc)}</span>
                <span>Liq {money(t.liq)}</span>
                <span className={up ? "text-gain" : "text-loss"}>{pct(t.ch_h1)} 1h</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {(t.pair_label || t.quote_symbol) && (
                  <span className="chip">{t.pair_label || `quote ${t.quote_symbol}`}</span>
                )}
                {t.price_indicative && <span className="chip text-amber">indicative</span>}
                {t.copycat_role === "copy" && <span className="chip text-loss">{t.copycat_label || "copy"}</span>}
                {t.copycat_role === "original" && t.copycat_label && <span className="chip text-cyan">{t.copycat_label}</span>}
                {typeof t.launch_group_sold_pct === "number" && t.launch_group_sold_pct >= 25 && (
                  <span className="chip text-amber">launch sold {t.launch_group_sold_pct.toFixed(0)}%</span>
                )}
                {t.dev_cashout && <span className="chip text-loss">dev cash-out</span>}
                {t.rug_memory_note && <span className="chip text-loss">rug wallet</span>}
                {warns.map((w) => (
                  <span key={w.label} className={`chip ${w.tone}`}>{w.label}</span>
                ))}
              </div>
            </div>
            <div className="flex flex-col items-center shrink-0">
              <ScoreRing score={t.score} />
              <span className="text-[10px] tracking-wider text-mute mt-0.5">{t.verdict || "—"}</span>
            </div>
          </button>
        );
      })}
      </div>
    </div>
  );
}

function feedWarnings(t: FeedToken): Array<{ label: string; tone: string }> {
  const out: Array<{ label: string; tone: string }> = [];
  if (!t.liq || t.liq <= 0) out.push({ label: "liq $0", tone: "text-loss" });
  else if (t.mc > 0 && t.mc / t.liq > 50) out.push({ label: "thin liq", tone: "text-amber" });
  const up = (t.ch_h1 != null && t.ch_h1 > 1000) || (t.ch_h24 != null && t.ch_h24 > 1000);
  const down = (t.ch_h1 != null && t.ch_h1 < -80) || (t.ch_h24 != null && t.ch_h24 < -80);
  if (up) out.push({ label: "extreme move", tone: "text-amber" });
  if (down) out.push({ label: "extreme drop", tone: "text-loss" });
  return out;
}
