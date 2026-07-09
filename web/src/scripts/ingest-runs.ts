import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { BenchmarkDataset, BenchmarkRun, FlightTrace, TelemetrySample } from "../types";

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

type RawFlight = {
  schema_version?: number;
  interval_s?: number;
  columns?: string[];
  points?: Array<Array<number | null>>;
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
    const flight = await readJson<RawFlight>(path.join(runDir, "flight.json"));
    const waypoints = await readJson<{ samples?: TelemetrySample[] }>(path.join(runDir, "telemetry_waypoints.json"));

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
      flight: normalizeFlight(flight, waypoints?.samples ?? []),
      telemetry: [],
    });
  }

  const bestRuns = bestRunByModel(runs);
  const existingDataset = await readJson<BenchmarkDataset>(outputPath);
  const mergedRuns = mergeBestRuns(existingDataset?.runs ?? [], bestRuns);

  const dataset: BenchmarkDataset = {
    generatedAt: new Date().toISOString(),
    sourceRoot: path.relative(path.dirname(outputPath), runsRoot),
    runs: mergedRuns.sort(compareRuns),
  };

  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(dataset, null, 2)}\n`, "utf8");
  console.log(
    `Wrote ${mergedRuns.length} best-of-model runs from ${runs.length} local runs to ${path.relative(
      repoRoot,
      outputPath,
    )}`,
  );
}

function normalizeFlight(raw: RawFlight | null, legacy: TelemetrySample[]): FlightTrace {
  if (raw?.columns && raw.points) {
    return { schemaVersion: raw.schema_version, intervalS: raw.interval_s, columns: raw.columns, points: raw.points };
  }
  return {
    schemaVersion: 0,
    intervalS: 10,
    columns: ["t", "alt", "apo", "peri", "lat", "lon", "speed", "stage", "fuel", "q"],
    points: legacy.map((sample) => [sample.mission_elapsed_s, sample.altitude_m, sample.apoapsis_m, sample.periapsis_m, sample.latitude_deg ?? null, sample.longitude_deg ?? null, sample.orbital_speed_m_s, sample.stage ?? null, null, null]),
  };
}

function bestRunByModel(runs: BenchmarkRun[]): BenchmarkRun[] {
  const bestByModel = new Map<string, BenchmarkRun>();

  for (const run of runs) {
    const previous = bestByModel.get(run.model);
    if (!previous || compareRuns(run, previous) < 0) {
      bestByModel.set(run.model, run);
    }
  }

  return [...bestByModel.values()];
}

function mergeBestRuns(existingRuns: BenchmarkRun[], localBestRuns: BenchmarkRun[]): BenchmarkRun[] {
  const mergedByModel = new Map<string, BenchmarkRun>();

  for (const run of existingRuns) {
    const previous = mergedByModel.get(run.model);
    if (!previous || compareRuns(run, previous) < 0) {
      mergedByModel.set(run.model, run);
    }
  }

  for (const run of localBestRuns) {
    const previous = mergedByModel.get(run.model);
    if (!previous || compareRuns(run, previous) < 0) {
      mergedByModel.set(run.model, run);
    }
  }

  return [...mergedByModel.values()];
}

function compareRuns(a: BenchmarkRun, b: BenchmarkRun): number {
  const scoreDelta = b.score - a.score;
  if (scoreDelta !== 0) return scoreDelta;

  const aCreated = Date.parse(a.createdAt ?? "");
  const bCreated = Date.parse(b.createdAt ?? "");
  const createdDelta =
    (Number.isNaN(bCreated) ? 0 : bCreated) - (Number.isNaN(aCreated) ? 0 : aCreated);
  if (createdDelta !== 0) return createdDelta;

  return a.runId.localeCompare(b.runId);
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
