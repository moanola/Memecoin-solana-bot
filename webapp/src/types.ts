export interface Me {
  paper: boolean;
  uid: number;
  username: string;
  balance: number | null;
  balance_set: boolean;
  savings: number;
  starting_balance: number | null;
  realized_pnl: number;
  total_fees_paid: number;
  open_cost: number;
  equity: number | null;
  apex_vault: number;
  open_positions: number;
  quick_buy_amount: number;
}

export interface Rug {
  no_mint: boolean | null;
  no_freeze: boolean | null;
  lp_burn: number | null;
  top10_pct: number | null;
  insider_pct: number | null;
  risks: string[];
  rate_limited: boolean;
}

export interface FeedToken {
  contract: string;
  symbol: string;
  name: string;
  chain: string;
  price: number;
  mc: number;
  liq: number;
  ch_m5: number;
  ch_h1: number;
  ch_h24: number;
  age_h: number | null;
  score: number;
  verdict: string;
  image: string;
  flags: string[];
}

export interface AiVerdict {
  verdict: string | null;
  confidence: number | null;
  suggested_amount: number | null;
  thesis: string;
  red_flags: string[];
  green_flags: string[];
  rug_risk: string | null;
  momentum: string | null;
  social_score: string | null;
}

export interface TokenDetail extends FeedToken {
  dex: string;
  vol_h1: number;
  vol_h24: number;
  buy_pct: number | null;
  warnings: string[];
  strengths: string[];
  rug: Rug;
  ai?: AiVerdict;
  position: { amount: number; cost: number; value: number; pnl: number; avg_price: number } | null;
  slippage: { sample_usd: number; slippage_pct: number; cost_usd: number } | null;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Position {
  contract: string;
  symbol: string;
  name: string;
  chain: string;
  amount: number;
  avg_price: number;
  price: number;
  price_live: boolean;
  value: number;
  cost: number;
  pnl: number;
  pnl_pct: number;
  x: number;
  mood: string;
  mc: number;
  liq: number;
}

export interface Trade {
  symbol: string;
  contract: string;
  realized_pnl: number;
  x: number;
  hold_h: number;
  reason: string;
  mood: string;
  closed_at: string | null;
  invested: number;
  returned: number;
}

export interface ApexStatus {
  enabled: boolean;
  state: string;
  paused: boolean;
  halted: boolean;
  vault: number;
  vault_pnl: number;
  profit_split: number;
  profit_sent: number;
  daily_pnl: number;
  heat_pct: number;
  positions: number;
  trades: number;
  wins: number;
  win_rate: number;
  consec_losses: number;
  phase: string;
  balance: number | null;
  buy_amount: number;
}

export interface BoardRow {
  rank: number;
  username: string;
  equity: number;
  pnl: number;
  win_rate: number;
  trades: number;
  growth: number;
  streak: number;
  is_me: boolean;
}

export interface Tick {
  type: string;
  balance: number | null;
  vault: number;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Position[];
  apex_enabled: boolean;
  ts: number;
}
