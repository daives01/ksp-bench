import { useEffect, useMemo, useState } from "react";
import { formatSeconds, modelLabel } from "@/lib/format";
import { loadFlightTrace } from "@/lib/data";
import type { BenchmarkRun, FlightTrace } from "@/types";

const COLORS = ["#95e6b8", "#5ac8fa", "#ff8d5c", "#d9a7ff", "#f7d154", "#ff86b9"];

type Point = { t: number; alt: number };
type FlightEvent = NonNullable<FlightTrace["events"]>[number];

export function OrbitView({ runs }: { runs: BenchmarkRun[] }) {
  const [selectedId, setSelectedId] = useState(runs[0]?.runId);
  const [loadedTraces, setLoadedTraces] = useState<Record<string, FlightTrace>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const selected = runs.find((run) => run.runId === selectedId) ?? runs[0];
  const selectedTrace = selected ? loadedTraces[selected.runId] ?? selected.flight : undefined;

  useEffect(() => setSelectedId(runs[0]?.runId), [runs]);
  useEffect(() => {
    if (!selected?.flightUrl || loadedTraces[selected.runId]) return;
    let cancelled = false;
    void loadFlightTrace(selected.flightUrl)
      .then((flight) => {
        if (!cancelled) setLoadedTraces((traces) => ({ ...traces, [selected.runId]: flight }));
      })
      .catch(() => {
        if (!cancelled) setLoadError("Flight trace could not be loaded.");
      });
    return () => { cancelled = true; };
  }, [loadedTraces, selected]);
  const traces = useMemo(
    () => selected && selectedTrace
      ? [{ run: selected, color: COLORS[0], points: pointsFor(selectedTrace), events: selectedTrace.events ?? [] }]
      : [],
    [selected, selectedTrace],
  );

  if (!runs.length) return <div className="flight-empty">No flight data yet.</div>;

  return (
    <section className="flight-view">
      <div className="flight-view__head">
        <div>
          <h2>Flights</h2>
          <p>Altitude by mission time</p>
        </div>
        <span className="flight-target">80 km target</span>
      </div>

      {selectedTrace ? <AltitudeChart traces={traces} selectedId={selectedId} /> : <div className="flight-loading">Loading selected flight…</div>}
      {loadError ? <p className="flight-error">{loadError}</p> : null}

      <div className="flight-list" aria-label="Select a flight">
        {runs.map((run, index) => (
          <button
            className={`flight-list__item ${run.runId === selectedId ? "is-selected" : ""}`}
            key={run.runId}
            onClick={() => {
              setLoadError(null);
              setSelectedId(run.runId);
            }}
          >
            <i style={{ backgroundColor: COLORS[index % COLORS.length] }} />
            <span>{modelLabel(run.model)}</span>
            <strong>{formatSeconds(run.time.mission_elapsed_s)}</strong>
          </button>
        ))}
      </div>
    </section>
  );
}

function AltitudeChart({ traces, selectedId }: { traces: { run: BenchmarkRun; color: string; points: Point[]; events: FlightEvent[] }[]; selectedId: string | undefined }) {
  const width = 960;
  const height = 400;
  const pad = { l: 58, r: 24, t: 20, b: 42 };
  const maxTime = Math.max(...traces.flatMap(({ points }) => points.map((point) => point.t)), 1);
  const maxAltitude = Math.max(100000, ...traces.flatMap(({ points }) => points.map((point) => point.alt)));
  const x = (value: number) => pad.l + (value / maxTime) * (width - pad.l - pad.r);
  const y = (value: number) => height - pad.b - (Math.max(0, value) / maxAltitude) * (height - pad.t - pad.b);
  const path = (points: Point[]) => points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.alt).toFixed(1)}`).join(" ");

  return (
    <div className="altitude-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Flight altitude over mission time">
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line x1={pad.l} x2={width - pad.r} y1={y(maxAltitude * tick)} y2={y(maxAltitude * tick)} className="chart-grid" />
            <text x={pad.l - 11} y={y(maxAltitude * tick) + 4} textAnchor="end">{Math.round(maxAltitude * tick / 1000)}k</text>
          </g>
        ))}
        <line x1={pad.l} x2={width - pad.r} y1={y(80000)} y2={y(80000)} className="chart-target" />
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => <text key={tick} x={x(maxTime * tick)} y={height - 14} textAnchor="middle">{formatSeconds(maxTime * tick)}</text>)}
        {traces.map(({ run, color, points }) => (
          <path key={run.runId} d={path(points)} stroke={color} className={`chart-line ${run.runId === selectedId ? "is-focused" : ""}`} />
        ))}
        {traces.flatMap(({ run, color, events }) => events.map((event, index) => (
          <circle
            className={`chart-event ${event.ok ? "" : "is-error"}`}
            cx={x(event.t)}
            cy={y(event.alt)}
            fill={color}
            key={`${run.runId}-${event.t}-${event.type}-${index}`}
            r={event.ok ? 4 : 5}
            tabIndex={0}
          >
            <title>{`${formatSeconds(event.t)} · ${event.label}`}</title>
          </circle>
        )))}
      </svg>
    </div>
  );
}

function pointsFor(trace: FlightTrace): Point[] {
  const index = trace.columns.indexOf("alt");
  const timeIndex = trace.columns.indexOf("t");
  return trace.points.map((row) => ({ t: Number(row[timeIndex] ?? 0), alt: Number(row[index] ?? 0) }));
}
