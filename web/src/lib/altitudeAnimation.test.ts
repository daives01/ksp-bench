import { describe, expect, test } from "bun:test";
import { altitudeAnimationDelay } from "./altitudeAnimation";

describe("altitude trace animation", () => {
  test("animates the recorded and projected segments together", () => {
    expect(altitudeAnimationDelay(0)).toBe("0ms");
    expect(altitudeAnimationDelay(3)).toBe("270ms");
  });
});
