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

export interface ExitPlan {
  preset: string;
  tp_x: number;
  tp_pct: number;
  invalidation_pct: number;
  time_stop_min: number;
}

export interface MarketMood {
  label: string;
  score: number;
  size_mult: number;
  heat_scale: number;
  fees_usd: number | null;
  volume_usd: number | null;
  share_7d_pct: number | null;
  day: string | null;
  source: string;
  attribution: string;
  paper: boolean;
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
  pair_label?: string;
  quote_symbol?: string;
  quote_kind?: string;
  price_indicative?: boolean;
  copycat_role?: string;
  copycat_label?: string;
  launch_group_sold_pct?: number | null;
  launch_group_size?: number | null;
  dev_cashout?: boolean;
  rug_memory_note?: string;
  helius?: boolean;
  holders_per_hour?: number | null;
  holder_retention_pct?: number | null;
  kol_exit_note?: string;
  fee_sweep?: boolean;
  multi_hop_txs?: number | null;
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
  position: {
    amount: number;
    cost: number;
    value: number;
    pnl: number;
    pnl_net?: number;
    entry_fees?: number;
    avg_price: number;
    mood?: string;
    exit_plan?: ExitPlan | null;
    apex_exit?: { rules: string[]; stop_loss_pct?: number | null; trail_activate_x?: number } | null;
  } | null;
  dev_cashout_reason?: string;
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
  pnl_net?: number;
  entry_fees?: number;
  pnl_pct: number;
  x: number;
  mood: string;
  exit_plan?: ExitPlan | null;
  apex_exit?: { rules: string[] } | null;
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
  deployed?: number;
  positions: number;
  trades: number;
  wins: number;
  win_rate: number | null;
  consec_losses: number;
  phase: string;
  balance: number | null;
  buy_amount: number;
  mood?: MarketMood | null;
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
