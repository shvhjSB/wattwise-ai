import { getJson } from './client';
import type { StoredKind } from './summary';

const STORED_KINDS: readonly unknown[] = ['synthetic', 'observed'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
const isString = (value: unknown): value is string => typeof value === 'string';
const isNumber = (value: unknown): value is number => typeof value === 'number';
const isNullable =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is T | null =>
    value === null || guard(value);

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

function isPage<T>(item: (value: unknown) => value is T) {
  return (value: unknown): value is Page<T> =>
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(item) &&
    isNumber(value.total) &&
    isNumber(value.limit) &&
    isNumber(value.offset);
}

// -- buildings and meters ---------------------------------------------------------------------

/** Mirrors `BuildingOut` in `backend/src/wattwise/api/schemas/catalog.py`. */
export interface Building {
  building_id: string;
  dataset_id: string;
  data_kind: StoredKind;
  site_id: string;
  timezone: string;
  primary_use: string | null;
  floor_area_m2: number | null;
  meter_count: number;
}

export function isBuilding(value: unknown): value is Building {
  return (
    isRecord(value) &&
    isString(value.building_id) &&
    isString(value.dataset_id) &&
    STORED_KINDS.includes(value.data_kind) &&
    isString(value.site_id) &&
    isString(value.timezone) &&
    isNullable(isString)(value.primary_use) &&
    isNullable(isNumber)(value.floor_area_m2) &&
    isNumber(value.meter_count)
  );
}

/** Mirrors `MeterOut`. */
export interface Meter {
  meter_id: string;
  building_id: string;
  dataset_id: string;
  data_kind: StoredKind;
  meter_type: string;
  unit: string;
}

export function isMeter(value: unknown): value is Meter {
  return (
    isRecord(value) &&
    isString(value.meter_id) &&
    isString(value.building_id) &&
    isString(value.dataset_id) &&
    STORED_KINDS.includes(value.data_kind) &&
    isString(value.meter_type) &&
    isString(value.unit)
  );
}

export function fetchBuildings(
  params: { q?: string; limit: number; offset: number },
  signal?: AbortSignal,
): Promise<Page<Building>> {
  const query = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.q) query.set('q', params.q);
  return getJson(
    `/api/v1/buildings?${query.toString()}`,
    isPage(isBuilding),
    signal ? { signal } : {},
  );
}

export function fetchMeters(buildingId: string, signal?: AbortSignal): Promise<Page<Meter>> {
  const query = new URLSearchParams({ building_id: buildingId, limit: '200' });
  return getJson(`/api/v1/meters?${query.toString()}`, isPage(isMeter), signal ? { signal } : {});
}

export function fetchMeter(meterId: string, signal?: AbortSignal): Promise<Meter> {
  return getJson(
    `/api/v1/meters/${encodeURIComponent(meterId)}`,
    isMeter,
    signal ? { signal } : {},
  );
}

// -- expectation ------------------------------------------------------------------------------

export type ExpectationUnavailable = 'no_expectation_stored' | 'outside_evaluation_window';

export interface ExpectationMeta {
  model_version: string;
  interval_nominal: number;
  measured_coverage: number | null;
  window_start: string;
  window_end: string;
  detection_start: string;
  first_interval: string | null;
}

export interface ExpectationPoint {
  timestamp: string;
  observed: number | null;
  expected: number | null;
  lower: number | null;
  upper: number | null;
}

/** Mirrors `ExpectationSeries`. */
export interface ExpectationSeries {
  meter_id: string;
  unit: string;
  data_kind: StoredKind;
  available: boolean;
  reason: ExpectationUnavailable | null;
  message: string | null;
  meta: ExpectationMeta | null;
  points: ExpectationPoint[];
  truncated: boolean;
  caveats: string[];
}

const isNullableNumber = isNullable(isNumber);

function isMeta(value: unknown): value is ExpectationMeta {
  return (
    isRecord(value) &&
    isString(value.model_version) &&
    isNumber(value.interval_nominal) &&
    isNullableNumber(value.measured_coverage) &&
    isString(value.window_start) &&
    isString(value.window_end) &&
    isString(value.detection_start) &&
    isNullable(isString)(value.first_interval)
  );
}

function isPoint(value: unknown): value is ExpectationPoint {
  return (
    isRecord(value) &&
    isString(value.timestamp) &&
    isNullableNumber(value.observed) &&
    isNullableNumber(value.expected) &&
    isNullableNumber(value.lower) &&
    isNullableNumber(value.upper)
  );
}

export function isExpectationSeries(value: unknown): value is ExpectationSeries {
  return (
    isRecord(value) &&
    isString(value.meter_id) &&
    isString(value.unit) &&
    STORED_KINDS.includes(value.data_kind) &&
    typeof value.available === 'boolean' &&
    isNullable(isString)(value.reason) &&
    isNullable(isString)(value.message) &&
    (value.meta === null || isMeta(value.meta)) &&
    Array.isArray(value.points) &&
    value.points.every(isPoint) &&
    typeof value.truncated === 'boolean' &&
    Array.isArray(value.caveats) &&
    value.caveats.every(isString)
  );
}

/** The meter's whole evaluation window, fetched once; the explorer pans and zooms client-side. */
export function fetchExpectation(
  meterId: string,
  signal?: AbortSignal,
): Promise<ExpectationSeries> {
  const query = new URLSearchParams({ limit: '50000' });
  return getJson(
    `/api/v1/meters/${encodeURIComponent(meterId)}/expectation?${query.toString()}`,
    isExpectationSeries,
    signal ? { signal } : {},
  );
}

// -- alerts on a meter ------------------------------------------------------------------------

export type Severity = 'high' | 'medium' | 'low';

/** The part of `AlertSummary` the explorer draws. */
export interface MeterAlert {
  alert_id: number;
  start: string;
  end: string;
  severity: Severity;
  signature: string;
  kind: string;
  priority_score: number;
  review_status: string;
}

export function isMeterAlert(value: unknown): value is MeterAlert {
  return (
    isRecord(value) &&
    isNumber(value.alert_id) &&
    isString(value.start) &&
    isString(value.end) &&
    (value.severity === 'high' || value.severity === 'medium' || value.severity === 'low') &&
    isString(value.signature) &&
    isString(value.kind) &&
    isNumber(value.priority_score) &&
    isString(value.review_status)
  );
}

export function fetchMeterAlerts(meterId: string, signal?: AbortSignal): Promise<Page<MeterAlert>> {
  const query = new URLSearchParams({ meter_id: meterId, limit: '200' });
  return getJson(
    `/api/v1/alerts?${query.toString()}`,
    isPage(isMeterAlert),
    signal ? { signal } : {},
  );
}
