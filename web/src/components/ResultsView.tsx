import { useEffect, useMemo, useRef, useState } from "react";
import { Filter, Search } from "lucide-react";
import { formatCost, formatSeconds, modelLabel, runOutcome } from "@/lib/format";
import { loadFlightTrace } from "@/lib/data";
import { projectedAltitude, type AltitudePoint } from "@/lib/trajectory";
import { altitudeAnimationDelay } from "@/lib/altitudeAnimation";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { BenchmarkRun, FlightTrace } from "@/types";

const COLORS = ["#95e6b8", "#5ac8fa", "#ff8d5c", "#d9a7ff", "#f7d154", "#ff86b9", "#70d6c1", "#b7b7ff"];
// Structural rendering and responsive CSS switch together at this boundary.
const MOBILE_MEDIA_QUERY = "(max-width: 760px)";
type Metric = "score" | "time" | "cost" | "tokens";
type Point = AltitudePoint & { apo?: number; peri?: number; speed?: number; stage?: number; fuel?: number; q?: number };

const metricMeta: Record<Metric, { label: string; unit: string; better: "high" | "low" }> = {
  score: { label: "Score", unit: "pts", better: "high" }, time: { label: "Time", unit: "s", better: "low" },
  cost: { label: "Cost", unit: "USD", better: "low" }, tokens: { label: "Tokens", unit: "tokens", better: "low" },
};

function value(run: BenchmarkRun, metric: Metric) {
  if (metric === "score") return run.score;
  if (metric === "time") return run.time.wall_clock_elapsed_s ?? run.time.mission_elapsed_s;
  if (metric === "cost") return run.usage?.cost_usd ?? Number.POSITIVE_INFINITY;
  return run.usage?.total_tokens ?? Number.POSITIVE_INFINITY;
}
function display(run: BenchmarkRun, metric: Metric) {
  const v = value(run, metric);
  if (!Number.isFinite(v)) return "n/a";
  if (metric === "score") return v.toFixed(1);
  if (metric === "time") return formatSeconds(v);
  if (metric === "cost") return formatCost(v);
  return v.toLocaleString();
}
function pointsFor(trace: FlightTrace): Point[] {
  const column = (name: string) => trace.columns.indexOf(name);
  const [time, alt, apo, peri, speed, stage, fuel, q] = ["t", "alt", "apo", "peri", "speed", "stage", "fuel", "q"].map(column);
  const optional = (row: Array<number | null>, index: number) => index >= 0 && row[index] != null ? Number(row[index]) : undefined;
  return trace.points.map((row) => ({ t: Number(row[time] ?? 0), alt: Number(row[alt] ?? 0), apo: optional(row, apo), peri: optional(row, peri), speed: optional(row, speed), stage: optional(row, stage), fuel: optional(row, fuel), q: optional(row, q) })).filter((point) => Number.isFinite(point.t) && Number.isFinite(point.alt));
}

