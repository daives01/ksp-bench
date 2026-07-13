import { describe, expect, test } from "bun:test";
import type { BenchmarkRun } from "@/types";
import { projectedAltitude } from "./trajectory";

function run(overrides: Partial<BenchmarkRun> = {}): BenchmarkRun {
  return {
    diagnostics: { stable_orbit: true },
    finalOrbit: {
      apoapsis_m: 90_000,
      periapsis_m: 80_000,
      time_to_apoapsis_s: 200,
    },
    ...overrides,
  } as BenchmarkRun;
}

describe("altitude projection horizon", () => {
  test("repeats an orbital projection through the shared chart end", () => {
    const points = [{ t: 0, alt: 80_000 }, { t: 10, alt: 82_000 }];

    const projected = projectedAltitude(run(), points, 7_200);

    expect(projected.at(-1)?.t).toBe(7_200);
    expect(projected.length).toBeGreaterThan(121);
  });

  test("holds a ballistic projection at ground level through the shared chart end", () => {
    const points = [{ t: 0, alt: 1_000 }, { t: 10, alt: 900 }];
    const ballisticRun = run({
      diagnostics: { stable_orbit: false } as BenchmarkRun["diagnostics"],
    });

    const projected = projectedAltitude(ballisticRun, points, 600);

    expect(projected.at(-1)).toEqual({ t: 600, alt: 0 });
  });
});
