import type { Page } from './catalog';
import { getJson } from './client';
import type { StoredKind } from './summary';

export interface Unavailable {
  available: false;
  message: string;
  reason: string;
}

export interface ModelMetadata {
  available: true;
  version: string;
  created_at: string;
  serves: string;
  model: {
    name: string;
    family: string;
    variant: string;
    seed: number;
    settings: Record<string, string | number>;
  };
  feature_set_version: string;
  horizon_hours: number;
  feature_columns: string[];
  training: {
    data_rows: number;
    training_rows: number;
    meters: number;
    first: string;
    last: string;
    data_fingerprint: string;
  };
  split: { time: Record<string, unknown> };
  libraries: Record<string, string>;
}

export interface Metrics {
  mae: number | null;
  rmse: number | null;
  bias: number | null;
  wape: number | null;
  scored: number;
  missing_prediction: number;
}

export interface ModelMetrics {
  available: true;
  version: string;
  data_label: 'observed';
  note: string;
  definitions: Record<string, string>;
  roles: {
    role: 'validation' | 'test';
    window_start: string | null;
    window_end: string | null;
    metrics: Metrics | null;
  }[];
}

export interface Evaluation {
  available: boolean;
  version: string | null;
  message: string;
  baseline_name: string;
  model_metrics: Metrics | null;
  baseline_metrics: Metrics | null;
  buildings: { building_id: string; metrics: Metrics }[];
  total: number;
  limit: number;
  offset: number;
}

export interface DatasetHealth {
  dataset_id: string;
  name: string;
  kind: StoredKind;
  buildings: number;
  meters: number;
  readings: number;
  missing_values: number;
  first_reading: string | null;
  last_reading: string | null;
}

export interface AnalysisRun {
  run_id: number;
  created_at: string;
  model_version: string | null;
  detector: string;
  input_start: string;
  input_end: string;
  meters: number;
  readings: number;
  missing_values: number;
  predictions: number;
  alerts: number;
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
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const map =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is Record<string, T> =>
    record(value) && Object.values(value).every(guard);

function isUnavailable(value: unknown): value is Unavailable {
  return record(value) && value.available === false && text(value.message) && text(value.reason);
}

export function isMetadata(value: unknown): value is ModelMetadata | Unavailable {
  if (isUnavailable(value)) return true;
  if (!record(value) || value.available !== true || !record(value.model) || !record(value.training))
    return false;
  const model = value.model;
  const training = value.training;
  return (
    text(value.version) &&
    date(value.created_at) &&
    text(value.serves) &&
    text(model.name) &&
    text(model.family) &&
    text(model.variant) &&
    number(model.seed) &&
    map((item): item is string | number => text(item) || number(item))(model.settings) &&
    text(value.feature_set_version) &&
    count(value.horizon_hours) &&
    strings(value.feature_columns) &&
    count(training.data_rows) &&
    count(training.training_rows) &&
    count(training.meters) &&
    date(training.first) &&
    date(training.last) &&
    text(training.data_fingerprint) &&
    record(value.split) &&
    record(value.split.time) &&
    map(text)(value.libraries)
  );
}

export function isMetrics(value: unknown): value is Metrics {
  return (
    record(value) &&
    ['mae', 'rmse', 'bias', 'wape'].every((key) => nullable(number)(value[key])) &&
    count(value.scored) &&
    count(value.missing_prediction)
  );
}

export function isModelMetrics(value: unknown): value is ModelMetrics | Unavailable {
  return (
    isUnavailable(value) ||
    (record(value) &&
      value.available === true &&
      text(value.version) &&
      value.data_label === 'observed' &&
      text(value.note) &&
      map(text)(value.definitions) &&
      Array.isArray(value.roles) &&
      value.roles.every(
        (role) =>
          record(role) &&
          (role.role === 'validation' || role.role === 'test') &&
          nullable(date)(role.window_start) &&
          nullable(date)(role.window_end) &&
          nullable(isMetrics)(role.metrics),
      ))
  );
}

export function isEvaluation(value: unknown): value is Evaluation {
  return (
    record(value) &&
    typeof value.available === 'boolean' &&
    nullable(text)(value.version) &&
    text(value.message) &&
    text(value.baseline_name) &&
    nullable(isMetrics)(value.model_metrics) &&
    nullable(isMetrics)(value.baseline_metrics) &&
    Array.isArray(value.buildings) &&
    value.buildings.every(
      (building) => record(building) && text(building.building_id) && isMetrics(building.metrics),
    ) &&
    count(value.total) &&
    count(value.limit) &&
    count(value.offset) &&
    (!value.available || (isMetrics(value.model_metrics) && isMetrics(value.baseline_metrics)))
  );
}

export function isDatasetHealth(value: unknown): value is DatasetHealth {
  return (
    record(value) &&
    text(value.dataset_id) &&
    text(value.name) &&
    (value.kind === 'observed' || value.kind === 'synthetic') &&
    ['buildings', 'meters', 'readings', 'missing_values'].every((key) => count(value[key])) &&
    nullable(date)(value.first_reading) &&
    nullable(date)(value.last_reading)
  );
}

export function isAnalysisPage(value: unknown): value is Page<AnalysisRun> {
  return (
    record(value) &&
    count(value.total) &&
    count(value.limit) &&
    count(value.offset) &&
    Array.isArray(value.items) &&
    value.items.every(
      (run) =>
        record(run) &&
        count(run.run_id) &&
        date(run.created_at) &&
        nullable(text)(run.model_version) &&
        text(run.detector) &&
        date(run.input_start) &&
        date(run.input_end) &&
        ['meters', 'readings', 'missing_values', 'predictions', 'alerts'].every((key) =>
          count(run[key]),
        ),
    )
  );
}

export const fetchMetadata = (signal?: AbortSignal) =>
  getJson('/api/v1/models/metadata', isMetadata, signal ? { signal } : {});
export const fetchModelMetrics = (signal?: AbortSignal) =>
  getJson('/api/v1/models/metrics', isModelMetrics, signal ? { signal } : {});
export function fetchEvaluation(q: string, offset: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ q, limit: '25', offset: String(offset) });
  return getJson(
    `/api/v1/models/evaluation?${query.toString()}`,
    isEvaluation,
    signal ? { signal } : {},
  );
}
export function fetchDatasets(signal?: AbortSignal) {
  return getJson(
    '/api/v1/dashboard/summary',
    (value): value is { datasets: DatasetHealth[] } =>
      record(value) && Array.isArray(value.datasets) && value.datasets.every(isDatasetHealth),
    signal ? { signal } : {},
  );
}
export function fetchAnalysisRuns(offset: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: '10', offset: String(offset) });
  return getJson(
    `/api/v1/analysis-runs?${query.toString()}`,
    isAnalysisPage,
    signal ? { signal } : {},
  );
}
