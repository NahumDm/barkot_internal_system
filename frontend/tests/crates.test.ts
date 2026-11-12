/**
 * Tests for the crate ↔ bottle wording (the bar's beers).
 *
 * The bar receives stock by the crate and sells it by the bottle, and 1 crate
 * holds 24 bottles. Every screen that shows a beer goes through these helpers,
 * so the cases that matter are a whole crate, a part crate, and a product that
 * is not counted in crates at all.
 */

import { describe, expect, it } from "vitest";

import { crateLabel, crateSize, parseBottles, splitCrates } from "@/lib/crates";

describe("crateSize", () => {
  it("reads a usable crate size off the product", () => {
    expect(crateSize({ bottles_per_crate: 24 })).toBe(24);
  });

  it("treats a missing or too-small size as 'not crated'", () => {
    expect(crateSize({ bottles_per_crate: null })).toBeNull();
    expect(crateSize({ bottles_per_crate: 1 })).toBeNull();
    expect(crateSize(undefined)).toBeNull();
  });
});

describe("splitCrates", () => {
  it("splits whole crates from loose bottles", () => {
    expect(splitCrates(72, 24)).toEqual({ crates: 3, loose: 0 });
    expect(splitCrates(75, 24)).toEqual({ crates: 3, loose: 3 });
    expect(splitCrates(5, 24)).toEqual({ crates: 0, loose: 5 });
  });
});

describe("crateLabel", () => {
  it("names whole crates", () => {
    expect(crateLabel(72, 24)).toBe("3 crates");
    expect(crateLabel(24, 24)).toBe("1 crate");
  });

  it("names a part crate as crates plus loose bottles", () => {
    expect(crateLabel(75, 24)).toBe("3 crates + 3 bottles");
    expect(crateLabel(25, 24)).toBe("1 crate + 1 bottle");
  });

  it("falls back to bottles when there is not a full crate", () => {
    expect(crateLabel(5, 24)).toBe("5 bottles");
    expect(crateLabel(1, 24)).toBe("1 bottle");
  });
});

describe("parseBottles", () => {
  it("reads the API's decimal string", () => {
    expect(parseBottles("240.000")).toBe(240);
    expect(parseBottles("0.000")).toBe(0);
  });

  it("returns null for a missing or unparseable value", () => {
    expect(parseBottles(null)).toBeNull();
    expect(parseBottles("")).toBeNull();
    expect(parseBottles("not-a-number")).toBeNull();
  });
});
