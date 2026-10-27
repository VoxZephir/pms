/** The savings payload (`/api/savings`). */
import type { Period } from "./types";

export interface Fee { amount: number; detail: string; pct: number | null; items: { date: string; label: string; amount: number }[] }

export interface PocketRow {
  pocket: "total" | "swissquote" | "ibkr" | "finpension" | "crypto" | "titres";
  name: string;
  start_value: number;
  value: number;
  change: number;
  put_in: number;
  gain: number;
  share: number | null;
  contribution: number | null;
  twr: number | null; mwr: number | null;
  twr_annual: number | null; mwr_annual: number | null;
  twr_pa: number | null; mwr_pa: number | null;
  timing: number | null; timing_pa: number | null; timing_chf: number | null;
  fees: Fee | null;
}

export type PocketKey = PocketRow["pocket"];

export interface MonthlyReturns {
  pocket: PocketKey; name: string; since: string | null;
  years: { year: number; months: (number | null)[]; partial: boolean[]; rate: number | null }[];
  best: { year: number; month: number; rate: number } | null;
  worst: { year: number; month: number; rate: number } | null;
  up: number; count: number;
}

export interface Drawdown {
  pocket: PocketKey; name: string; since: string | null;
  rows: { date: string; dd: number }[];
  worst: null | { depth: number; peak: string; trough: string; recovered: string | null; days: number };
  current: number;
}

export interface SavingsReads {
  slots: Partial<Record<PocketKey, number>>;
  bridge: { start: number; end: number; steps: { key: string; label: string; amount: number }[] };
  sparks: Partial<Record<PocketKey, number[]>>;
  months: Partial<Record<PocketKey, MonthlyReturns>>;
  drawdowns: Partial<Record<PocketKey, Drawdown>>;
}

export interface Savings {
  titres: { declared: number; counted: boolean; value: number; name: string };
  reads: SavingsReads;
  empty?: boolean;
  available: boolean;
  period: Period;
  focus: string; split: string; scale: string; perf: "twr" | "mwr"; rate: "period" | "annual";
  total: number;
  swissquote_chf: number; nav_chf: number; finp_chf: number;
  captured_at: string | null; captured_on: string | null;
  opened: string | null; reconstructed_until: string | null; journal_source: string | null;
  finpension: null | { value: number; value_as_of: string; deposits: number; fees: number; first: string };
  finp_as_of: string | null;
  stale: string[];
  parts: { name: string; value: number }[];
  fees: Record<string, Fee>;
  pockets: PocketRow[];
  hero: PocketRow;
  positions: { name: string; value: number; exposure: number; asset_class: string; currency: string; pnl: number; pnl_pct: number }[];
  crypto: null | {
    as_of: string;
    positions: { symbol: string; quantity: number; price_chf: number | null; value_chf: number | null; cost_chf: number;
      rewards: null | { quantity: number; count: number; yield: number | null; calibrated: boolean; ambiguous: number } }[];
    value_chf: number; cost_chf: number;
    calibration: Record<string, number> | null;
    sent: { day: string; symbol: string; quantity: number; value_chf: number }[];
    unread: string[];
  };
  reserve: null | { months: number; monthly: number; basis: number; low: number; high: number; excess: number; short: number };
  pillar3a: null | { year: number; paid: number; ceiling: number; left: number; days_left: number | null; published: boolean; gaps: { year: number; amount: number }[];
    buyback: { open: number; bought: number; room: number; cap: number } };
  allocation: {
    classes: string[];
    targets: Record<string, number>;
    current: Record<string, number>;
    drift: null | {
      rows: { name: string; value: number; share: number; target: number; gap: number }[];
      buy: { name: string; gap: number }[];
      sell: { name: string; gap: number }[];
      total: number;
    };
    exposure: null | { gross: number; rows: { name: string; share: number; value: number }[]; by_name: Record<string, { share: number }> };
  };
  tax: null | {
    years: { year: number; day: string; partial: boolean; taxable: number; dividends: number; interest: number; withheld: number;
      pillar3a_paid: number | null; pillar3a_value: number | null; ceiling_3a: number;
      rows: { name: string; value: number | null; detail: string }[] }[];
    rows: { name: string; cells: (null | { value: number | null; detail: string })[] }[];
  };
  bench: { name: string; rate: number; rate_pa: number | null; since: string | null; source: string; total_return: boolean }[];
  bench_options: { key: string; name: string; on: boolean; available: boolean; source: string }[];
  risk: null | { columns: string[]; rows: { label: string; why: string; cells: { text: string }[] }[]; points: number; yearly: boolean; mode: "annual" | "period"; extrapolated: boolean; cash_share: number | null };
  attribution: null | { fund_name: string; fund: number; fx: number; rest: number; total: number };
  invested: null | {
    rows: { date: string; contributed: number; value: number }[];
    pockets: string[]; contributed: number; value: number; gain: number; gain_pct: number | null;
  };
  evolution: { spec: { key: string; name: string; slot: number; dash?: boolean }[]; rows: Record<string, number | string | null>[]; unit: string };
  options: {
    splits: { id: string; label: string }[];
    scales: { id: string; label: string; title: string }[];
    perfs: { id: string; label: string; title: string }[];
    rates: { id: string; label: string; title: string }[];
    stats: { id: string; label: string; title: string }[];
    focuses: { id: string; label: string }[];
  };
}
