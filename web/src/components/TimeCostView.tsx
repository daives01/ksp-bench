import { formatCost, formatSeconds, modelLabel } from "@/lib/format";
import type { BenchmarkRun } from "@/types";

type TimeCostViewProps = {
  runs: BenchmarkRun[];
};

export function TimeView({ runs }: TimeCostViewProps) {
  const elapsed = (run: BenchmarkRun) => run.time.wall_clock_elapsed_s ?? run.time.mission_elapsed_s;
  const rankedRuns = [...runs].sort((a, b) => elapsed(a) - elapsed(b));
  const maxTime = Math.max(...rankedRuns.map(elapsed), 1);
  const topColors = ["hsl(var(--safety-green))", "hsl(var(--electric-blue))", "hsl(var(--hazard-orange))"];

  return (
    <section className="rounded-md border border-border bg-card/80 p-4">
      <div className="mb-5">
        <h2 className="font-display text-2xl font-bold uppercase">Time</h2>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
          Harness wall-clock time; legacy runs fall back to KSP MET
        </p>
      </div>
      <div className="space-y-px">
        {rankedRuns.map((run, index) => {
          const highlight = index < 3;
          const fillColor = highlight ? topColors[index] : "hsl(var(--muted-foreground) / 0.5)";
          const textColor = highlight ? "text-foreground" : "text-muted-foreground";
          const rankColor = highlight ? { color: fillColor } : undefined;

          return (
            <div key={run.runId}>
              <div className="group relative flex items-center gap-3 rounded-sm px-2 py-2.5 transition-colors hover:bg-white/[0.04] sm:px-4">
                <span
                  className={`w-7 shrink-0 text-right font-mono text-[11px] font-bold leading-none tabular-nums ${highlight ? "" : "text-muted-foreground/60"}`}
                  style={rankColor}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
                  <div className="min-w-0 shrink-0 sm:w-52">
                    <div className={`truncate font-mono text-[13px] font-semibold leading-none ${textColor}`}>
                      {modelLabel(run.model)}
                    </div>
                    <div className="mt-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                      {run.diagnostics.action_count} actions / {run.diagnostics.invalid_actions} invalid
                    </div>
                  </div>
                  <div className="min-w-6 flex-1 overflow-hidden rounded-full bg-white/[0.04]">
                    <div
                      className="bar-fill h-[6px] rounded-full"
                      style={{
                        width: `${(elapsed(run) / maxTime) * 100}%`,
                        backgroundColor: fillColor,
                        animationDelay: `${index * 35}ms`,
                        boxShadow: highlight ? `0 0 8px ${fillColor}` : undefined,
                      }}
                    />
                  </div>
                </div>
                <span className={`w-16 shrink-0 text-right font-mono text-[13px] font-bold leading-none tabular-nums ${textColor}`}>
                  {formatSeconds(elapsed(run))}
                </span>
              </div>
              {index === 2 ? <div className="mx-4 my-1.5 border-t border-dashed border-white/[0.06]" /> : null}
            </div>
          );
        })}
      </div>
      <div className="mt-5 flex flex-wrap gap-3 border-t border-border/70 pt-4 font-mono text-xs uppercase text-muted-foreground">
        <span>Ranked fastest to slowest</span>
        <span>Lower is better</span>
        <span>{rankedRuns.length} runs</span>
      </div>
    </section>
  );
}

export function CostView({ runs }: TimeCostViewProps) {
  return (
    <section className="rounded-md border border-border bg-card/80 p-4">
      <div className="mb-5">
        <h2 className="font-display text-2xl font-bold uppercase">API-equivalent cost</h2>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          OpenAI or comparable OpenRouter list price — not subscription billing
        </p>
      </div>
      <div className="space-y-3">
        {runs.map((run) => (
          <div
            key={run.runId}
            className="grid grid-cols-[1fr_auto] gap-3 rounded-md border border-border/70 bg-background/40 p-3"
          >
            <div className="min-w-0">
              <div className="truncate font-semibold">{modelLabel(run.model)}</div>
              <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                {run.usage?.total_tokens == null
                  ? "tokens n/a"
                  : `${run.usage.total_tokens.toLocaleString()} tokens`}
                {run.usage?.cached_input_tokens
                  ? ` · ${run.usage.cached_input_tokens.toLocaleString()} cached`
                  : ""}
                {run.usage?.pricing_source ? ` · ${run.usage.pricing_source}` : ""}
              </div>
            </div>
            <div className="font-display text-xl font-bold">
              {formatCost(run.usage?.cost_usd)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
