import { useEffect, useMemo, useState } from "react";
import { Activity, CircleDollarSign, Clock, Orbit } from "lucide-react";
import { Header } from "@/components/Header";
import { OrbitView } from "@/components/OrbitView";
import { ResultsView } from "@/components/ResultsView";
import { CostView, TimeView } from "@/components/TimeCostView";
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
      <div className="fixed inset-0 -z-10 circuit-grid opacity-70" />
      <Tabs defaultValue="kerbin-80">
        <Header>
          <TabsList>
            <TabsTrigger value="kerbin-80">80 km orbit</TabsTrigger>
          </TabsList>
        </Header>

        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <TabsContent value="kerbin-80">
            <Tabs defaultValue="results">
              <div className="border-y border-border/80 py-3">
                <TabsList>
                  <TabsTrigger value="results">
                    <Activity className="mr-2 h-4 w-4" />
                    Results
                  </TabsTrigger>
                  <TabsTrigger value="time">
                    <Clock className="mr-2 h-4 w-4" />
                    Time
                  </TabsTrigger>
                  <TabsTrigger value="cost">
                    <CircleDollarSign className="mr-2 h-4 w-4" />
                    Cost
                  </TabsTrigger>
                  <TabsTrigger value="orbits">
                    <Orbit className="mr-2 h-4 w-4" />
                    Orbits
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="results">
                <ResultsView runs={runs} />
              </TabsContent>
              <TabsContent value="time">
                <TimeView runs={runs} />
              </TabsContent>
              <TabsContent value="cost">
                <CostView runs={runs} />
              </TabsContent>
              <TabsContent value="orbits">
                <OrbitView runs={runs} />
              </TabsContent>
            </Tabs>
          </TabsContent>
        </main>
      </Tabs>
    </div>
  );
}