export function ResultsView({ runs }: { runs: BenchmarkRun[] }) {
  const isMobile = useMediaQuery(MOBILE_MEDIA_QUERY);
  const [metric, setMetric] = useState<Metric>("score");
  const [xMetric, setXMetric] = useState<Metric>("cost");
  const [yMetric, setYMetric] = useState<Metric>("score");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const activeId = pinnedId ?? hoveredId;
  const [traces, setTraces] = useState<Record<string, FlightTrace>>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set(runs.map((run) => run.runId)));
  const [filterOpen, setFilterOpen] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => setSelectedIds(new Set(runs.map((run) => run.runId))), [runs]);
  useEffect(() => {
    const clearPinned = (event: KeyboardEvent) => { if (event.key === "Escape") setPinnedId(null); };
    window.addEventListener("keydown", clearPinned);
    return () => window.removeEventListener("keydown", clearPinned);
  }, []);
  const visibleRuns = useMemo(() => runs.filter((run) => selectedIds.has(run.runId)), [runs, selectedIds]);
  useEffect(() => { if (pinnedId && !selectedIds.has(pinnedId)) setPinnedId(null); }, [pinnedId, selectedIds]);
  const colors = useMemo(() => Object.fromEntries(runs.map((run, index) => [run.runId, COLORS[index % COLORS.length]])), [runs]);
  const rankedRuns = useMemo(() => [...visibleRuns].sort((a, b) => {
    const delta = value(a, metric) - value(b, metric);
    return metricMeta[metric].better === "high" ? -delta : delta;
  }), [visibleRuns, metric]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all(runs.map(async (run) => {
      if (run.flight) return [run.runId, run.flight] as const;
      if (!run.flightUrl) return null;
      try { return [run.runId, await loadFlightTrace(run.flightUrl)] as const; } catch { return null; }
    })).then((loaded) => {
      if (!cancelled) setTraces(Object.fromEntries(loaded.filter((item): item is readonly [string, FlightTrace] => item !== null)));
    });
    return () => { cancelled = true; };
  }, [runs]);

  if (!runs.length) return <div className="empty-state">No runs yet.</div>;
  const metricMax = metric === "score" ? 120 : Math.max(...rankedRuns.map((run) => Number.isFinite(value(run, metric)) ? value(run, metric) : 0), 1);
  const chartTraces = visibleRuns.flatMap((run) => {
    const trace = traces[run.runId]; const points = trace && pointsFor(trace);
    return points?.length ? [{ run, points, events: trace.events ?? [], color: colors[run.runId] }] : [];
  });

  const leaderboardPanel = <section className="mission-panel leaderboard-panel">
    <div className="panel-head"><div className="leaderboard-heading"><h2>Leaderboard</h2><MetricControl value={metric} onChange={setMetric} /></div><ModelFilters runs={runs} selectedIds={selectedIds} setSelectedIds={setSelectedIds} open={filterOpen} setOpen={setFilterOpen} query={query} setQuery={setQuery} /></div>
    <div className="leaderboard-list"><div className="leaderboard-list__content">
      {!rankedRuns.length ? <p className="leaderboard-empty">No models selected.</p> : null}
      {rankedRuns.map((run, index) => {
        const v = value(run, metric), bar = Number.isFinite(v) && v > 0 ? Math.min(100, Math.max(3, v / metricMax * 100)) : 0;
        const focused = activeId === run.runId;
        return <button key={`${metric}-${run.runId}`} className={`leaderboard-row ${focused ? "is-active" : ""}`} style={{ animationDelay: `${index * 36}ms` }} aria-pressed={pinnedId === run.runId} onMouseEnter={() => setHoveredId(run.runId)} onMouseLeave={() => setHoveredId(null)} onFocus={() => setHoveredId(run.runId)} onBlur={() => setHoveredId(null)} onClick={() => setPinnedId(pinnedId === run.runId ? null : run.runId)}>
          <span className="leaderboard-rank">{String(index + 1).padStart(2, "0")}</span><span className="leaderboard-color" style={{ background: colors[run.runId] }} />
          <span className="leaderboard-name"><strong>{modelLabel(run.model)}</strong><small>{runOutcome(run)}</small></span>
          <span className="leaderboard-bar"><i style={{ width: `${bar}%`, background: colors[run.runId] }} /></span><strong className="leaderboard-value">{display(run, metric)}</strong>
        </button>;
      })}
    </div></div>
  </section>;
  const flightPanel = <section className="mission-panel flight-panel">
    <div className="panel-head"><h2>Altitude</h2><span className="target-label">80 km</span></div>
    {chartTraces.length ? <AltitudeChart traces={chartTraces} activeId={activeId} pinnedId={pinnedId} setPinnedId={setPinnedId} compact={isMobile} /> : <div className="chart-loading">No flights selected.</div>}
  </section>;

  return <section className="unified-bench">
    <div className="unified-bench__layout">
      {isMobile ? <>{flightPanel}{leaderboardPanel}</> : <>{leaderboardPanel}{flightPanel}</>}
    </div>
    <section className="mission-panel grid-panel">
      <div className="compare-head"><h2>Compare</h2><div className="axis-controls"><label><span>Y axis</span><MetricControl value={yMetric} onChange={setYMetric} /></label><span className="axis-controls__by">by</span><label><span>X axis</span><MetricControl value={xMetric} onChange={setXMetric} /></label></div></div>
      <TradeoffGrid runs={visibleRuns} colors={colors} xMetric={xMetric} yMetric={yMetric} activeId={activeId} pinnedId={pinnedId} setHoveredId={setHoveredId} setPinnedId={setPinnedId} setXMetric={setXMetric} setYMetric={setYMetric} compact={isMobile} />
    </section>
  </section>;
}

