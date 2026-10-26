/** The URL is the state: which keys ride from one link to the next. */
import { describe, expect, it } from "vitest";

import { TABLE_KEYS, WINDOW_KEYS, nextParams, windowPatch, withQuery } from "./url";

const q = (s: string) => new URLSearchParams(s);

describe("nextParams", () => {
  it("carries the window and the view switches, never a page-only key", () => {
    const next = nextParams(q("from=2026-01-01&to=2026-01-31&grain=day&stack=bucket&page=3&q=coop"), {});
    expect(next.toString()).toBe("from=2026-01-01&to=2026-01-31&grain=day&stack=bucket");
  });

  it("drops the preset when dates are given, and the dates when a preset is", () => {
    expect(nextParams(q("preset=12m&grain=month"), { from: "2025-05-01", to: "2025-05-31" }).toString())
      .toBe("grain=month&from=2025-05-01&to=2025-05-31");
    expect(nextParams(q("from=2025-05-01&to=2025-05-31&grain=day"), { preset: "all" }).toString())
      .toBe("grain=day&preset=all");
  });

  it("removes a key set to null or empty", () => {
    expect(nextParams(q("from=2026-01-01&focus=ibkr"), { focus: null }).toString()).toBe("from=2026-01-01");
    expect(nextParams(q("from=2026-01-01&focus=ibkr"), { focus: "" }).toString()).toBe("from=2026-01-01");
  });

  it("keeps only what it is told to: the table's filters stay in the table", () => {
    const current = q("from=2026-01-01&q=coop&category=Alimentation&stack=bucket");
    expect(nextParams(current, {}, WINDOW_KEYS).toString()).toBe("from=2026-01-01");
    expect(nextParams(current, {}, [...WINDOW_KEYS, ...TABLE_KEYS]).toString())
      .toBe("from=2026-01-01&q=coop&category=Alimentation");
  });
});

describe("links", () => {
  it("leave no lone question mark", () => {
    expect(withQuery("/epargne", q(""))).toBe("/epargne");
    expect(withQuery("/epargne", q("focus=ibkr"))).toBe("/epargne?focus=ibkr");
  });

  it("a window lets the server pick its grain and clears the preset", () => {
    const next = nextParams(q("preset=all"), windowPatch("2026-03-01", "2026-03-31"));
    expect(next.toString()).toBe("from=2026-03-01&to=2026-03-31&grain=auto");
  });
});
