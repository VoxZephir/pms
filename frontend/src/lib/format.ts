/** Swiss number formatting, French dates -- the voice of the whole app. */

export const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
  "août", "septembre", "octobre", "novembre", "décembre",
];
export const MONTHS_SHORT = [
  "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
  "août", "sept.", "oct.", "nov.", "déc.",
];
export const WEEKDAYS_SHORT = ["L", "M", "M", "J", "V", "S", "D"];

const THIN = "’";

/** 12’345.67 -- the apostrophe the Python side prints (`analysis.chf`). */
export function chf(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  const fixed = Math.abs(value).toFixed(decimals);
  const [int, frac] = fixed.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  // −0 after rounding prints as 0, never as a red minus zero.
  if (sign && Number(fixed) === 0) return frac ? `${grouped}.${frac}` : grouped;
  return sign + (frac ? `${grouped}.${frac}` : grouped);
}

/** +1’234 / −56: a change, always signed. */
export function signedChf(value: number | null | undefined, decimals = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const rounded = Number(value.toFixed(decimals));
  return (rounded > 0 ? "+" : "") + chf(value, decimals);
}

/** A compact amount for axis ticks: 12k, 1.2M. */
export function compact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e6) return `${sign}${trim(abs / 1e6)}M`;
  if (abs >= 1e4) return `${sign}${trim(abs / 1e3, 0)}k`;
  if (abs >= 1e3) return `${sign}${trim(abs / 1e3)}k`;
  return chf(value, 0);
}

function trim(v: number, digits = 1): string {
  return v.toFixed(digits).replace(/\.0$/, "");
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)} %`;
}

/** A rate given as a fraction (0.034), printed signed as a percentage. */
export function signedRate(rate: number | null | undefined, digits = 1): string {
  if (rate == null || !Number.isFinite(rate)) return "—";
  const v = rate * 100;
  const fixed = v.toFixed(digits);
  if (Number(fixed) === 0) return `${(0).toFixed(digits)} %`;
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)} %`;
}

/** A date from the API ("2026-10-14"), read as a local calendar day. */
export function day(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function iso(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 14.10.2026 */
export function frDate(value: string | null | undefined): string {
  if (!value) return "";
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** 14 oct. 2026 */
export function frDay(value: string, withYear = true): string {
  const date = day(value);
  const base = `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]}`;
  return withYear ? `${base} ${date.getFullYear()}` : base;
}

/** mardi 14 octobre 2026 */
export function frLongDay(value: string): string {
  return day(value).toLocaleDateString("fr-CH", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

/** "2026-10" -> "octobre 2026" */
export function monthLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count > 1 ? many : one}`;
}

/** The buckets keep their English names in the data (Need, Want, Save) --
 * they are keys, in URLs and in the corrections file. The screen speaks
 * French. */
const BUCKET_LABELS: Record<string, string> = { Need: "Besoins", Want: "Envies", Save: "Épargne" };
export function bucketLabel(name: string): string {
  return BUCKET_LABELS[name] ?? name;
}