function ModelFilters({ runs, selectedIds, setSelectedIds, open, setOpen, query, setQuery }: { runs: BenchmarkRun[]; selectedIds: Set<string>; setSelectedIds: (ids: Set<string>) => void; open: boolean; setOpen: (open: boolean) => void; query: string; setQuery: (query: string) => void }) {
  const matches = runs.filter((run) => modelLabel(run.model).toLowerCase().includes(query.trim().toLowerCase()));
  const select = (ids: string[]) => setSelectedIds(new Set(ids));
  return <div className="model-filters">
    <Button variant="ghost" size="icon" className="model-filter-trigger" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`Filter models, ${selectedIds.size} of ${runs.length} shown`} title="Filter models"><Filter className="h-4 w-4" /></Button>
    {open ? <div className="model-filters__body" role="dialog" aria-label="Choose models">
      <div className="model-filter-head"><div><strong>Models</strong><span>{selectedIds.size} of {runs.length}</span></div><div className="model-filter-actions"><Button variant="ghost" size="sm" onClick={() => select(runs.map((run) => run.runId))}>All</Button><Button variant="ghost" size="sm" onClick={() => select([])}>None</Button><Button variant="ghost" size="sm" onClick={() => select(runs.filter((run) => run.diagnostics.stable_orbit).map((run) => run.runId))}>Orbit</Button></div></div>
      <label className="model-search"><Search className="h-4 w-4" /><span className="sr-only">Search models</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search models…" /></label>
      <div className="model-checklist">{matches.map((run) => <label key={run.runId} className="model-check"><input type="checkbox" checked={selectedIds.has(run.runId)} onChange={() => { const next = new Set(selectedIds); if (next.has(run.runId)) next.delete(run.runId); else next.add(run.runId); setSelectedIds(next); }} /><span>{modelLabel(run.model)}</span></label>)}{!matches.length ? <p className="model-filter-no-results">No models match “{query}”.</p> : null}</div>
    </div> : null}
  </div>;
}

function MetricControl({ value, onChange }: { value: Metric; onChange: (value: Metric) => void }) { return <Select value={value} onValueChange={(next: string) => onChange(next as Metric)}><SelectTrigger className="metric-control"><SelectValue /></SelectTrigger><SelectContent>{(Object.keys(metricMeta) as Metric[]).map((key) => <SelectItem key={key} value={key}>{metricMeta[key].label}</SelectItem>)}</SelectContent></Select>; }

