import { getJson } from './client';

/** Where data comes from. `uploaded` is never stored; it labels analysis results. */
export type DataKind = 'synthetic' | 'observed' | 'uploaded';
export type StoredKind = 'synthetic' | 'observed';

/** Mirrors `AlertTotals` in `backend/src/wattwise/api/schemas/catalog.py`. */
export interface AlertTotals {
  alerts: number;
  open: number;
  high_severity: number;
  by_review_status: Record<string, number>;
  by_kind: Record<string, number>;
  potential_excess_kwh: number;
  observed_kwh_in_alerts: number;
  expected_kwh_in_alerts: number;
}

/** Mirrors `KindSummary`: totals for the datasets of one kind. Kinds are never added together. */
export interface KindSummary {
  kind: StoredKind;
  datasets: number;
  buildings: number;
  meters: number;
  readings: number;
  missing_values: number;
  missing_share: number | null;
  first_reading: string | null;
  last_reading: string | null;
  measured_kwh: number;
  alerts: AlertTotals;
}

/** The parts of `DashboardSummary` the application uses. */
export interface DashboardSummary {
  data_kinds: StoredKind[];
  by_kind: KindSummary[];
}

const STORED_KINDS: readonly unknown[] = ['synthetic', 'observed'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCountMap(value: unknown): value is Record<string, number> {
  return isRecord(value) && Object.values(value).every((n) => typeof n === 'number');
}

function isNumberOrNull(value: unknown): value is number | null {
  return value === null || typeof value === 'number';
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

export function isAlertTotals(value: unknown): value is AlertTotals {
  return (
    isRecord(value) &&
    typeof value.alerts === 'number' &&
    typeof value.open === 'number' &&
    typeof value.high_severity === 'number' &&
    isCountMap(value.by_review_status) &&
    isCountMap(value.by_kind) &&
    typeof value.potential_excess_kwh === 'number' &&
    typeof value.observed_kwh_in_alerts === 'number' &&
    typeof value.expected_kwh_in_alerts === 'number'
  );
}

export function isKindSummary(value: unknown): value is KindSummary {
  return (
    isRecord(value) &&
    STORED_KINDS.includes(value.kind) &&
    typeof value.datasets === 'number' &&
    typeof value.buildings === 'number' &&
    typeof value.meters === 'number' &&
    typeof value.readings === 'number' &&
    typeof value.missing_values === 'number' &&
    isNumberOrNull(value.missing_share) &&
    isStringOrNull(value.first_reading) &&
    isStringOrNull(value.last_reading) &&
    typeof value.measured_kwh === 'number' &&
    isAlertTotals(value.alerts)
  );
}

export function isDashboardSummary(value: unknown): value is DashboardSummary {
  return (
    isRecord(value) &&
    Array.isArray(value.data_kinds) &&
    value.data_kinds.every((kind) => STORED_KINDS.includes(kind)) &&
    Array.isArray(value.by_kind) &&
    value.by_kind.every(isKindSummary)
  );
}

/** Totals of the stored data, from `GET /api/v1/dashboard/summary`. */
export function fetchSummary(signal?: AbortSignal): Promise<DashboardSummary> {
  return getJson('/api/v1/dashboard/summary', isDashboardSummary, signal ? { signal } : {});
}
