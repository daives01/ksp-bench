import { useEffect, useMemo, useState } from "react";
import { formatCost, formatSeconds, modelLabel } from "@/lib/format";
import { loadFlightTrace } from "@/lib/data";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { BenchmarkRun, FlightTrace } from "@/types";

const COLORS = ["#95e6b8", "#5ac8fa", "#ff8d5c", "#d9a7ff", "#f7d154", "#ff86b9", "#70d6c1", "#b7b7ff"];
type Metric = "score" | "time" | "cost" | "tokens";
type Point = { t: number; alt: number };

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
  const alt = trace.columns.indexOf("alt"), time = trace.columns.indexOf("t");
  return trace.points.map((row) => ({ t: Number(row[time] ?? 0), alt: Number(row[alt] ?? 0) })).filter((point) => Number.isFinite(point.t) && Number.isFinite(point.alt));
}

export function ResultsView({ runs }: { runs: BenchmarkRun[] }) {
  const [metric, setMetric] = useState<Metric>("score");
  const [xMetric, setXMetric] = useState<Metric>("cost");
  const [yMetric, setYMetric] = useState<Metric>("score");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [traces, setTraces] = useState<Record<string, FlightTrace>>({});
  const colors = useMemo(() => Object.fromEntries(runs.map((run, index) => [run.runId, COLORS[index % COLORS.length]])), [runs]);
  const rankedRuns = useMemo(() => [...runs].sort((a, b) => {
    const delta = value(a, metric) - value(b, metric);
    return metricMeta[metric].better === "high" ? -delta : delta;
  }), [runs, metric]);

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
  const metricMax = Math.max(...rankedRuns.map((run) => Number.isFinite(value(run, metric)) ? value(run, metric) : 0), 1);
  const chartTraces = runs.flatMap((run) => {
    const trace = traces[run.runId]; const points = trace && pointsFor(trace);
    return points?.length ? [{ run, points, color: colors[run.runId] }] : [];
  });

  return <section className="unified-bench">
    <div className="unified-bench__layout">
      <section className="mission-panel leaderboard-panel">
        <div className="panel-head"><h2>Leaderboard</h2><MetricControl value={metric} onChange={setMetric} /></div>
        <div className="leaderboard-list">
          {rankedRuns.map((run, index) => {
            const v = value(run, metric), bar = Number.isFinite(v) ? Math.max(3, v / metricMax * 100) : 0;
            const focused = activeId === run.runId;
            return <button key={`${metric}-${run.runId}`} className={`leaderboard-row ${focused ? "is-active" : ""}`} style={{ animationDelay: `${index * 36}ms` }} onMouseEnter={() => setActiveId(run.runId)} onMouseLeave={() => setActiveId(null)} onFocus={() => setActiveId(run.runId)} onBlur={() => setActiveId(null)} onClick={() => setActiveId(activeId === run.runId ? null : run.runId)}>
              <span className="leaderboard-rank">{String(index + 1).padStart(2, "0")}</span><span className="leaderboard-color" style={{ background: colors[run.runId] }} />
              <span className="leaderboard-name"><strong>{modelLabel(run.model)}</strong></span>
              <span className="leaderboard-bar"><i style={{ width: `${bar}%`, background: colors[run.runId] }} /></span><strong className="leaderboard-value">{display(run, metric)}</strong>
            </button>;
          })}
        </div>
      </section>
      <section className="mission-panel flight-panel">
        <div className="panel-head"><h2>Altitude</h2><span className="target-label">80 km</span></div>
        {chartTraces.length ? <AltitudeChart traces={chartTraces} activeId={activeId} /> : <div className="chart-loading">Loading telemetry…</div>}
      </section>
    </div>
    <section className="mission-panel grid-panel">
      <div className="panel-head"><h2>Compare</h2></div>
      <TradeoffGrid runs={runs} colors={colors} xMetric={xMetric} yMetric={yMetric} activeId={activeId} setActiveId={setActiveId} setXMetric={setXMetric} setYMetric={setYMetric} />
    </section>
  </section>;
}

function MetricControl({ value, onChange }: { value: Metric; onChange: (value: Metric) => void }) { return <Select value={value} onValueChange={(next: string) => onChange(next as Metric)}><SelectTrigger className="metric-control"><SelectValue /></SelectTrigger><SelectContent>{(Object.keys(metricMeta) as Metric[]).map((key) => <SelectItem key={key} value={key}>{metricMeta[key].label} · {metricMeta[key].unit}</SelectItem>)}</SelectContent></Select>; }

