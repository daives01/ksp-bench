import type { BenchmarkDataset } from "@/types";

// The dashboard intentionally starts empty. Sample flights make it too easy
// to mistake placeholder data for a benchmark result.
const fallbackDataset: BenchmarkDataset = {
  generatedAt: "",
  sourceRoot: "fallback",
  benchmarkVersion: "0.1.0",
  runs: [],
};

export default fallbackDataset;
