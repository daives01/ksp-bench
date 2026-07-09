import { useMemo, useState } from "react";
import { ArrowUpRight, CheckCircle2, CircleDot, Crosshair, Gauge, Orbit, Route } from "lucide-react";
import { formatMeters, formatSeconds, modelLabel } from "@/lib/format";
import type { BenchmarkRun } from "@/types";

const COLORS = ["#ff8d5c", "#5ac8fa", "#f7d154", "#95e6b8", "#d9a7ff", "#ff86b9"];

type Point = { t: number; alt: number; apo: number; peri: number; lat: number | null; lon: number | null; speed: number };

export function OrbitView({ runs }: { runs: BenchmarkRun[] }) {
  const [selectedId, setSelectedId] = useState(runs[0]?.runId);
  const selected = runs.find((run) => run.runId === selectedId) ?? runs[0];
  const traces = useMemo(() => runs.map((run, index) => ({ run, color: COLORS[index % COLORS.length], points: pointsFor(run) })), [runs]);

  if (!selected) return null;
  const selectedPoints = pointsFor(selected);
  const hasPosition = selectedPoints.some((point) => point.lat != null && point.lon != null);

  return (
    <div className="flight-layout">
      <section className="flight-stage">
        <div className="flight-stage__head">
          <div>
            <p className="eyebrow"><Route size={13} /> Flight recorder</p>
            <h2>Every ascent, on one timeline.</h2>
          </div>
          <div className="flight-stage__target"><Crosshair size={15} /> 80 km target orbit</div>
        </div>
        <AltitudeChart traces={traces} selectedId={selected.runId} />
        <div className="flight-legend">
          <span><i className="chart-key target" /> target altitude</span>
          <span><i className="chart-key orbit" /> apoapsis / periapsis</span>
          <span>Click a flight in the ledger to focus it.</span>
        </div>
      </section>

      <aside className="flight-ledger">
        <div className="flight-ledger__head">
          <p className="eyebrow"><Orbit size={13} /> Flight ledger</p>
          <span>{runs.length} attempts</span>
        </div>
        {traces.map(({ run, color }) => (
          <button className={`flight-row ${run.runId === selected.runId ? "is-selected" : ""}`} key={run.runId} onClick={() => setSelectedId(run.runId)}>
            <i style={{ backgroundColor: color }} />
            <span className="flight-row__name">{modelLabel(run.model)}<small>{run.diagnostics.stable_orbit ? "stable orbit" : run.finalOrbit.situation.replaceAll("_", " ")}</small></span>
            <strong>{run.score.toFixed(1)}</strong>
          </button>
        ))}
      </aside>

      <section className="flight-detail">
        <div className="flight-detail__title">
          <div><p className="eyebrow"><CircleDot size={13} /> Selected flight</p><h3>{modelLabel(selected.model)}</h3></div>
          {selected.diagnostics.stable_orbit ? <span className="status-good"><CheckCircle2 size={15} /> orbit achieved</span> : <span className="status-muted">flight ended early</span>}
        </div>
        <div className="orbit-profile" aria-label="Orbit profile">
          <GroundTrack points={selectedPoints} />
          <div className="orbit-ring" style={{ transform: `scaleY(${Math.max(0.42, 1 - selected.finalOrbit.eccentricity * 0.7)}) rotate(${selected.finalOrbit.inclination_deg}deg)` }} />
          <div className="orbit-probe" />
          <p>{hasPosition ? "Ground track captured" : "Orbit profile from final telemetry"}</p>
        </div>
        <dl className="flight-stats">
          <Stat label="Apoapsis" value={formatMeters(selected.finalOrbit.apoapsis_m)} />
          <Stat label="Periapsis" value={formatMeters(selected.finalOrbit.periapsis_m)} />
          <Stat label="Orbit error" value={formatMeters(selected.finalOrbit.orbit_error_m)} />
          <Stat label="Mission time" value={formatSeconds(selected.time.mission_elapsed_s)} />
          <Stat label="Peak altitude" value={formatMeters(selected.diagnostics.max_altitude_m)} />
          <Stat label="Final speed" value={`${selected.finalOrbit.orbital_speed_m_s.toFixed(0)} m/s`} />
        </dl>
        <p className="trace-note"><Gauge size={14} /> New runs record geographic trace points for true ground-track reconstruction; legacy flights remain comparable on this altitude timeline.</p>
      </section>
    </div>
  );
}

