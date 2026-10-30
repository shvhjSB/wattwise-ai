import type { AlertDetail, AlertSummary, Feedback } from '../api/alerts';
import { HOUR, WINDOW_START } from './expectationFixture';

export function alertSummary(id = 1, overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    alert_id: id,
    meter_id: 'B1:electricity',
    building_id: 'B1',
    dataset_id: 'bdg2-cleaned-all',
    data_kind: 'observed',
    detector: 'rolling-z',
    start: new Date(WINDOW_START + 300 * HOUR).toISOString(),
    end: new Date(WINDOW_START + 310 * HOUR).toISOString(),
    duration_hours: 10,
    flagged_hours: 8,
    direction: 'high',
    signature: 'sustained',
    kind: 'above_expected',
    severity: 'high',
    priority_score: 82.4,
    potential_excess_kwh: 425.5,
    review_status: 'unreviewed',
    reviewed_at: null,
    feedback_count: 0,
    superseded: false,
    ...overrides,
  };
}

export function feedback(overrides: Partial<Feedback> = {}): Feedback {
  return {
    feedback_id: 9,
    alert_id: 1,
    label: 'needs_investigation',
    note: 'Check the air handler schedule.',
    reviewer: 'ops-1',
    created_at: '2017-08-01T10:00:00Z',
    ...overrides,
  };
}

export function alertDetail(overrides: Partial<AlertDetail> = {}): AlertDetail {
  const summary = alertSummary(overrides.alert_id ?? 1, overrides);
  return {
    ...summary,
    model_version: 'model-1',
    explanation:
      'Consumption stayed above its recent comparison and the model interval. This is an anomaly to investigate.',
    evidence: {
      detector: {
        name: 'rolling-z',
        baseline: 'its level at the same hour on the previous 14 days',
        observed_kwh: 1500,
        baseline_kwh: 1010,
        hours_compared: 10,
      },
      model: {
        observed_kwh: 1500,
        expected_kwh: 1000,
        hours_with_expectation: 10,
        interval: { nominal: 0.9, measured_coverage_in_detection_window: 0.872 },
        hours_above_upper_bound: 10,
        hours_below_lower_bound: 0,
        agrees_with_detector: true,
      },
      signature: {
        primary: 'sustained',
        all: ['sustained'],
        description: 'A persistent deviation over many hours.',
      },
      influences: [
        {
          feature: 'same_hour_mean_4w',
          description: 'Mean of the same hour in previous weeks.',
          mean_value: 98,
          mean_contribution_kwh: 12.5,
        },
      ],
      influences_note: 'Model associations, not causes.',
      check: 'Check the operating schedule and equipment overrides.',
    },
    feedback: [],
    caveats: [
      'An alert is an anomaly to investigate, not confirmed waste.',
      'The potential excess is an estimate above the model interval, not a verified saving.',
      'Model influences are associations, not causes.',
    ],
    retrained_from_feedback: false,
    ...overrides,
  };
}
