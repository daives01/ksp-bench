import { formatCost, formatSeconds, modelLabel } from "@/lib/format";
import type { BenchmarkRun } from "@/types";

type TimeCostViewProps = {
  runs: BenchmarkRun[];
};

export function TimeView({ runs }: TimeCostViewProps) {
  const maxTime = Math.max(...runs.map((run) => run.time.mission_elapsed_s), 1);
  const maxActions = Math.max(...runs.map((run) => run.diagnostics.action_count), 1);

  return (
    <section className="rounded-md border border-border bg-card/80 p-4">
      <div className="mb-5">
        <h2 className="font-display text-2xl font-bold uppercase">Time</h2>
      </div>
      <div className="space-y-4">
        {runs.map((run) => (
          <div key={run.runId} className="grid gap-2 sm:grid-cols-[13rem_1fr_5rem] sm:items-center">
            <div className="min-w-0">
              <div className="truncate font-semibold">{modelLabel(run.model)}</div>
              <div className="font-mono text-[11px] text-muted-foreground">
                {run.diagnostics.action_count} actions / {run.diagnostics.invalid_actions} invalid
              </div>
            </div>
            <div className="relative h-7 rounded-sm bg-secondary">
              <div
                className="absolute inset-y-0 left-0 rounded-sm bg-sky-300/70"
                style={{ width: `${(run.time.mission_elapsed_s / maxTime) * 100}%` }}
              />
              <div
                className="absolute inset-y-1 left-0 rounded-sm bg-emerald-300"
                style={{ width: `${(run.diagnostics.action_count / maxActions) * 100}%` }}
              />
            </div>
            <div className="font-mono text-sm text-muted-foreground sm:text-right">
              {formatSeconds(run.time.mission_elapsed_s)}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap gap-3 border-t border-border/70 pt-4 font-mono text-xs uppercase text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          <span className="h-2 w-5 rounded-full bg-sky-300/70" />
          elapsed
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-2 w-5 rounded-full bg-emerald-300" />
          actions
        </span>
      </div>
    </section>
  );
}

export function CostView({ runs }: TimeCostViewProps) {
  return (
    <section className="rounded-md border border-border bg-card/80 p-4">
      <div className="mb-5">
        <h2 className="font-display text-2xl font-bold uppercase">Cost</h2>
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
