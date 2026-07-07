import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMeters, formatSeconds, modelLabel } from "@/lib/format";
import type { BenchmarkRun } from "@/types";

type ResultsViewProps = {
  runs: BenchmarkRun[];
};

export function ResultsView({ runs }: ResultsViewProps) {
  const maxScore = Math.max(...runs.map((run) => run.score), 1);

  return (
    <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
      <section className="rounded-md border border-border bg-card/80 p-4">
        <div className="mb-4">
          <h2 className="font-display text-2xl font-bold uppercase">Score Distribution</h2>
        </div>
        <div className="space-y-3">
          {runs.map((run, index) => (
            <div key={run.runId} className="grid grid-cols-[2.5rem_1fr_4rem] items-center gap-3">
              <div className="font-mono text-sm text-muted-foreground">
                {String(index + 1).padStart(2, "0")}
              </div>
              <div className="min-w-0">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="truncate font-semibold">{modelLabel(run.model)}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {run.diagnostics.stable_orbit ? "orbit" : run.finalOrbit.situation}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-secondary">
                  <div
                    className="h-2 rounded-full bg-gradient-to-r from-emerald-300 via-sky-300 to-amber-200"
                    style={{ width: `${Math.max(2, (run.score / maxScore) * 100)}%` }}
                  />
                </div>
              </div>
              <div className="text-right font-display text-2xl font-bold">{run.score.toFixed(1)}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-md border border-border bg-card/80">
        <div className="flex items-center justify-between gap-4 border-b border-border p-4">
          <div>
            <h2 className="font-display text-2xl font-bold uppercase">Leaderboard</h2>
          </div>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Rank</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead className="text-right">Apoapsis</TableHead>
              <TableHead className="text-right">Periapsis</TableHead>
              <TableHead className="text-right">MET</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run, index) => (
              <TableRow key={run.runId}>
                <TableCell className="font-mono text-muted-foreground">
                  {String(index + 1).padStart(2, "0")}
                </TableCell>
                <TableCell>
                  <div className="font-semibold">{modelLabel(run.model)}</div>
                  <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                    {run.runId}
                  </div>
                </TableCell>
                <TableCell className="text-right font-display text-xl font-bold">
                  {run.score.toFixed(2)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatMeters(run.finalOrbit.apoapsis_m)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatMeters(run.finalOrbit.periapsis_m)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatSeconds(run.time.mission_elapsed_s)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
