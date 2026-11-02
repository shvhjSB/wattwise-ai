import type { Page } from './catalog';
import { getJson } from './client';
import type { StoredKind } from './summary';

export type DriftPeriod = 'week' | 'month';

export interface PeriodDrift {
  start: string;
  readings: number;
  meters: number;
  median_level_ratio: number | null;
  wape: number | null;
  bias: number | null;
  coverage: number | null;
}

export interface MeterDrift {
  meter_id: string;
  readings: number;
  level_ratio: number | null;
  wape: number | null;
  coverage: number | null;
}

/** Mirrors `DriftOut` in `backend/src/wattwise/api/schemas/drift.py`. */
export interface Drift {
  available: true;
  dataset_id: string;
  data_kind: StoredKind;
  datasets: string[];
  model_version: string;
  interval_nominal: number;
  period: DriftPeriod;
  reference_end: string;
  window_start: string;
  window_end: string;
  periods: PeriodDrift[];
  latest_period: string | null;
  meters: Page<MeterDrift>;
  definitions: Record<string, string>;
  note: string;
}

export interface DriftUnavailable {
  available: false;
  message: string;
  datasets: string[];
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
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);

function isPeriod(value: unknown): value is PeriodDrift {
  return (
    record(value) &&
    date(value.start) &&
    count(value.readings) &&
    count(value.meters) &&
    ['median_level_ratio', 'wape', 'bias', 'coverage'].every((key) => nullable(number)(value[key]))
  );
}

function isMeter(value: unknown): value is MeterDrift {
  return (
    record(value) &&
    text(value.meter_id) &&
    count(value.readings) &&
    ['level_ratio', 'wape', 'coverage'].every((key) => nullable(number)(value[key]))
  );
}

export function isDrift(value: unknown): value is Drift | DriftUnavailable {
  if (!record(value) || !texts(value.datasets)) return false;
  if (value.available === false) return text(value.message);
  const meters = value.meters;
  return (
    value.available === true &&
    text(value.dataset_id) &&
    (value.data_kind === 'synthetic' || value.data_kind === 'observed') &&
    text(value.model_version) &&
    number(value.interval_nominal) &&
    (value.period === 'week' || value.period === 'month') &&
    date(value.reference_end) &&
    date(value.window_start) &&
    date(value.window_end) &&
    Array.isArray(value.periods) &&
    value.periods.every(isPeriod) &&
    nullable(date)(value.latest_period) &&
    record(meters) &&
    count(meters.total) &&
    count(meters.limit) &&
    count(meters.offset) &&
    Array.isArray(meters.items) &&
    meters.items.every(isMeter) &&
    record(value.definitions) &&
    Object.values(value.definitions).every(text) &&
    text(value.note)
  );
}

export const DRIFT_PAGE = 10;

export function fetchDrift(
  query: { datasetId: string | null; period: DriftPeriod | null; offset: number },
  signal?: AbortSignal,
): Promise<Drift | DriftUnavailable> {
  const params = new URLSearchParams({ limit: String(DRIFT_PAGE), offset: String(query.offset) });
  if (query.datasetId) params.set('dataset_id', query.datasetId);
  if (query.period) params.set('period', query.period);
  return getJson(`/api/v1/models/drift?${params.toString()}`, isDrift, signal ? { signal } : {});
}
