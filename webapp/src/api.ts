import { initData } from "./telegram";
import type {
  ApexStatus,
  BoardRow,
  Candle,
  ExitPlan,
  FeedToken,
  MarketMood,
  Me,
  Position,
  Tick,
  TokenDetail,
  Trade,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const SESSION_KEY = "apex_session";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function formatDetail(detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const row = item as { loc?: unknown; msg?: unknown; message?: unknown };
        const loc = Array.isArray(row.loc)
          ? row.loc.filter((part) => part !== "body" && part !== "query").join(".")
          : "";
        const msg = String(row.msg || row.message || "").replace(/^Value error,\s*/i, "");
        if (msg && loc) return `${loc}: ${msg}`;
        return msg || loc;
      }
      return "";
    }).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object" && "msg" in detail) {
    return String((detail as { msg: unknown }).msg || "");
  }
  return "";
}

export function sessionToken(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

export function setSession(token: string | null): void {
  if (token) localStorage.setItem(SESSION_KEY, token);
  else localStorage.removeItem(SESSION_KEY);
}

export function hasCredential(): boolean {
  return Boolean(initData() || sessionToken());
}

function authHeader(): Record<string, string> {
  const data = initData();
  if (data) return { Authorization: `tma ${data}` };
  const session = sessionToken();
  if (session) return { Authorization: `Bearer ${session}` };
  return {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...authHeader(),
        ...(init?.headers || {}),
      },
    });
  } catch {
    throw new ApiError(0, "Can't reach the API. Check VITE_API_BASE.");
  }
  const text = await res.text();
  let data: { detail?: unknown } = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {};
    }
  }
  if (!res.ok) {
    const detail = data.detail;
    const msg = formatDetail(detail) || `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  me: () => request<Me>("/api/me"),
  positions: () => request<{ positions: Position[]; unrealized_pnl: number }>("/api/positions"),
  history: () => request<{ trades: Trade[] }>("/api/history"),
  feed: (refresh = false) => request<{ tokens: FeedToken[] }>(`/api/feed?refresh=${refresh ? "true" : "false"}`),
  token: (contract: string) => request<TokenDetail>(`/api/tokens/${encodeURIComponent(contract)}`),
  candles: (contract: string) =>
    request<{ candles: Candle[]; source: string }>(`/api/tokens/${encodeURIComponent(contract)}/candles`),
  buy: (contract: string, amount_usd: number, plan?: Partial<ExitPlan> & { preset?: string }) =>
    request<{ symbol: string; tokens: number; price: number; fee: number; balance: number; exit_plan?: ExitPlan }>(
      "/api/trade/buy",
      { method: "POST", body: JSON.stringify({ contract, amount_usd, ...(plan || {}) }) },
    ),
  mood: () => request<{ mood: MarketMood | null; discipline: { breaks: number; break_cost: number; overrides: number; break_pnl?: number }; presets: Record<string, ExitPlan> }>("/api/mood"),
  sell: (contract: string, percent: number) =>
    request<{ symbol: string; received: number; realized: number; closed: boolean; balance: number }>(
      "/api/trade/sell",
      { method: "POST", body: JSON.stringify({ contract, percent }) },
    ),
  apex: () => request<ApexStatus>("/api/apex"),
  apexToggle: (enabled: boolean) =>
    request<ApexStatus>("/api/apex/toggle", { method: "POST", body: JSON.stringify({ enabled }) }),
  vault: (action: "fund" | "withdraw", amount: number) =>
    request<ApexStatus>("/api/apex/vault", {
      method: "POST",
      body: JSON.stringify({ action, amount }),
    }),
  split: (percent: number) =>
    request<ApexStatus>("/api/apex/split", { method: "POST", body: JSON.stringify({ percent }) }),
  board: (sort: "equity" | "pnl" | "wr") =>
    request<{ rows: BoardRow[]; my_rank: number | null }>(`/api/leaderboard?sort=${sort}`),
  login: (payload: Record<string, unknown>) =>
    request<{ token: string; user: Me }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export function wsUrl(): string {
  const base = BASE || window.location.origin;
  const url = new URL("/api/ws", base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function openTicks(onTick: (tick: Tick) => void, onClose: () => void): () => void {
  const socket = new WebSocket(wsUrl());
  let stopped = false;
  socket.onopen = () => {
    const data = initData();
    if (data) socket.send(JSON.stringify({ initData: data }));
    else if (sessionToken()) socket.send(JSON.stringify({ token: sessionToken() }));
    else socket.close();
  };
  socket.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data) as Tick;
      if (msg.type === "tick") onTick(msg);
    } catch {
      /* ignore malformed frames */
    }
  };
  socket.onclose = () => {
    if (!stopped) onClose();
  };
  return () => {
    stopped = true;
    socket.close();
  };
}
