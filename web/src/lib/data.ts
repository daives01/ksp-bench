import type { BenchmarkDataset, FlightTrace } from "@/types";

export async function loadBenchmarkData(): Promise<BenchmarkDataset> {
  try {
    const response = await fetch("/data/index.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`data request failed: ${response.status}`);
    const dataset = (await response.json()) as BenchmarkDataset;
    if (!Array.isArray(dataset.runs)) {
      throw new Error("benchmark data did not include a runs array");
    }
    return {
      ...dataset,
      runs: rankRuns(dataset.runs),
    };
  } catch {
    return { generatedAt: "", sourceRoot: "", runs: [] };
  }
}

export function rankRuns(runs: BenchmarkDataset["runs"]) {
  return [...runs].sort((a, b) => b.score - a.score);
}

export async function loadFlightTrace(url: string): Promise<FlightTrace> {
  const response = await fetch(url, { cache: "force-cache" });
  if (!response.ok) throw new Error(`flight request failed: ${response.status}`);
  const flight = (await response.json()) as {
    schema_version?: number;
    interval_s?: number;
    columns?: string[];
    points?: Array<Array<number | null>>;
  };
  if (!Array.isArray(flight.columns) || !Array.isArray(flight.points)) {
    throw new Error("flight data is invalid");
  }
  return {
    schemaVersion: flight.schema_version,
    intervalS: flight.interval_s,
    columns: flight.columns,
    points: flight.points,
  };
}
