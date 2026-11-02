import type { Page } from './catalog';
import { getJson } from './client';
import type { StoredKind } from './summary';

/** Mirrors `QualityCheck` in `backend/src/wattwise/data/quality.py`. */
export const QUALITY_CHECKS = [
  'gaps',
  'irregular_interval',
  'missing_values',
  'low_coverage',
  'negative_values',
  'zero_runs',
  'flatlines',
  'extreme_values',
  'implausible_intensity',
] as const;
export type QualityCheck = (typeof QUALITY_CHECKS)[number];

export interface QualityFinding {
  check: QualityCheck;
  severity: 'info' | 'warning';
  message: string;
  count: number;
  start: string | null;
  end: string | null;
}

export interface MeterQuality {
  meter_id: string;
  building_id: string;
  meter_type: string;
  unit: string;
  interval_minutes: number | null;
  first: string;
  last: string;
  expected_intervals: number;
  present_rows: number;
  absent_intervals: number;
  missing_values: number;
  available_values: number;
  coverage_pct: number;
  negative_values: number;
  zero_values: number;
  warnings: number;
  findings: QualityFinding[];
}

export interface QualitySummary {
  meters: number;
  rows: number;
  first: string;
  last: string;
  expected_intervals: number;
  available_values: number;
  coverage_pct: number;
  meters_with_warnings: number;
}

/** Mirrors `DatasetQualityOut` in `backend/src/wattwise/api/schemas/quality.py`. */
export interface DatasetQuality {
  available: true;
  dataset_id: string;
  name: string;
  data_kind: StoredKind;
  assessed_at: string;
  quality_version: string;
  contract_version: string;
  thresholds: Record<string, number>;
  summary: QualitySummary;
  checks: { check: QualityCheck; definition: string; meters: number }[];
  duplicates_note: string;
  uploads_note: string;
  meters: Page<MeterQuality>;
}

export interface QualityNotAssessed {
  available: false;
  dataset_id: string;
  name: string;
  data_kind: StoredKind;
  message: string;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const number = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const count = (value: unknown): value is number =>
  number(value) && Number.isInteger(value) && value >= 0;
const date = (value: unknown): value is string => text(value) && Number.isFinite(Date.parse(value));
const nullable =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is T | null =>
    value === null || guard(value);
const kind = (value: unknown): value is StoredKind => value === 'synthetic' || value === 'observed';
const check = (value: unknown): value is QualityCheck =>
  (QUALITY_CHECKS as readonly unknown[]).includes(value);

function isFinding(value: unknown): value is QualityFinding {
  return (
    record(value) &&
    check(value.check) &&
    (value.severity === 'info' || value.severity === 'warning') &&
    text(value.message) &&
    count(value.count) &&
    nullable(text)(value.start ?? null) &&
    nullable(text)(value.end ?? null)
  );
}

function isMeter(value: unknown): value is MeterQuality {
  return (
    record(value) &&
    ['meter_id', 'building_id', 'meter_type', 'unit', 'first', 'last'].every((key) =>
      text(value[key]),
    ) &&
    nullable(count)(value.interval_minutes) &&
    [
      'expected_intervals',
      'present_rows',
      'absent_intervals',
      'missing_values',
      'available_values',
      'negative_values',
      'zero_values',
      'warnings',
    ].every((key) => count(value[key])) &&
    number(value.coverage_pct) &&
    Array.isArray(value.findings) &&
    value.findings.every(isFinding)
  );
}

function isSummary(value: unknown): value is QualitySummary {
  return (
    record(value) &&
    ['meters', 'rows', 'expected_intervals', 'available_values', 'meters_with_warnings'].every(
      (key) => count(value[key]),
    ) &&
    text(value.first) &&
    text(value.last) &&
    number(value.coverage_pct)
  );
}

export function isDatasetQuality(value: unknown): value is DatasetQuality | QualityNotAssessed {
  if (!record(value) || !text(value.dataset_id) || !text(value.name) || !kind(value.data_kind)) {
    return false;
  }
  if (value.available === false) return text(value.message);
  const meters = value.meters;
  return (
    value.available === true &&
    date(value.assessed_at) &&
    text(value.quality_version) &&
    text(value.contract_version) &&
    record(value.thresholds) &&
    Object.values(value.thresholds).every(number) &&
    isSummary(value.summary) &&
    Array.isArray(value.checks) &&
    value.checks.every(
      (c) => record(c) && check(c.check) && text(c.definition) && count(c.meters),
    ) &&
    text(value.duplicates_note) &&
    text(value.uploads_note) &&
    record(meters) &&
    count(meters.total) &&
    count(meters.limit) &&
    count(meters.offset) &&
    Array.isArray(meters.items) &&
    meters.items.every(isMeter)
  );
}

export interface QualityQuery {
  check: QualityCheck | null;
  warningsOnly: boolean;
  offset: number;
}

export const QUALITY_PAGE = 25;

export function fetchDatasetQuality(
  datasetId: string,
  query: QualityQuery,
  signal?: AbortSignal,
): Promise<DatasetQuality | QualityNotAssessed> {
  const params = new URLSearchParams({
    limit: String(QUALITY_PAGE),
    offset: String(query.offset),
  });
  if (query.check) params.set('check', query.check);
  if (query.warningsOnly) params.set('warnings_only', 'true');
  return getJson(
    `/api/v1/datasets/${encodeURIComponent(datasetId)}/quality?${params.toString()}`,
    isDatasetQuality,
    signal ? { signal } : {},
  );
}
