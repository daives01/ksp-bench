export function formatMeters(value: number) {
  if (!Number.isFinite(value)) return "n/a";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} Mm`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)} km`;
  return `${Math.round(value)} m`;
}

export function formatSeconds(value: number) {
  if (!Number.isFinite(value)) return "n/a";
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function formatCost(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "not reported";
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatDeltaV(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "not captured";
  return `${Math.round(value)} m/s`;
}

export function modelLabel(model: string) {
  return model.replace(/^opencode\//, "").replace(/^openai\//, "");
}

export function runOutcome(run: {
  diagnostics: {
    stable_orbit: boolean;
    reached_space: boolean;
    reached_10km: boolean;
    cleared_tower: boolean;
  };
}) {
  if (run.diagnostics.stable_orbit) return "Reached orbit";
  if (run.diagnostics.reached_space) return "Suborbital flight";
  if (run.diagnostics.reached_10km) return "Reached upper atmosphere";
  if (run.diagnostics.cleared_tower) return "Cleared launch tower";
  return "Did not leave launch pad";
}
