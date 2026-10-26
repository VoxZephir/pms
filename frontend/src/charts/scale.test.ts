/** The axis arithmetic every chart shares. These were the Python tests of
 * the chart geometry when it was drawn server-side. */
import { describe, expect, it } from "vitest";

import { axisScale, labelEvery, levelOf, quantileCuts, ticks } from "./scale";

describe("axisScale", () => {
  it("wastes little height on round ticks", () => {
    // 62'000 of data used to sit on a 100'000 axis: a third of it empty.
    expect(axisScale(0, 62426, { zero: true, min: 3, max: 6 })).toEqual([0, 75000, 25000]);
  });

  it("fits base 100 on a quiet window with three to six round ticks", () => {
    const [bottom, top, step] = axisScale(97.2, 118.4, { zero: false, min: 3, max: 6 });
    expect(bottom).toBeLessThanOrEqual(97.2);
    expect(top).toBeGreaterThanOrEqual(118.4);
    expect(top - 118.4).toBeLessThan(step);
    expect(97.2 - bottom).toBeLessThan(step);
    const intervals = Math.round((top - bottom) / step);
    expect(intervals).toBeGreaterThanOrEqual(3);
    expect(intervals).toBeLessThanOrEqual(6);
  });

  it("covers the data whatever its scale", () => {
    for (const [lo, hi] of [[0, 13.1], [0, 1234567], [12000, 12900]] as const) {
      const [bottom, top, step] = axisScale(lo, hi, { zero: lo === 0, min: 3, max: 6 });
      expect(bottom).toBeLessThanOrEqual(lo);
      expect(top).toBeGreaterThanOrEqual(hi);
      const intervals = Math.round((top - bottom) / step);
      expect(intervals).toBeGreaterThanOrEqual(3);
      expect(intervals).toBeLessThanOrEqual(6);
    }
  });

  it("anchors amounts at zero", () => {
    expect(axisScale(30000, 46000, { zero: true })[0]).toBe(0);
  });

  it("survives a flat series", () => {
    const [bottom, top] = axisScale(5, 5);
    expect(top).toBeGreaterThan(bottom);
  });
});

describe("ticks", () => {
  it("steps from bottom to top without floating dust", () => {
    expect(ticks(0, 0.3, 0.1)).toEqual([0, 0.1, 0.2, 0.3]);
  });
});

describe("labelEvery", () => {
  it("keeps labels apart however many columns", () => {
    expect(labelEvery(12, 1000)).toBe(1);
    expect(labelEvery(365, 340)).toBeGreaterThan(50);
  });
});

describe("the calendar ramp", () => {
  it("cuts on quantiles, so ordinary days are not all in the lightest bin", () => {
    const days = [...Array.from({ length: 90 }, (_, i) => 10 + i), 1500, 2000];
    const cuts = quantileCuts(days);
    expect(cuts).toHaveLength(4);
    expect(levelOf(15, cuts)).toBe(1);
    expect(levelOf(2000, cuts)).toBe(5);
  });

  it("leaves a day without spending at level zero, drawn hollow", () => {
    expect(levelOf(0, quantileCuts([5, 10, 20]))).toBe(0);
    expect(quantileCuts([])).toEqual([]);
  });
});
