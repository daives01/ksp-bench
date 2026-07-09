import fallbackDataset from "@/data/fallbackBenchmark";
import type { BenchmarkDataset, BenchmarkRun, FlightTrace } from "@/types";

export async function loadBenchmarkData(): Promise<BenchmarkDataset> {
  try {
    const response = await fetch("/data/benchmark.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`data request failed: ${response.status}`);
    const dataset = (await response.json()) as BenchmarkDataset;
    if (!Array.isArray(dataset.runs) || dataset.runs.length === 0) {
      throw new Error("benchmark data did not include runs");
    }
    return {
      ...dataset,
      runs: rankRuns(dataset.runs.map(normalizeRun)),
    };
  } catch {
    return { ...fallbackDataset, runs: rankRuns(fallbackDataset.runs.map(normalizeRun)) };
  }
}

function normalizeRun(run: BenchmarkRun): BenchmarkRun {
  return { ...run, flight: run.flight ?? legacyTrace(run.telemetry) };
}

function legacyTrace(samples: BenchmarkRun["telemetry"]): FlightTrace {
  return {
    schemaVersion: 0,
    intervalS: 10,
    columns: ["t", "alt", "apo", "peri", "lat", "lon", "speed", "stage", "fuel", "q"],
    points: samples.map((sample) => [
      sample.mission_elapsed_s,
      sample.altitude_m,
      sample.apoapsis_m,
      sample.periapsis_m,
      sample.latitude_deg ?? null,
      sample.longitude_deg ?? null,
      sample.orbital_speed_m_s,
      sample.stage ?? null,
      sample.liquid_fuel == null ? null : sample.liquid_fuel + (sample.oxidizer ?? 0) + (sample.solid_fuel ?? 0),
      sample.dynamic_pressure_pa ?? null,
    ]),
  };
}

export function rankRuns(runs: BenchmarkDataset["runs"]) {
  return [...runs].sort((a, b) => b.score - a.score);
}
