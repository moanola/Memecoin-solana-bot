export function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1_000_000_000) return `${sign}$${(a / 1_000_000_000).toFixed(2)}B`;
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(2)}M`;
  if (a >= 10_000) return `${sign}$${Math.round(a).toLocaleString("en-US")}`;
  if (a >= 1_000) return `${sign}$${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (a >= 1) return `${sign}$${a.toFixed(2)}`;
  return `${sign}$${a.toPrecision(3)}`;
}

export function signed(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const body = money(Math.abs(n));
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body.replace("-", "")}`;
  return body;
}

const SUB = "₀₁₂₃₄₅₆₇₈₉";

/** Token price. Tiny values use subscript zeros: 0.0000042 → $0.0₅42. */
export function price(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a === 0) return "$0";
  if (a >= 1000) return `${sign}$${a.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  if (a >= 1) return `${sign}$${a.toFixed(a >= 100 ? 2 : 4)}`;
  if (a >= 0.01) return `${sign}$${a.toFixed(4)}`;
  if (a >= 0.0001) return `${sign}$${a.toFixed(6)}`;
  const exp = Math.floor(Math.log10(a));
  const zeros = Math.abs(exp) - 1;
  const sig = (a * 10 ** (zeros + 1)).toPrecision(3).replace(".", "").replace(/e.*/, "").slice(0, 3);
  const sub = String(zeros).split("").map((d) => SUB[Number(d)] || d).join("");
  return `${sign}$0.0${sub}${sig}`;
}

/** Axis label. Same precision as price(), without a glyph the canvas font may not draw. */
export function priceAxis(n: number): string {
  return price(n).replace("$", "");
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function holdTime(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours) || hours < 0) return "—";
  const mins = Math.max(0, Math.round(hours * 60));
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

const EXIT_REASONS: Record<string, string> = {
  manual: "Manual",
  exit_tp: "Take profit",
  exit_invalidation: "Invalidation",
  exit_time_stop: "Time stop",
  stop_loss: "Stop loss",
  auto_sell: "Auto sell",
  limit_sell: "Limit sell",
  apex_trail_exit: "Trail stop",
  apex_threat_red: "Threat exit",
  apex_threat_orange: "Threat exit",
  apex_momentum_decay: "Momentum fade",
};

export function exitReason(reason: string | null | undefined): string {
  if (!reason) return "Manual";
  if (EXIT_REASONS[reason]) return EXIT_REASONS[reason];
  return reason.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function positionPnl(pnl: number, pnlNet?: number | null): number {
  return pnlNet == null || Number.isNaN(pnlNet) ? pnl : pnlNet;
}

export function age(hours: number | null | undefined): string {
  if (hours == null) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m`;
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
  return `${Math.round(hours / 24)}d`;
}

export function clsx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
