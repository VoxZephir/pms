/** The shapes the Flask API returns (`src/pms/web/api/`). Dates are ISO strings. */

import type { Deadline, Due, Horizon } from "@/pages/upcoming/types";

export interface Tx {
  key: string;
  date: string;
  seq: number;
  label: string;
  merchant: string;
  location: string;
  kind: string;
  detail: string[];
  category: string;
  subcategory: string;
  bucket: string;
  amount: number;
  currency: string;
  chf: number;
  account: string;
  overridden: boolean;
}

export interface Crumb { label: string; start: string; end: string; current: boolean }
export interface Preset { id: string; group: string; label: string; start: string; end: string; active: boolean }
export interface PresetGroup { name: string; buttons: Preset[] }
export interface Neighbour { start: string; end: string; available: boolean }

export interface Period {
  start: string;
  end: string;
  grain: Grain;
  auto_grain: boolean;
  title: string;
  days: number;
  crumbs: Crumb[];
  presets: Preset[];
  preset_groups: PresetGroup[];
  is_full: boolean;
  neighbours: null | {
    label: string;
    prev: Neighbour;
    next: Neighbour;
    prev_label: string;
    next_label: string;
  };
  grains: { id: Grain; label: string }[];
  bounds: { low: string; high: string };
}

export type Grain = "year" | "semester" | "quarter" | "month" | "week" | "day";

export interface Meta {
  empty: boolean;
  ledger: string;
  bounds: { low: string; high: string };
  movements: number;
  gaps: { after: string; before: string }[];
  news: null | { id: string; added: number; when: string; until: string; start: string; end: string; label: string };
  late: { bank: string; until: string; days: number; url: string }[];
  watching: boolean;
  backup: { title: string; detail: string } | null;
  /** The forecast goes under the owner's cash floor: the alert, else null. */
  floor: FloorAlert | null;
  overrides: number;
  crypto: boolean;
  /** The pocket's name when holdings are declared, else null. */
  titres: string | null;
  savings: boolean;
}

export interface CategoryRow {
  category: string;
  amount: number;
  share: number;
  count: number;
  average: number;
  slot: number;
  subcategories: { name: string; amount: number; count: number }[];
  top_merchants: { name: string; amount: number; count: number }[];
}

export interface SeriesRow {
  key: string;
  label: string;
  start: string;
  end: string;
  spending: number;
  income: number;
  net: number;
  count: number;
  categories: Record<string, number>;
  buckets: Record<string, number>;
}

export interface BucketPart { name: string; amount: number; share: number; count: number; hollow: boolean }
export interface BucketRow { name: string; amount: number; share: number; count: number; parts: BucketPart[] }
export interface Buckets {
  rows: BucketRow[];
  basis: "income" | "spend";
  base: number;
  income: number;
  overspend: number;
  residual: number;
  transferred_to_savings: number;
}

export interface Merchant {
  name: string;
  amount: number;
  count: number;
  average: number;
  median: number;
  category: string;
  mixed: boolean;
  category_share: number;
  categories: number;
}