function AltitudeChart({ traces, activeId }: { traces: { run: BenchmarkRun; points: Point[]; color: string }[]; activeId: string | null }) {
  const width = 960, height = 355, pad = { l: 48, r: 18, t: 18, b: 36 };
  const maxTime = Math.max(...traces.flatMap(({ points }) => points.map((p) => p.t)), 1), maxAlt = Math.max(100000, ...traces.flatMap(({ points }) => points.map((p) => p.alt)));
  const x = (v: number) => pad.l + v / maxTime * (width - pad.l - pad.r), y = (v: number) => height - pad.b - Math.max(0, v) / maxAlt * (height - pad.t - pad.b);
  const path = (points: Point[]) => points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.alt).toFixed(1)}`).join(" ");
  return <div className="altitude-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="All flight altitudes over mission time"><text className="axis-title" transform={`translate(13 ${(pad.t+height-pad.b)/2}) rotate(-90)`} textAnchor="middle">Altitude · km</text>{[0, .25, .5, .75, 1].map((tick) => <g key={tick}><line className="chart-grid" x1={pad.l} x2={width-pad.r} y1={y(maxAlt*tick)} y2={y(maxAlt*tick)} /><text className="chart-tick" x={pad.l-8} y={y(maxAlt*tick)+3} textAnchor="end">{Math.round(maxAlt*tick/1000)}</text><text className="chart-tick" x={x(maxTime*tick)} y={height-10} textAnchor="middle">{formatSeconds(maxTime*tick)}</text></g>)}<text className="axis-title" x={(pad.l+width-pad.r)/2} y={height-1} textAnchor="middle">Mission time</text><line className="chart-target" x1={pad.l} x2={width-pad.r} y1={y(80000)} y2={y(80000)} />{traces.map(({run, points, color}, index) => <path key={run.runId} d={path(points)} stroke={color} className={`chart-line chart-line--draw ${activeId && activeId !== run.runId ? "is-dimmed" : ""} ${activeId === run.runId ? "is-focused" : ""}`} style={{ animationDelay: `${index * 90}ms` }} />)}</svg></div>;
}

function TradeoffGrid({ runs, colors, xMetric, yMetric, activeId, setActiveId, setXMetric, setYMetric }: { runs: BenchmarkRun[]; colors: Record<string, string>; xMetric: Metric; yMetric: Metric; activeId: string | null; setActiveId: (id: string | null) => void; setXMetric: (metric: Metric) => void; setYMetric: (metric: Metric) => void }) {
  const width=960, height=310, pad={l:54,r:22,t:20,b:48}; const finite = (metric: Metric) => runs.map((run) => value(run,metric)).filter(Number.isFinite);
  const extent = (metric: Metric) => { const values=finite(metric); return [Math.min(...values,0), Math.max(...values,1)] as const; }; const [xmin,xmax]=extent(xMetric), [ymin,ymax]=extent(yMetric);
  const scale=(v:number,min:number,max:number,start:number,end:number,invert=false) => start + ((invert ? max-v : v-min) / Math.max(max-min, 1)) * (end-start);
  return <div className="tradeoff-grid"><div className="axis-control axis-control--y"><MetricControl value={yMetric} onChange={setYMetric} /><span>{metricMeta[yMetric].unit} · best ↑</span></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metricMeta[xMetric].label} by ${metricMeta[yMetric].label} grid`}><rect x={pad.l} y={pad.t} width={width-pad.l-pad.r} height={height-pad.t-pad.b} className="grid-box" />{[.25,.5,.75].map((tick)=><g key={tick}><line className="chart-grid" x1={pad.l+(width-pad.l-pad.r)*tick} x2={pad.l+(width-pad.l-pad.r)*tick} y1={pad.t} y2={height-pad.b}/><line className="chart-grid" x1={pad.l} x2={width-pad.r} y1={pad.t+(height-pad.t-pad.b)*tick} y2={pad.t+(height-pad.t-pad.b)*tick}/></g>)}{runs.filter((run)=>Number.isFinite(value(run,xMetric))&&Number.isFinite(value(run,yMetric))).map((run)=>{ const cx=scale(value(run,xMetric),xmin,xmax,pad.l,width-pad.r,metricMeta[xMetric].better==="low"), cy=scale(value(run,yMetric),ymin,ymax,height-pad.b,pad.t,metricMeta[yMetric].better==="high"); const active=activeId===run.runId; return <g key={run.runId} className={`grid-point ${active ? "is-active" : ""}`} onMouseEnter={()=>setActiveId(run.runId)} onMouseLeave={()=>setActiveId(null)} onClick={()=>setActiveId(active ? null : run.runId)}><circle cx={cx} cy={cy} r={active?10:6} fill={colors[run.runId]}/><text x={cx+10} y={cy+4}>{modelLabel(run.model)}</text></g>;})}</svg><div className="axis-control axis-control--x"><MetricControl value={xMetric} onChange={setXMetric} /><span>{metricMeta[xMetric].unit} · best →</span></div></div>;
}