function AltitudeChart({ traces, activeId, pinnedId, setPinnedId, compact }: { traces: { run: BenchmarkRun; points: Point[]; events: NonNullable<FlightTrace["events"]>; color: string }[]; activeId: string | null; pinnedId: string | null; setPinnedId: (id: string | null) => void; compact: boolean }) {
  const width = compact ? 320 : 960, height = compact ? 360 : 600, pad = compact ? { l: 42, r: 12, t: 16, b: 44 } : { l: 70, r: 32, t: 22, b: 66 };
  const [tooltip, setTooltip] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  const plotted = traces.map((trace) => ({ ...trace, projected: projectedAltitude(trace.run, trace.points) }));
  const focused = plotted.find(({ run }) => run.runId === activeId);
  const focusedPoints = focused ? [...focused.points, ...focused.projected] : [];
  const recordedEnd = focused ? Math.max(...focused.points.map((p) => p.t), 1) : 0;
  const targetMaxTime = focused ? Math.max(...focusedPoints.map((p) => p.t, 1)) : Math.max(...plotted.flatMap(({ points }) => points.map((p) => p.t)), 1);
  const targetMaxAlt = focused ? Math.max(120000, ...focusedPoints.map((p) => p.alt)) * 1.06 : 120000;
  const targetRecordedFraction = focused && targetMaxTime > recordedEnd * 2.5 ? .34 : 1;
  const maxTime = useAnimatedNumber(targetMaxTime);
  const maxAlt = useAnimatedNumber(targetMaxAlt);
  const recordedFraction = useAnimatedNumber(targetRecordedFraction);
  const hasTimeBreak = Boolean(focused && targetMaxTime > recordedEnd * 2.5);
  const x = (v: number) => {
    const plotWidth = width - pad.l - pad.r;
    if (!focused || !hasTimeBreak || v <= recordedEnd) return pad.l + v / Math.max(recordedEnd || maxTime, 1) * plotWidth * (focused && hasTimeBreak ? recordedFraction : 1);
    return pad.l + plotWidth * (recordedFraction + (v-recordedEnd) / Math.max(maxTime-recordedEnd, 1) * (1-recordedFraction));
  };
  const y = (v: number) => height - pad.b - Math.max(0, v) / maxAlt * (height - pad.t - pad.b);
  const altitudeTicks = [0, .25, .5, .75, 1].map((tick) => maxAlt * tick);
  const path = (points: Point[]) => points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.alt).toFixed(1)}`).join(" ");
  const timeTicks = hasTimeBreak ? [0, recordedEnd, recordedEnd+(maxTime-recordedEnd)/2, maxTime] : [0, .25, .5, .75, 1].map((tick) => maxTime*tick);
  const breakX = x(recordedEnd);
  return <div className="altitude-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Recorded and projected flight altitudes in kilometers over mission time" onClick={() => setPinnedId(null)}><defs><clipPath id="altitude-plot"><rect x={pad.l} y={pad.t} width={width-pad.l-pad.r} height={height-pad.t-pad.b} /></clipPath></defs><text className="axis-title" transform={`translate(16 ${(pad.t+height-pad.b)/2}) rotate(-90)`} textAnchor="middle">Altitude (km)</text>{altitudeTicks.map((altitude) => <g key={altitude}><line className="chart-grid" x1={pad.l} x2={width-pad.r} y1={y(altitude)} y2={y(altitude)} /><text className="chart-tick" x={pad.l-10} y={y(altitude)+4} textAnchor="end">{Math.round(altitude/1000)}</text></g>)}{timeTicks.map((time) => <text className="chart-tick" key={time} x={x(time)} y={height-pad.b+24} textAnchor="middle">{formatSeconds(time)}</text>)}{hasTimeBreak ? <g className="chart-time-break"><path d={`M${breakX-7},${height-pad.b+5} l7,-10 M${breakX+1},${height-pad.b+5} l7,-10`} /><text x={breakX+12} y={pad.t+14}>projected orbit →</text></g> : null}<text className="axis-title" x={(pad.l+width-pad.r)/2} y={height-8} textAnchor="middle">Mission time</text><line className="chart-target" x1={pad.l} x2={width-pad.r} y1={y(80000)} y2={y(80000)} /><g clipPath="url(#altitude-plot)">{plotted.map(({run, points, projected, color}, index) => <g key={run.runId} onClick={(event) => { event.stopPropagation(); setPinnedId(pinnedId === run.runId ? null : run.runId); }}><path d={path(points)} stroke={color} className={`chart-line chart-line--hit chart-line--draw ${activeId && activeId !== run.runId ? "is-dimmed" : ""} ${activeId === run.runId ? "is-focused" : ""}`} style={{ animationDelay: altitudeAnimationDelay(index) }} />{projected.length ? <path d={path(projected)} stroke={color} className={`chart-line chart-line--projected chart-line--projected-draw ${activeId && activeId !== run.runId ? "is-dimmed" : ""} ${activeId === run.runId ? "is-focused" : ""}`} style={{ animationDelay: altitudeAnimationDelay(index) }} /> : null}</g>)}</g>{focused ? <g className="chart-waypoints">{focused.events.map((event, index) => <EventWaypoint key={`${event.t}-${event.type}-${index}`} event={event} point={nearestPoint(focused.points, event.t)} color={focused.color} x={x} y={y} setTooltip={setTooltip} />)}</g> : null}{tooltip ? <ChartTooltip {...tooltip} width={width} /> : null}</svg></div>;
}

function useAnimatedNumber(target: number, duration = 380) {
  const [value, setValue] = useState(target);
  const valueRef = useRef(value);
  useEffect(() => { valueRef.current = value; }, [value]);
  useEffect(() => {
    const from = valueRef.current, started = performance.now();
    let frame = 0;
    const animate = (now: number) => {
      const progress = Math.min(1, (now-started)/duration);
      const eased = 1-Math.pow(1-progress, 3);
      const next = from+(target-from)*eased;
      valueRef.current = next; setValue(next);
      if (progress < 1) frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [duration, target]);
  return value;
}

function nearestPoint(points: Point[], time: number) { return points.reduce((nearest, point) => Math.abs(point.t-time) < Math.abs(nearest.t-time) ? point : nearest, points[0]); }

function EventWaypoint({ event, point, color, x, y, setTooltip }: { event: NonNullable<FlightTrace["events"]>[number]; point: Point; color: string; x: (value: number) => number; y: (value: number) => number; setTooltip: (tooltip: { x: number; y: number; lines: string[] } | null) => void }) {
  const details = [event.label, `${formatSeconds(event.t)} · ${(event.alt/1000).toFixed(1)} km`, point.apo != null && point.peri != null ? `Apo ${(point.apo/1000).toFixed(1)} km · Peri ${(point.peri/1000).toFixed(1)} km` : null, point.speed != null ? `Speed ${Math.round(point.speed).toLocaleString()} m/s` : null, point.stage != null ? `Stage ${point.stage}` : null, point.fuel != null ? `Fuel ${point.fuel.toFixed(1)}` : null, point.q != null ? `Q ${(point.q/1000).toFixed(1)} kPa` : null].filter((line): line is string => Boolean(line));
  const cx=x(event.t), cy=y(event.alt);
  const common = { fill: event.ok ? color : "#ff6b6b", tabIndex: 0, className: `chart-waypoint chart-waypoint--${event.type}`, onMouseEnter: () => setTooltip({ x: cx, y: cy, lines: details }), onMouseLeave: () => setTooltip(null), onFocus: () => setTooltip({ x: cx, y: cy, lines: details }), onBlur: () => setTooltip(null) };
  if (event.type === "stage") return <rect {...common} x={cx-5} y={cy-5} width={10} height={10} transform={`rotate(45 ${cx} ${cy})`} />;
  if (event.type === "set_attitude") return <polygon {...common} points={`${cx},${cy-6} ${cx+6},${cy+5} ${cx-6},${cy+5}`} />;
  return <circle {...common} cx={cx} cy={cy} r={event.ok ? 4.5 : 6} />;
}

function ChartTooltip({ x, y, lines, width }: { x: number; y: number; lines: string[]; width: number }) {
  const boxWidth=224, boxHeight=20+lines.length*16;
  const left=Math.min(width-boxWidth-12, Math.max(12, x+12));
  const top=Math.max(10, y-boxHeight-12);
  return <g className="chart-tooltip" pointerEvents="none"><rect x={left} y={top} width={boxWidth} height={boxHeight} rx={7}/><text x={left+12} y={top+19}>{lines.map((line,index)=><tspan className={index===0 ? "chart-tooltip__title" : undefined} x={left+12} dy={index ? 16 : 0} key={line}>{line}</tspan>)}</text></g>;
}

function TradeoffGrid({ runs, colors, xMetric, yMetric, activeId, pinnedId, setHoveredId, setPinnedId, setXMetric, setYMetric, compact }: { runs: BenchmarkRun[]; colors: Record<string, string>; xMetric: Metric; yMetric: Metric; activeId: string | null; pinnedId: string | null; setHoveredId: (id: string | null) => void; setPinnedId: (id: string | null) => void; setXMetric: (metric: Metric) => void; setYMetric: (metric: Metric) => void; compact: boolean }) {
  const width=compact?320:960, height=compact?300:330, pad=compact?{l:52,r:12,t:18,b:50}:{l:78,r:34,t:24,b:58}; const finite = (metric: Metric) => runs.map((run) => value(run,metric)).filter(Number.isFinite);
  const extent = (metric: Metric) => niceExtent(finite(metric), metric); const [xmin,xmax]=extent(xMetric), [ymin,ymax]=extent(yMetric);
  const scale=(v:number,min:number,max:number,start:number,end:number,invert=false) => start + ((invert ? max-v : v-min) / Math.max(max-min, 1)) * (end-start);
  const tickDisplay = (metric: Metric, v: number) => metric === "cost" ? formatCost(v) : metric === "time" ? formatSeconds(v) : metric === "tokens" ? Intl.NumberFormat("en", { notation: "compact" }).format(v) : v.toFixed(1);
  return <div className="tradeoff-grid"><div className="axis-controls"><label><span>Y axis</span><MetricControl value={yMetric} onChange={setYMetric} /></label><span className="axis-controls__by">by</span><label><span>X axis</span><MetricControl value={xMetric} onChange={setXMetric} /></label></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metricMeta[xMetric].label} by ${metricMeta[yMetric].label} grid`} onClick={()=>setPinnedId(null)}><rect x={pad.l} y={pad.t} width={width-pad.l-pad.r} height={height-pad.t-pad.b} className="grid-box" />{[0,.25,.5,.75,1].map((tick)=>{const gx=pad.l+(width-pad.l-pad.r)*tick, gy=height-pad.b-(height-pad.t-pad.b)*tick; const xv=metricMeta[xMetric].better==="low"?xmax-(xmax-xmin)*tick:xmin+(xmax-xmin)*tick; const yv=ymin+(ymax-ymin)*tick; return <g key={tick}><line className="chart-grid" x1={gx} x2={gx} y1={pad.t} y2={height-pad.b}/><line className="chart-grid" x1={pad.l} x2={width-pad.r} y1={gy} y2={gy}/><text className="chart-tick" x={gx} y={height-pad.b+22} textAnchor="middle">{tickDisplay(xMetric,xv)}</text><text className="chart-tick" x={pad.l-12} y={gy+4} textAnchor="end">{tickDisplay(yMetric,yv)}</text></g>})}<text className="axis-title" x={(pad.l+width-pad.r)/2} y={height-5} textAnchor="middle">{metricMeta[xMetric].label} ({metricMeta[xMetric].unit}) · best →</text><text className="axis-title" transform={`translate(17 ${(pad.t+height-pad.b)/2}) rotate(-90)`} textAnchor="middle">{metricMeta[yMetric].label} ({metricMeta[yMetric].unit}) · best ↑</text>{runs.filter((run)=>Number.isFinite(value(run,xMetric))&&Number.isFinite(value(run,yMetric))).map((run)=>{ const cx=scale(value(run,xMetric),xmin,xmax,pad.l,width-pad.r,metricMeta[xMetric].better==="low"), cy=scale(value(run,yMetric),ymin,ymax,height-pad.b,pad.t,false); const active=activeId===run.runId; return <g key={run.runId} className={`grid-point ${active ? "is-active" : ""}`} tabIndex={0} role="button" aria-label={`${modelLabel(run.model)}, ${metricMeta[xMetric].label} ${display(run,xMetric)}, ${metricMeta[yMetric].label} ${display(run,yMetric)}`} onMouseEnter={()=>setHoveredId(run.runId)} onMouseLeave={()=>setHoveredId(null)} onFocus={()=>setHoveredId(run.runId)} onBlur={()=>setHoveredId(null)} onClick={(event)=>{event.stopPropagation();setPinnedId(pinnedId===run.runId?null:run.runId);}}><circle cx={cx} cy={cy} r={active?10:7} fill={colors[run.runId]}/>{active ? <GridPointTooltip run={run} xMetric={xMetric} yMetric={yMetric} cx={cx} cy={cy} width={width} /> : null}</g>;})}</svg></div>;
}

