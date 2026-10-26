/** The app's voice for numbers and dates. */
import { describe, expect, it } from "vitest";

import { chf, compact, frDate, monthLabel, plural, signedChf, signedRate } from "./format";

describe("chf", () => {
  it("groups thousands with the Swiss apostrophe and keeps the decimal point", () => {
    expect(chf(12345.67)).toBe("12’345.67");
    expect(chf(813)).toBe("813.00");
    expect(chf(1234567, 0)).toBe("1’234’567");
  });

  it("writes a typographic minus, and never a minus zero", () => {
    expect(chf(-1550)).toBe("−1’550.00");
    expect(chf(-0.3, 0)).toBe("0");
  });

  it("says nothing rather than NaN", () => {
    expect(chf(Number.NaN)).toBe("—");
    expect(chf(null)).toBe("—");
  });
});

describe("signed figures", () => {
  it("always carry their sign", () => {
    expect(signedChf(4256.66)).toBe("+4’257");
    expect(signedChf(-2)).toBe("−2");
    expect(signedRate(0.0889)).toBe("+8.9 %");
    expect(signedRate(-0.118)).toBe("−11.8 %");
    expect(signedRate(0.00001)).toBe("0.0 %");
  });
});

describe("axis ticks", () => {
  it("shorten large amounts", () => {
    expect(compact(15000)).toBe("15k");
    expect(compact(2500)).toBe("2.5k");
    expect(compact(1_250_000)).toBe("1.3M");
    expect(compact(500)).toBe("500");
  });
});

describe("dates", () => {
  it("read the Swiss way", () => {
    expect(frDate("2026-10-14")).toBe("14.10.2026");
    expect(monthLabel("2026-10")).toBe("octobre 2026");
  });
});

describe("plural", () => {
  it("agrees with its count", () => {
    expect(plural(1, "mouvement")).toBe("1 mouvement");
    expect(plural(2, "mouvement")).toBe("2 mouvements");
    expect(plural(0, "mouvement")).toBe("0 mouvement");
  });
});
