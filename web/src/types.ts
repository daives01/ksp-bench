export type TelemetrySample = {
  mission_elapsed_s: number;
  altitude_m: number;
  surface_altitude_m?: number;
  apoapsis_m: number;
  periapsis_m: number;
  surface_speed_m_s?: number;
  orbital_speed_m_s: number;
  vertical_speed_m_s?: number;
  pitch_deg?: number;
  heading_deg?: number;
  roll_deg?: number;
  stage?: number;
  liquid_fuel?: number;
  oxidizer?: number;
  solid_fuel?: number;
  dynamic_pressure_pa?: number;
  situation: string;
  body: string;
  controllable?: boolean;
  intact?: boolean;
  time_to_apoapsis_s?: number;
  time_to_periapsis_s?: number;
  eccentricity: number;
  inclination_deg: number;
  latitude_deg?: number | null;
  longitude_deg?: number | null;
};

/** A small, browser-facing trace. `points` use the names in `columns`. */
export type FlightTrace = {
  schemaVersion?: number;
  intervalS?: number;
  columns: string[];
  points: Array<Array<number | null>>;
  events?: Array<{
    t: number;
    alt: number;
    type: string;
    label: string;
    ok: boolean;
  }>;
};

export type BenchmarkRun = {
  runId: string;
  createdAt?: string;
  model: string;
  thinkingLevel?: string | null;
  adapter?: string;
  score: number;
  benchmarkVersion: string;
  harnessVersion: string;
  instanceId: string;
  finalOrbit: {
    body: string;
    situation: string;
    apoapsis_m: number;
    periapsis_m: number;
    target_altitude_m: number;
    orbit_error_m: number;
    eccentricity: number;
    inclination_deg: number;
    orbital_speed_m_s: number;
    time_to_apoapsis_s: number;
    time_to_periapsis_s: number;
  };
  fuelRemaining: {
    liquid_fuel: number;
    oxidizer: number;
    solid_fuel: number;
  };
  remainingDeltaVMs?: number | null;
  time: {
    /** Actual harness duration. Null means this is a legacy artifact. */
    wall_clock_elapsed_s?: number | null;
    /** KSP mission elapsed time; it may be accelerated by in-game warp. */
    mission_elapsed_s: number;
    agent_timeout_s?: number;
  };
  diagnostics: {
    max_altitude_m: number;
    max_apoapsis_m: number;
    max_periapsis_m: number;
    cleared_tower: boolean;
    reached_10km: boolean;
    reached_space: boolean;
    stable_orbit: boolean;
    invalid_actions: number;
    action_count: number;
    intact: boolean;
    controllable: boolean;
    outcome?: string;
    failure_category?: string | null;
    termination_reason?: string | null;
    tool_errors?: number;
    recoverable_tool_errors?: number;
    policy_violations?: number;
    flight_termination_errors?: number;
  };
  usage?: {
    cost_usd: number | null;
    cost_kind?: "api_equivalent" | "reported" | null;
    pricing_model?: string | null;
    pricing_source?: string | null;
    input_tokens: number | null;
    cached_input_tokens?: number | null;
    cache_write_tokens?: number | null;
    output_tokens: number | null;
    reasoning_tokens?: number | null;
    total_tokens: number | null;
  };
  flightUrl?: string;
  detailUrl?: string;
  flight?: FlightTrace;
  /** Legacy public datasets. Normalized to `flight` while loading. */
  telemetry?: TelemetrySample[];
};

export type BenchmarkDataset = {
  generatedAt: string;
  sourceRoot: string;
  benchmarkVersion: string;
  runs: BenchmarkRun[];
};
