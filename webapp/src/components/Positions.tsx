import { useState } from "react";
import { exitReason, holdTime, money, pct, positionPnl, signed } from "../format";
import type { Position, Trade } from "../types";

export function Positions({
  rows,
  unrealized,
  trades,
  onOpen,
}: {
  rows: Position[];
  unrealized: number;
  trades: Trade[];
  onOpen: (contract: string) => void;
}) {
  const [tab, setTab] = useState<"open" | "closed">("open");
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] tracking-[0.18em] uppercase text-mute">Book</div>
          <h1 className="text-xl font-semibold">Positions</h1>
        </div>
        <div className={unrealized >= 0 ? "text-gain num" : "text-loss num"}>{signed(unrealized)}</div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button onClick={() => setTab("open")} className={`rounded-full py-1 text-xs uppercase tracking-wider border ${tab === "open" ? "border-cyan text-cyan" : "border-line text-mute"}`}>Open</button>
        <button onClick={() => setTab("closed")} className={`rounded-full py-1 text-xs uppercase tracking-wider border ${tab === "closed" ? "border-cyan text-cyan" : "border-line text-mute"}`}>History</button>
      </div>
      {tab === "open" && rows.length === 0 && (
        <div className="card p-5 text-sm text-mute">No open paper positions. Buy from the feed.</div>
      )}
      <div className={tab === "open" ? "space-y-3 lg:grid lg:grid-cols-2 lg:gap-3 lg:space-y-0" : "space-y-3"}>
      {tab === "open" && rows.map((p) => {
        const pnl = positionPnl(p.pnl, p.pnl_net);
        return (
        <button key={p.contract} onClick={() => onOpen(p.contract)} className="card w-full text-left p-3">
          <div className="flex justify-between items-baseline">
            <span className="font-semibold">${p.symbol}</span>
            <span className={pnl >= 0 ? "text-gain num" : "text-loss num"}>{signed(pnl)}</span>
          </div>
          <div className="mt-1 flex justify-between text-xs text-mute num">
            <span>{p.x.toFixed(2)}x · {pct(p.pnl_pct)}</span>
            <span>{money(p.value)}{p.price_live ? "" : " · delayed"}</span>
          </div>
          {p.mood && <div className="text-[10px] uppercase tracking-wider text-mute mt-1">{p.mood}</div>}
          {p.exit_plan && (
            <div className="text-[10px] text-cyan mt-1 num">
              Exit {p.exit_plan.preset} · {p.exit_plan.tp_x}×
              {p.exit_plan.tp_pct < 1 ? ` · ${Math.round(p.exit_plan.tp_pct * 100)}%` : ""}
              {" "}· −{p.exit_plan.invalidation_pct}% · {p.exit_plan.time_stop_min}m
            </div>
          )}
          {p.apex_exit?.rules && (
            <div className="text-[10px] text-cyan mt-1">
              {p.apex_exit.rules.slice(0, 3).join(" · ")}
            </div>
          )}
        </button>
        );
      })}
      </div>
      {tab === "closed" && trades.length === 0 && (
        <div className="card p-5 text-sm text-mute">No closed trades yet.</div>
      )}
      {tab === "closed" && trades.map((t, i) => (
        <div key={`${t.contract}-${t.closed_at}-${i}`} className="card p-3">
          <div className="flex justify-between">
            <span className="font-semibold">${t.symbol}</span>
            <span className={t.realized_pnl >= 0 ? "text-gain num" : "text-loss num"}>{signed(t.realized_pnl)}</span>
          </div>
          <div className="text-xs text-mute num mt-1">
            {(t.x ?? 0).toFixed(2)}x · {holdTime(t.hold_h)} · {exitReason(t.reason)}
            {t.fees_paid ? ` · fees ${money(t.fees_paid)}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