function AltitudeChart({ traces, selectedId }: { traces: { run: BenchmarkRun; color: string; points: Point[] }[]; selectedId: string }) {
  const width = 960; const height = 430; const pad = { l: 64, r: 24, t: 28, b: 48 };
  const maxTime = Math.max(...traces.flatMap(({ points }) => points.map((point) => point.t)), 1);
  const maxAltitude = Math.max(100000, ...traces.flatMap(({ points }) => points.flatMap((point) => [point.alt, point.apo, point.peri].filter((value) => value > 0))));
  const x = (value: number) => pad.l + (value / maxTime) * (width - pad.l - pad.r);
  const y = (value: number) => height - pad.b - (Math.max(0, value) / maxAltitude) * (height - pad.t - pad.b);
  const path = (points: Point[], field: keyof Point) => points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(Number(point[field]) || 0).toFixed(1)}`).join(" ");
  return <div className="altitude-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Altitude, apoapsis, and periapsis over mission time">
    {[0, 0.25, 0.5, 0.75, 1].map((tick) => <g key={tick}><line x1={pad.l} x2={width - pad.r} y1={y(maxAltitude * tick)} y2={y(maxAltitude * tick)} className="chart-grid" /><text x={pad.l - 12} y={y(maxAltitude * tick) + 4} textAnchor="end">{Math.round(maxAltitude * tick / 1000)}k</text></g>)}
    <line x1={pad.l} x2={width - pad.r} y1={y(80000)} y2={y(80000)} className="chart-target" />
    {[0, .25, .5, .75, 1].map((tick) => <text key={tick} x={x(maxTime * tick)} y={height - 16} textAnchor="middle">{formatSeconds(maxTime * tick)}</text>)}
    {traces.map(({ run, color, points }) => <g key={run.runId} className={run.runId === selectedId ? "chart-line is-focused" : "chart-line"}><path d={path(points, "apo")} stroke={color} className="chart-orbit-line" /><path d={path(points, "peri")} stroke={color} className="chart-peri-line" /><path d={path(points, "alt")} stroke={color} className="chart-alt-line" /></g>)}
  </svg></div>;
}

function pointsFor(run: BenchmarkRun): Point[] {
  const trace = run.flight; if (!trace) return [];
  const value = (row: Array<number | null>, name: string) => row[trace.columns.indexOf(name)] ?? 0;
  return trace.points.map((row) => ({ t: Number(value(row, "t")), alt: Number(value(row, "alt")), apo: Number(value(row, "apo")), peri: Number(value(row, "peri")), lat: value(row, "lat"), lon: value(row, "lon"), speed: Number(value(row, "speed")) }));
}
function Stat({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }

function GroundTrack({ points }: { points: Point[] }) {
  const tracked = points.filter((point) => point.lat != null && point.lon != null);
  const path = tracked.map((point, index) => {
    const x = 16 + ((Number(point.lon) + 180) / 360) * 168;
    const y = 16 + ((90 - Number(point.lat)) / 180) * 82;
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return <div className="ground-track">
    <svg viewBox="0 0 200 114" aria-label="Kerbin ground track">
      <defs><clipPath id="kerbin-map"><rect x="16" y="16" width="168" height="82" rx="40" /></clipPath></defs>
      <rect x="16" y="16" width="168" height="82" rx="40" className="ground-track__planet" />
      <path d="M16 57h168M100 16v82M16 36h168M16 78h168" className="ground-track__grid" />
      {path ? <path d={path} clipPath="url(#kerbin-map)" className="ground-track__path" /> : null}
      <text x="100" y="61" textAnchor="middle">KERBIN</text>
    </svg>
  </div>;
}