export interface Dashboard {
  empty?: boolean;
  period: Period;
  previous: { start: string; end: string; exists: boolean; label: string };
  versus: { category: string; now: number; before: number; delta: number; slot: number }[];
  pace: null | {
    day: number; days: number; done: boolean; spent: number; values: number[];
    median: number[]; low: number[]; high: number[];
    ordinary_now: number; ordinary_end: number; vs_ordinary: number; projected: number;
    span: { label: string }; months: number;
    budgets: { category: string; budget: number; spent: number; pace: number; share: number | null }[];
  };
  soon: null | {
    deadlines: Deadline[];
    next: Due[];
    month: Horizon;
  };
  count: number;
  kpis: {
    spend: number; earn: number; net: number; per_day: number; median_day: number; closing: number;
    previous: null | { spend: number; earn: number; per_day: number; median_day: number };
  };
  panels: Record<string, boolean>;
  categories: CategoryRow[];
  legend: { name: string; slot: number }[];
  timeline: { rows: SeriesRow[]; drill: string | null; hint: string; stack: "category" | "bucket"; stacks: { id: string; label: string }[];
    median: null | { amount: number; periods: number; partial: number } };
  bucket_order: string[];
  bucket_fill: Record<string, string>;
  buckets: Buckets;
  custodian: Custodian;
  top_merchants: Merchant[];
  daily: Record<string, [number, number]>;
  review: Review | null;
  highlights: { label: string; value: string; detail: string }[];
  income: null | {
    payers: number;
    slots: Record<string, number>;
    table: { label: string; slot: number; amount: number; share: number; count: number; first: string; last: string; folded?: boolean }[];
    rows: { key: string; label: string; start: string; end: string; total: number; sources: Record<string, number> }[];
  };
  missing: { label: string; category: string; last: string; expected: string; average: number; interval: number; gap: number; ended: boolean }[];
  fixed: null | {
    months: { month: string; fixed: number; variable: number }[];
    monthly_floor: number;
    fixed_share: number;
    commitment_count: number;
    commitments: { label: string; category: string; months: number; average: number; total: number }[];
  };
  monthly: { name: string; slot: number; total: number; median: number; budget: number | null; months: { key: string; label: string; amount: number }[] }[];
  balance: [string, number][];
  years: { year: number; total: number; first_day: number; last_day: number; points: [number, number][] }[];
  weekday: { day: string; amount: number; count: number }[];
  season: { month: number; average: number; years: number }[];
  geo: { rows: { country: string; amount: number; count: number; share: number }[]; total?: number; uncovered?: number };
  shares: {
    base: string; smooth: number;
    rows: { key: string; label: string; raw: Record<string, number | null>; smooth: Record<string, number | null> }[];
    names: string[];
    bases: { id: string; label: string }[];
    smoothings: number[];
    targets: Record<string, number>;
  };
  uncategorised: number;
  categories_present: string[];
  today: string;
}

export interface Custodian {
  count: number;
  markup_chf: number;
  effective_pct: number;
  volume_chf: number;
  median_markup_pct: number;
  interest_chf: number;
  explicit_fees_chf: number;
  total_chf: number;
  by_currency: { currency: string; markup_chf: number; markup_pct: number; volume_chf: number; count: number }[];
  conversions: {
    date: string; currency: string; foreign_amount: number; reference_chf: number;
    charged_chf: number; markup_chf: number; markup_pct: number; rate?: number;
  }[];
  references: { name: string; rate: number; would_cost: number; saved: number; note: string; as_of?: string }[];
  references_as_of: string;
}

export interface Review {
  label: string;
  first: string;
  last: string;
  partial: boolean;
  history_months: number;
  spent: number;
  median: number;
  delta_pct: number | null;
  prices: { label: string; before: number; now: number; currency: string; delta: number; pct: number }[];
  new_payees: { label: string; amount: number }[];
  duplicates: { label: string; amount: number; dates: string[] }[];
  categories: { category: string; amount: number; habit: number; seasonal: boolean }[];
}

export interface TxPage {
  period: Period;
  rows: Tx[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
  debit_total: number;
  credit_total: number;
  categories: string[];
  /** The accounts the window's rows come from, named by their bank; a filter only when more than one. */
  accounts: { id: string; label: string }[];
  slots: Record<string, number>;
  summary: TxSummary;
  query: Record<string, string>;
}

/** The filtered rows in brief (`api/transactions.summary`). */
export interface TxSummary {
  count: number; out_count: number; out: number; in: number; net: number; median: number | null;
  parts: { name: string; amount: number; share: number; slot: number | null; rest?: number }[];
  grain: string;
  series: { key: string; label: string; out: number; in: number }[];
  payees: { name: string; amount: number; count: number }[];
  internal: number;
}

export interface Choices {
  categories: string[];
  subcategories: Record<string, string[]>;
  buckets: string[];
}

export interface FloorAlert {
  floor: number; below: boolean; months: number; count?: number;
  first?: { key: string; label: string; amount: number };
  low?: { key: string; label: string; amount: number };
  text?: string;
}

/** The tax still owed, estimated from the rate paid on a whole past year
 * (`taxes.provision`); with `planned`/`uncovered` in Prévisions
 * (`plans.tax_cover`). */
export interface TaxProvision {
  basis: { year: number; tax: number; pay: number; rate: number; paid_in: number };
  years: { year: number; pay: number; pay_so_far: number; pay_estimated: boolean; estimated: number;
           paid: number; paid_in: number; later: boolean; outstanding: number }[];
  outstanding: number; as_of: string;
  planned?: number; until?: string; uncovered?: number;
}
