import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { money, signed } from "../format";
import type { BoardRow } from "../types";

const SORTS = [
  { id: "equity", label: "Equity" },
  { id: "pnl", label: "PnL" },
  { id: "wr", label: "Win%" },
] as const;

export function Board() {
  const [sort, setSort] = useState<(typeof SORTS)[number]["id"]>("equity");
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.board(sort)
      .then((res) => setRows(res.rows))
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Leaderboard unavailable"));
  }, [sort]);

  return (
    <div className="space-y-3">
      <div>
        <div className="text-[11px] tracking-[0.18em] uppercase text-mute">Global</div>
        <h1 className="text-xl font-semibold">Leaderboard</h1>
        <p className="text-[11px] text-mute mt-1">Equity includes cash, live position values, and the APEX vault. PnL includes partial sells that are still open.</p>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {SORTS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSort(s.id)}
            className={`rounded-full py-1 text-xs uppercase tracking-wider border ${sort === s.id ? "border-cyan text-cyan" : "border-line text-mute"}`}
          >
            {s.label}
          </button>
        ))}
      </div>
      {error && <div className="text-sm text-loss">{error}</div>}
      {rows.length === 0 && !error && <div className="card p-5 text-sm text-mute">No closed trades yet.</div>}
      {rows.map((r) => (
        <div key={r.rank} className={`card p-3 flex items-center gap-3 ${r.is_me ? "border-cyan" : ""}`}>
          <div className="num w-6 text-mute">{r.rank}</div>
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate">@{r.username}{r.is_me ? " · you" : ""}</div>
            <div className="text-xs text-mute num">{r.trades} trades · {r.win_rate}% · streak {r.streak}</div>
          </div>
          <div className="text-right">
            <div className="num text-sm">{money(r.equity)}</div>
            <div className={r.pnl >= 0 ? "text-gain num text-xs" : "text-loss num text-xs"}>{signed(r.pnl)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
