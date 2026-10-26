/** The forecast payload (`/api/previsions`) and the one way to edit the plan. */
import { useMemo } from "react";

import { ApiError, send, useApi } from "./api";
import { useView } from "./url";

/** The keys the forecast page keeps from one view to the next. */
export const PREVISIONS_KEEP = ["months", "wealth", "scale", "yscale", "split", "swr"] as const;
// The split is drawn from what the page already has: not asked of the server.
const SERVER = PREVISIONS_KEEP.filter((k) => k !== "split");

/** The forecast for the address shown -- one cache entry, read by the page
 * and by the pickers in the top bar alike. */
export function usePrevisions() {
  const { params } = useView();
  const query = useMemo(() => {
    const p = new URLSearchParams();
    SERVER.forEach((k) => { const v = params.get(k); if (v) p.set(k, v); });
    return p.toString();
  }, [params]);
  return useApi<Previsions>("/api/previsions", query);
}

/** Asks the scenarios panel to open its "new scenario" sheet -- from the
 * top bar, which does not hold it. */
export const NEW_SCENARIO_EVENT = "pms:new-scenario";

/** Unfolds a panel of the page and brings it into view. */
export function openSection(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.dispatchEvent(new Event("section:open"));
  setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
}

export interface OneOff { label: string; amount: number; date: string; source: string; transfer: string; every?: string; months?: number }
export interface MonthRow {
  key: string; label: string; start: number; income: number; spend: number; end: number;
  partial: boolean; one_offs: OneOff[];
}
export interface Low { amount: number; key: string | null; label: string }

export interface Freedom {
  wealth: number; spend: number; spend_months: number; years_covered: number; years_label: string;
  withdrawal: number; rates: number[]; target: number; progress: number; monthly: number;
  declared: boolean; months: number | null; months_flat: number | null;
  wait: string | null; wait_flat: string | null; date: string | null; date_flat: string | null;
  what_ifs: { label: string; months: number | null; wait: string | null; sooner: number | null; sooner_label: string | null }[];
}

export interface Previsions {
  empty?: boolean;
  freedom: Freedom | null;
  as_of: string;
  months: number;
  horizon_label: string;
  horizons: { id: number; label: string }[];
  projection: {
    cash: number; income: number; income_source: string; baseline: number; baseline_history: number;
    baseline_source: string; low: Low; months: number; rows: MonthRow[]; margin: number;
  };
  wealth: null | {
    invested: number; start: number; change: number; rate: number | null; rated: boolean; vol: number; vol_source: string;
    vol_measured: number | null;
    moved: number; include_cash: boolean; pocket: string | null;
    observed: { total: number; label: string }[];
    rows: { key: string; label: string; cash: number; invested: number; total: number; low: number; high: number; moved: number }[];
    final: { total: number; low: number; high: number; label: string };
    parts: WealthParts;
    pockets_rates: PocketRates[];
  };
  wealth_observed: number;
  wealth_view: string;
  wealth_views: { id: string; label: string; title: string; note: string }[];
  scale: string;
  yscale: string;
  yscales: { id: string; label: string }[];
  profile: { month: number; label: string; short: string; raw_median: number; stripped_median: number; seasonal_median: number; years: number[]; iqr: number; seasonal: { category: string; amount: number }[] }[];
  comparison: {
    name: string | null; active: boolean; slot: number | null; income: number; spend: number; spend_source: string;
    low: Low; end: number; moved: number; wealth: number | null; delta_low: number | null; delta_wealth: number | null;
    line: number[];
  }[];
  active: string | null;
  plan: {
    income: number | null; spend: number | null; vol: number | null;
    rate_segments: [number, number][];
    rate_years: RateYear[];
    declared: { month: string; label: string; amount: number; date: string; transfer: string; seasonal: unknown }[];
    contributions: { pocket: string; amount: number; every: string; months: number; start: string; every_label: string; start_label: string }[];
    ignored: { category: string; month: number; label: string }[];
    scenarios: ({ name: string; summary: string } & Market)[];
  };
  suggestions: { category: string; month: number; month_label: string; amount: number; years: number[]; target: string }[];
  builtin_scenarios: ({ key: string; label: string; note: string; pockets: { id: string; label: string; rate: number; vol: number }[] } & Market)[];
  growth: GrowthPath;
  destinations: { id: string; label: string }[];
  every_options: { id: string; label: string }[];
  pockets: { id: string; label: string }[];
}

/** One way of splitting the net worth: its layers, measured then projected. */
export interface Split {
  series: { key: string; name: string; slot: number | null }[];
  observed: Record<string, number>[];
  projected: Record<string, number>[];
}
/** The net worth by pocket and by asset class, and what each piece brings
 * from today to the horizon (`views.previsions._parts`). */
export interface WealthParts {
  pockets: Split;
  classes: Split;
  table: { key: string; name: string; slot: number; start: number; paid: number; growth: number; end: number }[];
  flows: { key: string; label: string; amount: number; slot: number | null; pocket?: string }[];
  start: number; end: number; moved: number; rated: boolean; own: string[];
}

/** One calendar year of the horizon under a barème (`plans.rate_years`):
 * `rate` null when the year straddles two periods, or nothing is declared. */
export interface RateYear { year: number; months: number; rate: number | null; mixed: boolean }
/** A pocket in the rate panel: its own barème, or the common one it follows. */
export interface PocketRates {
  id: string; label: string; slot: number; value: number; own: boolean; fixed_by_default: boolean;
  rate_segments: [number, number][]; rate_years: RateYear[];
  vol: number | null; vol_effective: number | null; vol_measured: number | null;
  growth: GrowthPath; summary: string;
}

/** What a barème does to one franc placed today (`plans.growth_path`). */
export interface GrowthPath { months: number; points: number[]; end: number; low: number; low_month: number; annual: number | null }
/** A market scenario as its card shows it. */
export interface Market {
  segments: { months: number; rate: number }[]; vol: number | null; months: number | null; path: GrowthPath;
}

export type FieldErrors = Record<string, string>;

/** One edit to the plan. Resolves to the errors by field when refused
 * (nothing saved), to `{}` when applied. */
export async function planAction(
  months: number, body: Record<string, unknown>,
): Promise<{ errors?: FieldErrors; months?: number | null }> {
  try {
    const r = await send<{ ok: boolean; months: number | null }>(`/api/previsions?months=${months}`, body);
    return { months: r.months };
  } catch (e) {
    if (e instanceof ApiError && e.data && typeof e.data === "object" && "errors" in e.data) {
      return { errors: (e.data as { errors: FieldErrors }).errors };
    }
    throw e;
  }
}
