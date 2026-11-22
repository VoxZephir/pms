import { describe, expect, it } from "vitest";

import { isStaleBuild } from "./stale";

describe("isStaleBuild", () => {
  it("reads a chunk gone with a new build, in each browser's words", () => {
    expect(isStaleBuild(new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:5000/static/spa/assets/Taxes-DDDi6SMu.js"))).toBe(true);
    expect(isStaleBuild(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isStaleBuild(new TypeError("error loading dynamically imported module"))).toBe(true);
  });

  it("leaves every other error alone", () => {
    expect(isStaleBuild(new Error("Cannot read properties of undefined"))).toBe(false);
    expect(isStaleBuild(null)).toBe(false);
  });
});
