import { useEffect, useMemo, useState } from "react";
import { Activity, CircleDollarSign, Orbit } from "lucide-react";
import { Header } from "@/components/Header";
import { MetricTile } from "@/components/MetricTile";
import { OrbitView } from "@/components/OrbitView";
import { ResultsView } from "@/components/ResultsView";
import { TimeCostView } from "@/components/TimeCostView";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { loadBenchmarkData } from "@/lib/data";
import { formatMeters, formatSeconds, modelLabel } from "@/lib/format";
import type { BenchmarkDataset } from "@/types";

export default function App() {
  const [dataset, setDataset] = useState<BenchmarkDataset | null>(null);

  useEffect(() => {
    void loadBenchmarkData().then(setDataset);
  }, []);

  const runs = useMemo(() => dataset?.runs ?? [], [dataset]);
  const bestRun = runs[0];
  const stableCount = runs.filter((run) => run.diagnostics.stable_orbit).length;
  const medianTime = useMemo(() => {
    if (runs.length === 0) return 0;
    const values = runs.map((run) => run.time.mission_elapsed_s).sort((a, b) => a - b);
    return values[Math.floor(values.length / 2)];
  }, [runs]);

  if (!dataset) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="font-mono text-sm uppercase text-muted-foreground">Loading benchmark data</div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="fixed inset-0 -z-10 circuit-grid opacity-70" />
      <Header dataset={dataset} />
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <section className="grid gap-3 md:grid-cols-4">
          <MetricTile
            label="Best score"
            value={bestRun ? bestRun.score.toFixed(1) : "0.0"}
            detail={bestRun ? modelLabel(bestRun.model) : "No runs"}
            tone="green"
          />
          <MetricTile
            label="Stable orbits"
            value={`${stableCount}/${runs.length}`}
            detail="Periapsis above 70km"
            tone={stableCount > 0 ? "green" : "amber"}
          />
          <MetricTile
            label="Median MET"
            value={formatSeconds(medianTime)}
            detail="Mission elapsed time"
            tone="blue"
          />
          <MetricTile
            label="Best orbit error"
            value={bestRun ? formatMeters(bestRun.finalOrbit.orbit_error_m) : "n/a"}
            detail="Mean apo/peri target error"
            tone="neutral"
          />
        </section>

        <Tabs defaultValue="results" className="mt-6">
          <div className="flex flex-col gap-3 border-y border-border/80 py-3 sm:flex-row sm:items-center sm:justify-between">
            <TabsList>
              <TabsTrigger value="results">
                <Activity className="mr-2 h-4 w-4" />
                Results
              </TabsTrigger>
              <TabsTrigger value="time-cost">
                <CircleDollarSign className="mr-2 h-4 w-4" />
                Time & Cost
              </TabsTrigger>
              <TabsTrigger value="orbits">
                <Orbit className="mr-2 h-4 w-4" />
                Orbits
              </TabsTrigger>
            </TabsList>
            <div className="font-mono text-xs uppercase text-muted-foreground">
              {dataset.sourceRoot === "fallback" ? "fallback data" : "generated from runs/"}
            </div>
          </div>
          <TabsContent value="results">
            <ResultsView runs={runs} />
          </TabsContent>
          <TabsContent value="time-cost">
            <TimeCostView runs={runs} />
          </TabsContent>
          <TabsContent value="orbits">
            <OrbitView runs={runs} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
