import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { BenchmarkDataset, BenchmarkRun, TelemetrySample } from "../types";

type RawScore = {
  agent?: {
    adapter?: string;
    model?: string;
  };
  benchmark_version: string;
  diagnostics: BenchmarkRun["diagnostics"];
  final_orbit: BenchmarkRun["finalOrbit"];
  fuel_remaining: BenchmarkRun["fuelRemaining"];
  harness_version: string;
  instance_id: string;
  run_id: string;
  score: number;
  time: BenchmarkRun["time"];
};

type RawManifest = {
  created_at?: string;
};

type RawAgentProcess = {
  usage?: BenchmarkRun["usage"];
};

const repoRoot = path.resolve(import.meta.dir, "../../..");
const runsRoot = path.join(repoRoot, "runs");
const outputPath = path.join(import.meta.dir, "../../public/data/benchmark.json");

async function main() {
  const scorePaths = await findScoreFiles(runsRoot);
  const runs: BenchmarkRun[] = [];

  for (const scorePath of scorePaths) {
    const runDir = path.dirname(scorePath);
    const score = await readJson<RawScore>(scorePath);
    if (!score) continue;

    const manifest = await readJson<RawManifest>(path.join(runDir, "manifest.json"));
    const agentProcess = await readJson<RawAgentProcess>(path.join(runDir, "agent_process.json"));
    const waypoints = await readJson<{ samples?: TelemetrySample[] }>(
      path.join(runDir, "telemetry_waypoints.json"),
    );

    runs.push({
      runId: score.run_id,
      createdAt: manifest?.created_at,
      model: score.agent?.model ?? "unknown-model",
      adapter: score.agent?.adapter,
      score: score.score,
      benchmarkVersion: score.benchmark_version,
      harnessVersion: score.harness_version,
      instanceId: score.instance_id,
      finalOrbit: score.final_orbit,
      fuelRemaining: score.fuel_remaining,
      time: score.time,
      diagnostics: score.diagnostics,
      usage: agentProcess?.usage,
      telemetry: waypoints?.samples ?? [],
    });
  }

  const dataset: BenchmarkDataset = {
    generatedAt: new Date().toISOString(),
    sourceRoot: path.relative(path.dirname(outputPath), runsRoot),
    runs: runs.sort((a, b) => b.score - a.score),
  };

  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(dataset, null, 2)}\n`, "utf8");
  console.log(`Wrote ${runs.length} runs to ${path.relative(repoRoot, outputPath)}`);
}

async function readJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf8")) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function findScoreFiles(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true }).catch(() => []);
  const scoreFiles: string[] = [];

  for (const entry of entries) {
    const entryPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      scoreFiles.push(...(await findScoreFiles(entryPath)));
    } else if (entry.isFile() && entry.name === "score.json") {
      scoreFiles.push(entryPath);
    }
  }

  return scoreFiles;
}

await main();
