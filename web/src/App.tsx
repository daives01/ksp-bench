import { useEffect, useMemo, useState } from "react";
import { Activity, Clock, Github, Heart, Orbit, Rocket, Trophy } from "lucide-react";
import { Header } from "@/components/Header";
import { ResultsView } from "@/components/ResultsView";
import { TimeView } from "@/components/TimeCostView";
import { OrbitView } from "@/components/OrbitView";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { loadBenchmarkData } from "@/lib/data";
import type { BenchmarkDataset } from "@/types";

export default function App() {
  const [dataset, setDataset] = useState<BenchmarkDataset | null>(null);

  useEffect(() => {
    void loadBenchmarkData().then(setDataset);
  }, []);

  const runs = useMemo(() => dataset?.runs ?? [], [dataset]);

  if (!dataset) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="font-mono text-sm uppercase text-muted-foreground">Loading benchmark data</div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="fixed inset-0 -z-10 orbital-backdrop" />
      <Header
        actions={
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" size="icon">
              <a
                href="https://github.com/daives01/ksp-bench"
                target="_blank"
                rel="noreferrer"
                aria-label="View daives01/ksp-bench on GitHub"
              >
                <Github className="h-4 w-4" />
              </a>
            </Button>
            <Button asChild variant="ghost" size="icon">
              <a
                href="https://buymeacoffee.com/danielives"
                target="_blank"
                rel="noreferrer"
                aria-label="Support Daniel Ives on Buy Me a Coffee"
              >
                <Heart className="h-4 w-4" />
              </a>
            </Button>
          </div>
        }
      >
        <p className="mission-label">MISSION 01 / KERBIN → 80 KM ORBIT</p>
      </Header>

      <main className="mx-auto w-full max-w-[92rem] px-4 py-5 sm:px-6 lg:px-8">
        <section className="mission-brief">
          <div><p className="eyebrow"><Rocket size={13} /> Autonomous flight benchmark</p><h2>Which model can fly the cleanest climb?</h2><p>Same rocket. Same launchpad. Every decision is recorded from ignition to final orbit.</p></div>
          <div className="brief-stats"><span><Trophy size={15} /> <b>{runs[0]?.score.toFixed(1) ?? "—"}</b><small>best score</small></span><span><Orbit size={15} /> <b>{runs.filter((run) => run.diagnostics.stable_orbit).length}</b><small>orbits achieved</small></span></div>
        </section>
        <Tabs defaultValue="results">
          <div className="bench-tabs">
            <TabsList className="w-full justify-start">
              <TabsTrigger value="results">
                <Activity className="mr-2 h-4 w-4" />
                Results
              </TabsTrigger>
              <TabsTrigger value="time">
                <Clock className="mr-2 h-4 w-4" />
                Time
              </TabsTrigger>
              <TabsTrigger value="orbits">
                <Orbit className="mr-2 h-4 w-4" />
                Flights
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="results">
            <ResultsView runs={runs} />
          </TabsContent>
          <TabsContent value="time">
            <TimeView runs={runs} />
          </TabsContent>
          <TabsContent value="orbits"><OrbitView runs={runs} /></TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
