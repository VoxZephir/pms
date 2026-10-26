import { describe, expect, it } from "vitest";

import type { Split } from "@/lib/previsions";
import { stacked, tipParts } from "./Parts";

const split: Split = {
  series: [{ key: "cash", name: "Cash", slot: 0 }, { key: "actions", name: "Actions", slot: 2 }],
  observed: [{ cash: 10, actions: 5 }, { cash: 12, actions: 6 }],
  projected: [{ cash: 11, actions: 8 }],
};

describe("stacked", () => {
  it("lays each layer on the one under it, measured then projected from today", () => {
    const s = stacked(split, 2)!;
    const actionsSeen = s.find((x) => x.key === "actions:seen")!;
    const actionsAhead = s.find((x) => x.key === "actions:ahead")!;
    expect(actionsSeen.values).toEqual([15, 18, null]);
    expect(actionsSeen.fillTo).toEqual([10, 12, null]);
    // Today's point is shared: the projected layer starts where the measured ends.
    expect(actionsAhead.values).toEqual([null, 18, 19]);
    expect(actionsAhead.dash).toBe(true);
  });

  it("refuses a layer below zero rather than drawing a stack that lies", () => {
    expect(stacked({ ...split, projected: [{ cash: -3, actions: 8 }] }, 2)).toBeNull();
  });

  it("reads each layer's own value in the tooltip, largest first", () => {
    expect(tipParts(split, 2, 2).map((r) => r.name)).toEqual(["Cash", "Actions"]);
    expect(tipParts(split, 2, 2)[1].value).toBe("8 CHF");
  });
});
