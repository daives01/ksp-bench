import { useEffect, useMemo, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatMeters, formatSeconds, modelLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BenchmarkRun, TelemetrySample } from "@/types";

const KERBIN_RADIUS_M = 600_000;
const SVG_SIZE = 420;
const CENTER = SVG_SIZE / 2;
const ORBIT_COLORS = ["#34d399", "#7dd3fc", "#facc15", "#fb7185", "#a7f3d0", "#fbbf24"];

type OrbitViewProps = {
  runs: BenchmarkRun[];
};

type Point = {
  x: number;
  y: number;
};

export function OrbitView({ runs }: OrbitViewProps) {
  const [selectedRunId, setSelectedRunId] = useState(runs[0]?.runId);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(100);
  const selectedRun = runs.find((run) => run.runId === selectedRunId) ?? runs[0];
  const scale = useMemo(() => orbitScale(runs), [runs]);
  const currentSample = selectedRun ? sampleAtProgress(selectedRun.telemetry, progress) : undefined;

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      setProgress((value) => {
        if (value >= 100) {
          setIsPlaying(false);
          return 100;
        }
        return Math.min(100, value + 1.5);
      });
    }, 80);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  if (!selectedRun) return null;

  return (
    <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
      <section className="rounded-md border border-border bg-card/80 p-4">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-display text-2xl font-bold uppercase">Orbit Plot</h2>
          </div>
          <Badge variant={selectedRun.diagnostics.stable_orbit ? "success" : "warning"}>
            {selectedRun.diagnostics.stable_orbit ? "stable orbit" : selectedRun.finalOrbit.situation}
          </Badge>
        </div>

        <div className="relative mx-auto aspect-square w-full max-w-[34rem] overflow-hidden rounded-md border border-border bg-[#050806]">
          <svg viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`} className="h-full w-full">
            <defs>
              <radialGradient id="kerbin" cx="44%" cy="36%" r="60%">
                <stop offset="0%" stopColor="#6ee7b7" />
                <stop offset="45%" stopColor="#0ea5e9" />
                <stop offset="100%" stopColor="#064e3b" />
              </radialGradient>
              <filter id="softGlow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur" />
                <feMerge>
                  <feMergeNode in="coloredBlur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <rect width={SVG_SIZE} height={SVG_SIZE} fill="#050806" />
            <g opacity="0.28">
              {[-140, -70, 0, 70, 140].map((offset) => (
                <line
                  key={`v-${offset}`}
                  x1={CENTER + offset}
                  x2={CENTER + offset}
                  y1="0"
                  y2={SVG_SIZE}
                  stroke="#334155"
                  strokeWidth="1"
                />
              ))}
              {[-140, -70, 0, 70, 140].map((offset) => (
                <line
                  key={`h-${offset}`}
                  x1="0"
                  x2={SVG_SIZE}
                  y1={CENTER + offset}
                  y2={CENTER + offset}
                  stroke="#334155"
                  strokeWidth="1"
                />
              ))}
            </g>
            <circle
              cx={CENTER}
              cy={CENTER}
              r={KERBIN_RADIUS_M * scale}
              fill="url(#kerbin)"
              opacity="0.98"
            />
            <circle
              cx={CENTER}
              cy={CENTER}
              r={(KERBIN_RADIUS_M + selectedRun.finalOrbit.target_altitude_m) * scale}
              fill="none"
              stroke="#facc15"
              strokeDasharray="3 5"
              strokeWidth="1.5"
              opacity="0.95"
            />
            {runs.map((run, index) => (
              <OrbitEllipse
                key={run.runId}
                run={run}
                scale={scale}
                color={ORBIT_COLORS[index % ORBIT_COLORS.length]}
                active={run.runId === selectedRun.runId}
              />
            ))}
            <TrajectoryPath
              run={selectedRun}
              progress={progress}
              scale={scale}
              color="#ffffff"
            />
            {currentSample ? (
              <Probe sample={currentSample} run={selectedRun} scale={scale} progress={progress} />
            ) : null}
          </svg>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex gap-2">
            <Button
              size="icon"
              title={isPlaying ? "Pause trajectory" : "Play trajectory"}
              onClick={() => {
                if (progress >= 100) setProgress(0);
                setIsPlaying((value) => !value);
              }}
            >
              {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button
              variant="outline"
              size="icon"
              title="Reset trajectory"
              onClick={() => {
                setIsPlaying(false);
                setProgress(0);
              }}
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
          </div>
          <input
            aria-label="Trajectory progress"
            className="h-2 flex-1 accent-emerald-300"
            type="range"
            min="0"
            max="100"
            value={progress}
            onChange={(event) => {
              setIsPlaying(false);
              setProgress(Number(event.target.value));
            }}
          />
          <div className="w-20 font-mono text-xs text-muted-foreground sm:text-right">
            {currentSample ? formatSeconds(currentSample.mission_elapsed_s) : "n/a"}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="rounded-md border border-border bg-card/80 p-4">
          <h2 className="font-display text-2xl font-bold uppercase">Model Runs</h2>
          <div className="mt-4 space-y-2">
            {runs.map((run, index) => (
              <button
                key={run.runId}
                className={cn(
                  "grid w-full grid-cols-[0.75rem_1fr_auto] items-center gap-3 rounded-md border p-3 text-left transition-colors",
                  run.runId === selectedRun.runId
                    ? "border-emerald-300/70 bg-emerald-300/10"
                    : "border-border bg-background/30 hover:bg-secondary/60",
                )}
                onClick={() => {
                  setSelectedRunId(run.runId);
                  setProgress(100);
                  setIsPlaying(false);
                }}
              >
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: ORBIT_COLORS[index % ORBIT_COLORS.length] }}
                />
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{modelLabel(run.model)}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    e {run.finalOrbit.eccentricity.toFixed(3)} / i {run.finalOrbit.inclination_deg.toFixed(3)} deg
                  </span>
                </span>
                <span className="font-display text-xl font-bold">{run.score.toFixed(1)}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-border bg-card/80 p-4">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate font-display text-2xl font-bold uppercase">
                {modelLabel(selectedRun.model)}
              </h3>
              <p className="font-mono text-[11px] text-muted-foreground">{selectedRun.runId}</p>
            </div>
            <Badge variant="outline">{selectedRun.finalOrbit.body}</Badge>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <OrbitMetric label="Apoapsis" value={formatMeters(selectedRun.finalOrbit.apoapsis_m)} />
            <OrbitMetric label="Periapsis" value={formatMeters(selectedRun.finalOrbit.periapsis_m)} />
            <OrbitMetric label="Target error" value={formatMeters(selectedRun.finalOrbit.orbit_error_m)} />
            <OrbitMetric label="Max altitude" value={formatMeters(selectedRun.diagnostics.max_altitude_m)} />
            <OrbitMetric label="Eccentricity" value={selectedRun.finalOrbit.eccentricity.toFixed(4)} />
            <OrbitMetric label="Speed" value={`${selectedRun.finalOrbit.orbital_speed_m_s.toFixed(0)} m/s`} />
          </dl>
        </div>
      </section>
    </div>
  );
}

function OrbitMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-background/40 p-3">
      <dt className="font-mono text-[11px] uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  );
}

function OrbitEllipse({
  run,
  scale,
  color,
  active,
}: {
  run: BenchmarkRun;
  scale: number;
  color: string;
  active: boolean;
}) {
  const apo = KERBIN_RADIUS_M + Math.max(run.finalOrbit.apoapsis_m, -KERBIN_RADIUS_M * 0.92);
  const peri = KERBIN_RADIUS_M + Math.max(run.finalOrbit.periapsis_m, -KERBIN_RADIUS_M * 0.92);
  const semiMajor = Math.max((apo + peri) / 2, KERBIN_RADIUS_M * 0.08);
  const semiMinor = Math.max(semiMajor * Math.sqrt(Math.max(0.02, 1 - run.finalOrbit.eccentricity ** 2)), 4 / scale);
  const focusOffset = ((apo - peri) / 2) * scale;

  return (
    <ellipse
      cx={CENTER - focusOffset}
      cy={CENTER}
      rx={semiMajor * scale}
      ry={semiMinor * scale}
      fill="none"
      stroke={color}
      strokeWidth={active ? 2.8 : 1.4}
      strokeDasharray={run.diagnostics.stable_orbit ? undefined : "7 6"}
      opacity={active ? 1 : 0.52}
      filter={active ? "url(#softGlow)" : undefined}
    >
      <title>
        {`${modelLabel(run.model)} / apo ${formatMeters(run.finalOrbit.apoapsis_m)} / peri ${formatMeters(run.finalOrbit.periapsis_m)}`}
      </title>
    </ellipse>
  );
}

function TrajectoryPath({
  run,
  progress,
  scale,
  color,
}: {
  run: BenchmarkRun;
  progress: number;
  scale: number;
  color: string;
}) {
  const samples = visibleSamples(run.telemetry, progress);
  const points = samples.map((sample) => samplePoint(sample, run, scale));
  const d = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");

  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      opacity="0.82"
    />
  );
}

function Probe({
  sample,
  run,
  scale,
  progress,
}: {
  sample: TelemetrySample;
  run: BenchmarkRun;
  scale: number;
  progress: number;
}) {
  const point = samplePoint(sample, run, scale);

  return (
    <g transform={`translate(${point.x} ${point.y})`}>
      <circle r="5" fill="#f8fafc" />
      <circle r="10" fill="none" stroke="#f8fafc" strokeOpacity="0.25">
        <title>{`${progress.toFixed(0)}% replay / altitude ${formatMeters(sample.altitude_m)}`}</title>
      </circle>
    </g>
  );
}

function orbitScale(runs: BenchmarkRun[]) {
  const maxRadius = Math.max(
    ...runs.flatMap((run) => [
      KERBIN_RADIUS_M + Math.max(run.finalOrbit.apoapsis_m, 0),
      KERBIN_RADIUS_M + Math.max(run.diagnostics.max_apoapsis_m, 0),
      KERBIN_RADIUS_M + run.finalOrbit.target_altitude_m,
    ]),
    KERBIN_RADIUS_M + 80_000,
  );
  return 175 / maxRadius;
}

function visibleSamples(samples: TelemetrySample[], progress: number) {
  if (samples.length <= 1) return samples;
  const count = Math.max(1, Math.ceil((samples.length * progress) / 100));
  return samples.slice(0, count);
}

function sampleAtProgress(samples: TelemetrySample[], progress: number) {
  if (samples.length === 0) return undefined;
  const index = Math.min(samples.length - 1, Math.max(0, Math.round(((samples.length - 1) * progress) / 100)));
  return samples[index];
}

function samplePoint(sample: TelemetrySample, run: BenchmarkRun, scale: number): Point {
  const lastMet = run.telemetry.at(-1)?.mission_elapsed_s || run.time.mission_elapsed_s || 1;
  const fraction = Math.min(1, Math.max(0, sample.mission_elapsed_s / lastMet));
  const headingBias = ((sample.heading_deg ?? 90) - 90) * 0.35;
  const angle = (-115 + fraction * 285 + headingBias) * (Math.PI / 180);
  const radius = (KERBIN_RADIUS_M + Math.max(sample.altitude_m, -KERBIN_RADIUS_M * 0.92)) * scale;

  return {
    x: CENTER + Math.cos(angle) * radius,
    y: CENTER + Math.sin(angle) * radius,
  };
}