function niceExtent(values: number[], metric: Metric): readonly [number, number] {
  if (!values.length) return [0,1];
  const rawMin=Math.min(...values), rawMax=Math.max(...values);
  const baselineSpan=metric==="score"?10:Math.max(Math.abs(rawMax)*.2,1);
  const span=Math.max(rawMax-rawMin,baselineSpan);
  const paddedMin=rawMin-span*.12, paddedMax=rawMax+span*.12;
  const roughStep=(paddedMax-paddedMin)/4;
  const power=10**Math.floor(Math.log10(Math.max(roughStep,Number.EPSILON)));
  const fraction=roughStep/power;
  const step=(fraction<=1?1:fraction<=2?2:fraction<=5?5:10)*power;
  let min=Math.floor(paddedMin/step)*step, max=Math.ceil(paddedMax/step)*step;
  if (metric==="score") { min=Math.max(0,min); max=Math.min(120,max); }
  else if (rawMin>=0 && min<0) min=0;
  if (max<=min) max=min+step;
  return [min,max];
}

function GridPointTooltip({ run, xMetric, yMetric, cx, cy, width }: { run: BenchmarkRun; xMetric: Metric; yMetric: Metric; cx: number; cy: number; width: number }) {
  const label=modelLabel(run.model), boxWidth=Math.min(270,Math.max(170,label.length*8+24)), boxHeight=52;
  const preferredLeft=cx+boxWidth+16>width?cx-boxWidth-14:cx+14;
  const left=Math.min(width-boxWidth-8,Math.max(8,preferredLeft));
  const top=Math.max(8,cy-boxHeight/2);
  return <g className="grid-tooltip" pointerEvents="none"><rect x={left} y={top} width={boxWidth} height={boxHeight} rx={6}/><text x={left+11} y={top+19}><tspan className="grid-tooltip__title">{label}</tspan><tspan x={left+11} dy={18}>{metricMeta[xMetric].label} {display(run,xMetric)} · {metricMeta[yMetric].label} {display(run,yMetric)}</tspan></text></g>;
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}
