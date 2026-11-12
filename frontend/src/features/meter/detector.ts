/**
 * The default detector (D030), ported from `backend/src/wattwise/ml/detection.py` for the meter
 * check (T067): the rolling same-hour z-score and its hysteresis events. It runs in the browser on
 * hourly energy, so a meter file never leaves the user's computer.
 *
 * It must find exactly what Python finds: `detector.test.ts` runs it on
 * `detector-parity.json`, which `backend/tests/ml/test_detector_parity.py` generates from the
 * Python detector and checks. The arithmetic follows the Python order of operations.
 *
 * An event is an anomaly to investigate, not confirmed waste.
 */

export interface DetectorConfig {
  z_on: number;
  z_off: number;
  min_hours: number;
  z_spike: number;
  max_gap_hours: number;
  scale_floor_fraction: number;
}

/** The rolling z-score defaults (`DetectorConfig` with `DETECTOR_DEFAULTS[ROLLING_Z]`). */
export const DEFAULT_CONFIG: DetectorConfig = {
  z_on: 4,
  z_off: 2,
  min_hours: 3,
  z_spike: 8,
  max_gap_hours: 2,
  scale_floor_fraction: 0.01,
};
export const ROLLING_DAYS = 14;
export const ROLLING_MIN_DAYS = 7;
export const HOUR_MS = 3_600_000;

/** One hourly reading: the hour's start (UTC milliseconds) and its energy, or null if missing.
 * Hours with no row at all are not scanned, as in Python. */
export interface HourRow {
  t: number;
  value: number | null;
}

export interface DetectorEvent {
  direction: 'high' | 'low';
  start: number;
  end: number;
  duration_hours: number;
  flagged_hours: number;
  missing_hours: number;
  peak_time: number;
  peak_z: number;
  peak_residual: number;
  residual_sum: number;
  ongoing: boolean;
}

export interface Scores {
  start: number;
  values: Float64Array;
  mean: Float64Array;
  z: Float64Array;
  present: boolean[];
}

/** The hourly grid and each hour's z-score against the same hour on the previous 14 days
 * (`rolling_same_hour`, statistic "mean"). */
export function rollingSameHour(rows: readonly HourRow[], floorFraction = 0.01): Scores | null {
  if (!rows.length) return null;
  const sorted = [...rows].sort((a, b) => a.t - b.t);
  const start = sorted[0]?.t ?? 0;
  const endT = sorted[sorted.length - 1]?.t ?? start;
  const n = Math.round((endT - start) / HOUR_MS) + 1;
  const values = new Float64Array(n).fill(NaN);
  const present: boolean[] = new Array<boolean>(n).fill(false);
  for (const row of sorted) {
    const i = Math.round((row.t - start) / HOUR_MS);
    values[i] = row.value ?? NaN;
    present[i] = true;
  }
  const total = new Float64Array(n);
  const squares = new Float64Array(n);
  const count = new Float64Array(n);
  for (let d = 1; d <= ROLLING_DAYS; d += 1) {
    const lag = 24 * d;
    if (lag >= n) break;
    for (let i = lag; i < n; i += 1) {
      const past = values[i - lag] ?? NaN;
      if (!Number.isNaN(past)) {
        total[i] = (total[i] ?? 0) + past;
        squares[i] = (squares[i] ?? 0) + past * past;
        count[i] = (count[i] ?? 0) + 1;
      }
    }
  }
  const mean = new Float64Array(n);
  const z = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const c = count[i] ?? 0;
    const m = c >= ROLLING_MIN_DAYS ? (total[i] ?? 0) / Math.max(c, 1) : NaN;
    const variance = ((squares[i] ?? 0) - c * (m * m)) / Math.max(c - 1, 1);
    let std = Math.sqrt(Math.max(variance, 0));
    std = Math.max(std, Math.max(floorFraction * Math.abs(m), 1e-9));
    mean[i] = m;
    z[i] = ((values[i] ?? NaN) - m) / std;
  }
  return { start, values, mean, z, present };
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function scan(
  scores: Scores,
  sign: 1 | -1,
  direction: 'high' | 'low',
  config: DetectorConfig,
): DetectorEvent[] {
  const { values, mean, present, start: gridStart } = scores;
  const score = scores.z.map((v) => sign * v);
  const positions: number[] = [];
  present.forEach((isPresent, i) => {
    if (isPresent) positions.push(i);
  });
  const found: DetectorEvent[] = [];
  if (!positions.length) return found;
  const lastActive = positions[positions.length - 1] ?? 0;

  const close = (from: number, to: number, ongoing: boolean) => {
    let flagged = 0;
    let missing = 0;
    let total = 0;
    let peakValue = -Infinity;
    let peakAt = from;
    let peakResidual = NaN;
    for (let t = from; t <= to; t += 1) {
      const value = score[t] ?? NaN;
      if (Number.isNaN(value)) {
        missing += 1;
        continue;
      }
      const residual = (values[t] ?? NaN) - (mean[t] ?? NaN);
      if (value >= config.z_off) flagged += 1;
      total += residual;
      if (value > peakValue) {
        peakValue = value;
        peakAt = t;
        peakResidual = residual;
      }
    }
    if (flagged < config.min_hours && peakValue < config.z_spike) return;
    found.push({
      direction,
      start: gridStart + from * HOUR_MS,
      end: gridStart + (to + 1) * HOUR_MS,
      duration_hours: to - from + 1,
      flagged_hours: flagged,
      missing_hours: missing,
      peak_time: gridStart + peakAt * HOUR_MS,
      peak_z: round3(peakValue),
      peak_residual: round3(peakResidual),
      residual_sum: round3(total),
      ongoing,
    });
  };

  let open: number | null = null;
  let last = 0;
  for (const t of positions) {
    const value = score[t] ?? NaN;
    if (open === null) {
      if (value >= config.z_on) {
        open = t;
        last = t;
      }
      continue;
    }
    if (t - last > config.max_gap_hours + 1) {
      close(open, last, false);
      open = value >= config.z_on ? t : null;
      last = t;
      continue;
    }
    if (value >= config.z_off) last = t;
  }
  if (open !== null) close(open, last, lastActive - last <= config.max_gap_hours);
  return found;
}

/** Events above and below the baseline, by start time, then direction (as Python sorts them). */
export function detectEvents(
  rows: readonly HourRow[],
  config: DetectorConfig = DEFAULT_CONFIG,
): DetectorEvent[] {
  const scores = rollingSameHour(rows, config.scale_floor_fraction);
  if (scores === null) return [];
  return [...scan(scores, 1, 'high', config), ...scan(scores, -1, 'low', config)].sort(
    (a, b) => a.start - b.start || a.direction.localeCompare(b.direction),
  );
}
