/** Axis arithmetic shared by every chart. */

/** Round axis bounds and the step between ticks: [bottom, top, step].
 *
 * The step is 1, 2, 2.5 or 5 x 10^k, picked among those giving `min`..`max`
 * intervals for the one that wastes the least plot height -- the rule
 * `charts.axis_scale` used server-side. `zero` keeps the bottom at 0 (bars
 * and amounts stand for what they are). */
export function axisScale(
  lo: number, hi: number, { zero = true, min = 3, max = 5 } = {},
): [number, number, number] {
  if (zero) lo = Math.min(0, lo);
  if (!(hi > lo)) hi = lo + 1;
  const span = hi - lo;
  let best: [number, number, number, number, number] | null = null;
  const exponent = Math.floor(Math.log10(span)) - 1;
  for (let k = exponent; k < exponent + 3; k++) {
    for (const mantissa of [1, 2, 2.5, 5]) {
      const step = mantissa * 10 ** k;
      const bottom = zero && lo >= 0 ? 0 : Math.floor(lo / step) * step;
      const top = Math.ceil(hi / step) * step;
      const intervals = Math.round((top - bottom) / step);
      if (intervals < min || intervals > max) continue;
      const waste = top - bottom - span;
      if (!best || waste < best[0] || (waste === best[0] && intervals < best[1])) {
        best = [waste, intervals, bottom, top, step];
      }
    }
  }
  if (!best) return [lo, hi, span / 2];
  return [best[2], best[3], best[4]];
}

export function ticks(bottom: number, top: number, step: number): number[] {
  const out: number[] = [];
  const n = Math.round((top - bottom) / step);
  for (let i = 0; i <= n; i++) out.push(Number((bottom + step * i).toFixed(9)));
  return out;
}

/** Show at most one label per `minGap` pixels, so they never collide. */
export function labelEvery(count: number, width: number, minGap = 52): number {
  if (count <= 0) return 1;
  return Math.max(1, Math.ceil(count / Math.max(1, Math.floor(width / minGap))));
}

/** Quantile cuts for a sequential ramp: daily spending is heavily skewed
 * (a rent payment is 100x a coffee), so equal widths would put every
 * ordinary day in the lightest bin. */
export function quantileCuts(values: number[], qs = [0.25, 0.5, 0.75, 0.92]): number[] {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (!sorted.length) return [];
  return qs.map((q) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))]);
}

export function levelOf(amount: number, cuts: number[]): number {
  if (amount <= 0 || !cuts.length) return 0;
  for (let i = 0; i < cuts.length; i++) if (amount <= cuts[i]) return i + 1;
  return 5;
}
