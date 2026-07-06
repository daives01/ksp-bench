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
};

export type BenchmarkRun = {
  runId: string;
  createdAt?: string;
  model: string;
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
  time: {
    mission_elapsed_s: number;
    timeout_s: number;
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
  };
  usage?: {
    cost_usd: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
  };
  telemetry: TelemetrySample[];
};

export type BenchmarkDataset = {
  generatedAt: string;
  sourceRoot: string;
  runs: BenchmarkRun[];
};
