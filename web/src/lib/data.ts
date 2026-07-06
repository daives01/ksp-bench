import fallbackDataset from "@/data/fallbackBenchmark";
import type { BenchmarkDataset } from "@/types";

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
      runs: rankRuns(dataset.runs),
    };
  } catch {
    return fallbackDataset;
  }
}

export function rankRuns(runs: BenchmarkDataset["runs"]) {
  return [...runs].sort((a, b) => b.score - a.score);
}
