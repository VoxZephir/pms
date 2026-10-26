/** The `/api/analyse` payload. */
import type { ProfileMonth } from "@/components/MonthlyProfile";

export type Kind = "regular" | "variable" | "occasional" | "seasonal";

export interface CategoryRow {
  category: string; median: number; peak: number; peak_month: number; peak_month_label: string;
  trend: number | null; seasonal: null | { month: number; month_label: string; amount: number; years: number[] };
  slot: number | null; spark: number[]; share: number; months_with: number; months: number; kind: Kind;
}

export interface Span { from: string; to: string; label: string }

export interface Change {
  months: number; last: Span; before: Span;
  rows: { category: string; now: number; before: number; delta: number; pct: number | null }[];
  total: { now: number; before: number; delta: number; pct: number | null };
}

export interface Drill {
  category: string; median: number;
  rows: { key: string; label: string; amount: number }[];
  months: number; total_year: number; mean: number; max: number; max_month: string | null; count_year: number;
  merchants: { name: string; amount: number; count: number; median: number; share: number; last: string }[];
  years: { year: number; months: (number | null)[] }[];
}

export interface Rhythm {
  months: number; span: Span; median: number[]; low: number[]; high: number[]; half_day: number | null;
  current: null | { month: string; label: string; values: number[]; day: number; whole: boolean; vs_median: number };
}

export interface Weekdays {
  rows: { day: string; amount: number; count: number; per_day: number }[];
  weekend: number; week: number;
}

export interface Inflation {
  pct: number; yearly_before: number; yearly_now: number; delta: number; count: number;
  rows: { label: string; category: string; subcategory: string; before: number; now: number;
          yearly_before: number; yearly_now: number; pct: number; contribution: number }[];
  cpi: { month: string | null; pct: number | null; yearly: { year: number; pct: number }[];
         monthly: { month: string; pct: number }[]; source: string; url: string;
         latest: string; fetched: string | null };
}

export interface Households {
  months: number; first: string; last: string; size: number; source: string; url: string;
  rows: { label: string; mine: number; household: number; person: number; vs_person: number | null }[];
}

export interface Analyse {
  empty?: boolean;
  inflation: Inflation | null;
  households: Households | null;
  as_of: string;
  baseline: number;
  profile: ProfileMonth[];
  year: string;
  years: { id: string; label: string }[];
  categories: CategoryRow[];
  drill: Drill | null;
  headline: {
    months: number; spending: number | null; income: number | null; saving_rate: number | null;
    year: Change["total"] | null; year_months: number | null;
  };
  change: Change | null;
  rhythm: Rhythm | null;
  weekdays: Weekdays | null;
  whole_months: number;
}
