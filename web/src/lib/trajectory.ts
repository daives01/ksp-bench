import type { BenchmarkRun } from "@/types";

export type AltitudePoint = { t: number; alt: number };

const KERBIN_RADIUS_M = 600_000;
const KERBIN_MU = 3.5316e12;
const KERBIN_SURFACE_GRAVITY = KERBIN_MU / KERBIN_RADIUS_M ** 2;

/** Continue a trace from its last observed point without presenting predictions as telemetry. */
export function projectedAltitude(run: BenchmarkRun, points: AltitudePoint[]): AltitudePoint[] {
  if (points.length < 2) return [];
  return run.diagnostics.stable_orbit
    ? orbitalProjection(run, points.at(-1)!)
    : ballisticProjection(points);
}

function orbitalProjection(run: BenchmarkRun, last: AltitudePoint): AltitudePoint[] {
  const apo = run.finalOrbit.apoapsis_m;
  const peri = run.finalOrbit.periapsis_m;
  if (!(peri >= 0 && apo >= peri)) return [];

  const semiMajorAxis = KERBIN_RADIUS_M + (apo + peri) / 2;
  const period = 2 * Math.PI * Math.sqrt(semiMajorAxis ** 3 / KERBIN_MU);
  if (!Number.isFinite(period) || period <= 0) return [];

  const midpoint = (apo + peri) / 2;
  const amplitude = (apo - peri) / 2;
  const timeToApo = normalizedFutureTime(run.finalOrbit.time_to_apoapsis_s, period);
  const angularRate = 2 * Math.PI / period;
  const altitudeRatio = amplitude > 0 ? clamp((last.alt - midpoint) / amplitude, -1, 1) : 1;
  const phaseMagnitude = Math.acos(altitudeRatio);
  const phases = [phaseMagnitude, 2 * Math.PI - phaseMagnitude];
  const startPhase = phases.reduce((best, candidate) => {
    const candidateTimeToApo = normalizedFutureTime(-candidate / angularRate, period);
    const bestTimeToApo = normalizedFutureTime(-best / angularRate, period);
    return circularDistance(candidateTimeToApo, timeToApo, period) < circularDistance(bestTimeToApo, timeToApo, period)
      ? candidate
      : best;
  });
  const count = 120;
  return Array.from({ length: count + 1 }, (_, index) => {
    const elapsed = period * index / count;
    // Radius is not exactly sinusoidal in time for an eccentric orbit, but this
    // starts at the observed altitude and reaches both apsides at the right period.
    return { t: last.t + elapsed, alt: midpoint + amplitude * Math.cos(startPhase + angularRate * elapsed) };
  });
}

function ballisticProjection(points: AltitudePoint[]): AltitudePoint[] {
  const last = points.at(-1)!;
  let lookback = points.at(-2)!;
  for (let index = points.length - 2; index >= 0; index -= 1) {
    if (points[index].t <= last.t - 5) {
      lookback = points[index];
      break;
    }
  }
  const dt = Math.max(last.t - lookback.t, 0.1);
  const verticalSpeed = (last.alt - lookback.alt) / dt;
  const impactTime = positiveImpactTime(last.alt, verticalSpeed);
  if (!Number.isFinite(impactTime) || impactTime <= 0) return [];

  const duration = Math.min(impactTime, 20 * 60);
  const count = Math.max(24, Math.ceil(duration / 5));
  return Array.from({ length: count + 1 }, (_, index) => {
    const elapsed = duration * index / count;
    const altitude = last.alt + verticalSpeed * elapsed - 0.5 * KERBIN_SURFACE_GRAVITY * elapsed ** 2;
    return { t: last.t + elapsed, alt: Math.max(0, altitude) };
  });
}

function positiveImpactTime(altitude: number, verticalSpeed: number) {
  return (verticalSpeed + Math.sqrt(verticalSpeed ** 2 + 2 * KERBIN_SURFACE_GRAVITY * Math.max(0, altitude))) / KERBIN_SURFACE_GRAVITY;
}

function normalizedFutureTime(value: number, period: number) {
  if (!Number.isFinite(value)) return period / 2;
  return ((value % period) + period) % period;
}

function circularDistance(a: number, b: number, period: number) {
  const distance = Math.abs(a - b);
  return Math.min(distance, period - distance);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
