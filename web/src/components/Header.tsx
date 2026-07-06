import { Rocket, Satellite } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { BenchmarkDataset } from "@/types";

type HeaderProps = {
  dataset: BenchmarkDataset;
};

export function Header({ dataset }: HeaderProps) {
  const generated = new Date(dataset.generatedAt);

  return (
    <header className="border-b border-border/80 bg-background/80">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-2 font-mono text-xs uppercase text-muted-foreground">
              <Satellite className="h-4 w-4 text-sky-300" />
              Data / Kerbin Orbit 80km
            </div>
            <h1 className="font-display text-5xl font-black uppercase leading-none text-foreground sm:text-7xl">
              KSP BENCH
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">v0 orbital flight</Badge>
            <Badge variant="success">{dataset.runs.length} runs</Badge>
            <Badge variant="outline">updated {Number.isNaN(generated.valueOf()) ? "unknown" : generated.toLocaleDateString()}</Badge>
          </div>
        </div>
        <div className="grid gap-3 border-t border-border/60 pt-4 text-sm text-muted-foreground md:grid-cols-[1fr_auto]">
          <p className="max-w-3xl">
            Agent benchmark results for flying a fixed Kerbal 1 launch vehicle into a stable
            low-Kerbin orbit. Scores reward ascent milestones, orbit quality, and remaining fuel.
          </p>
          <div className="flex items-center gap-2 font-mono text-xs uppercase text-muted-foreground">
            <Rocket className="h-4 w-4 text-emerald-300" />
            Cloudflare Workers target
          </div>
        </div>
      </div>
    </header>
  );
}
