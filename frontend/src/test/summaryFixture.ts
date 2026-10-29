import type { AlertTotals, DashboardSummary, KindSummary, StoredKind } from '../api/summary';

export function alertTotals(overrides: Partial<AlertTotals> = {}): AlertTotals {
  return {
    alerts: 0,
    open: 0,
    high_severity: 0,
    by_review_status: {},
    by_kind: {},
    potential_excess_kwh: 0,
    observed_kwh_in_alerts: 0,
    expected_kwh_in_alerts: 0,
    ...overrides,
  };
}

export function kindSummary(kind: StoredKind, overrides: Partial<KindSummary> = {}): KindSummary {
  return {
    kind,
    datasets: 1,
    buildings: 4,
    meters: 4,
    readings: 5376,
    missing_values: 6,
    missing_share: 6 / 5376,
    first_reading: '2016-01-04T00:00:00Z',
    last_reading: '2016-02-28T23:00:00Z',
    measured_kwh: 506730.041,
    alerts: alertTotals(),
    ...overrides,
  };
}

export function summaryOf(...kinds: KindSummary[]): DashboardSummary {
  return { data_kinds: kinds.map((k) => k.kind).sort(), by_kind: kinds };
}

/** A realistic observed summary with alerts (the shape and scale of the full-scale data). */
export const OBSERVED_WITH_ALERTS = kindSummary('observed', {
  datasets: 1,
  buildings: 1148,
  meters: 1148,
  readings: 20_137_056,
  missing_values: 1_187_658,
  missing_share: 1_187_658 / 20_137_056,
  first_reading: '2016-01-01T00:00:00Z',
  last_reading: '2018-01-01T07:00:00Z',
  measured_kwh: 2_872_660_506.2,
  alerts: alertTotals({
    alerts: 5546,
    open: 5546,
    high_severity: 232,
    by_review_status: { unreviewed: 5546 },
    by_kind: { above_expected: 3141, below_expected: 1943, meter_problem: 462 },
    potential_excess_kwh: 558_721.9,
    observed_kwh_in_alerts: 7_057_517.1,
    expected_kwh_in_alerts: 6_757_676.3,
  }),
});
