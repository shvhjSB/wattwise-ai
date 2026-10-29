import type {
  Building,
  ExpectationPoint,
  ExpectationSeries,
  Meter,
  MeterAlert,
} from '../api/catalog';

export const HOUR = 3_600_000;
export const WINDOW_START = Date.UTC(2017, 6, 1);
export const HOURS = 30 * 24;

/**
 * Thirty days of hourly points: expectation 100, interval 90-110 from hour 24, observed 100
 * except a spike of 150 over hours 300-309 (outside the interval) and one missing reading at
 * hour 50.
 */
export function points(hours = HOURS): ExpectationPoint[] {
  return Array.from({ length: hours }, (_, i) => ({
    timestamp: new Date(WINDOW_START + i * HOUR).toISOString(),
    observed: i === 50 ? null : i >= 300 && i < 310 ? 150 : 100,
    expected: 100,
    lower: i >= 24 ? 90 : null,
    upper: i >= 24 ? 110 : null,
  }));
}

export function series(overrides: Partial<ExpectationSeries> = {}): ExpectationSeries {
  const all = points();
  return {
    meter_id: 'B1:electricity',
    unit: 'kWh',
    data_kind: 'observed',
    available: true,
    reason: null,
    message: null,
    meta: {
      model_version: 'model-1',
      interval_nominal: 0.9,
      measured_coverage: 0.872,
      window_start: all[0]?.timestamp ?? '',
      window_end: new Date(WINDOW_START + HOURS * HOUR).toISOString(),
      detection_start: new Date(WINDOW_START + 10 * 24 * HOUR).toISOString(),
      first_interval: all[24]?.timestamp ?? null,
    },
    points: all,
    truncated: false,
    caveats: ['The expectation is the model’s estimate, not a target.'],
    ...overrides,
  };
}

export function alertAt(
  id: number,
  startHour: number,
  endHour: number,
  score = 50,
  overrides: Partial<MeterAlert> = {},
): MeterAlert {
  return {
    alert_id: id,
    start: new Date(WINDOW_START + startHour * HOUR).toISOString(),
    end: new Date(WINDOW_START + endHour * HOUR).toISOString(),
    severity: score >= 60 ? 'high' : score >= 40 ? 'medium' : 'low',
    signature: 'sustained',
    kind: 'above_expected',
    priority_score: score,
    review_status: 'unreviewed',
    ...overrides,
  };
}

export function building(id: string, overrides: Partial<Building> = {}): Building {
  return {
    building_id: id,
    dataset_id: 'bdg2-cleaned-all',
    data_kind: 'observed',
    site_id: 'Site',
    timezone: 'America/New_York',
    primary_use: 'Education',
    floor_area_m2: null,
    meter_count: 1,
    ...overrides,
  };
}

export function meter(id: string, buildingId: string, overrides: Partial<Meter> = {}): Meter {
  return {
    meter_id: id,
    building_id: buildingId,
    dataset_id: 'bdg2-cleaned-all',
    data_kind: 'observed',
    meter_type: 'electricity',
    unit: 'kWh',
    ...overrides,
  };
}

export function page<T>(items: T[], total = items.length, limit = 20, offset = 0) {
  return { items, total, limit, offset };
}
