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

export function price(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n >= 1) return `$${n.toFixed(4)}`;
  if (n >= 0.01) return `$${n.toFixed(6)}`;
  if (n >= 0.0001) return `$${n.toFixed(8)}`;
  return `$${n.toExponential(2)}`;
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
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
