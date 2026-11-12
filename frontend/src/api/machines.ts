import { getJson } from './client';
import type { StoredKind } from './summary';

/** Mirrors `MeterComparisonOut` (backend/src/wattwise/api/schemas/machines.py). */
export interface MeterComparison {
  meter_id: string;
  energy_kwh: number;
  hours_with_reading: number;
  running_threshold_kwh: number;
  running_hours: number;
  closed_kwh: number;
  closed_share: number | null;
  peak_kwh: number;
  events: number;
  negative_hours: number;
  negative_kwh: number;
}

export interface MainMeter extends MeterComparison {
  chosen: boolean;
}

export interface Machine extends MeterComparison {
  share_of_main: number | null;
}

/** Mirrors `MachineComparison`: a building's meters against its main meter (T066). */
export interface MachineComparison {
  available: boolean;
  message: string | null;
  building_id: string;
  dataset_id: string;
  dataset_name: string;
  data_kind: StoredKind;
  timezone: string;
  first_reading: string | null;
  last_reading: string | null;
  open_days: number[];
  open_from: number;
  open_to: number;
  main: MainMeter | null;
  machines: Machine[];
  unmetered_kwh: number | null;
  unmetered_share: number | null;
  not_compared: string[];
  definitions: Record<string, string>;
  caveats: string[];
}

export interface MachineQuery {
  main: string | null;
  days: number[];
  from: number;
  to: number;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const num = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const numOrNull = (value: unknown): value is number | null => value === null || num(value);
const text = (value: unknown): value is string => typeof value === 'string';
const textOrNull = (value: unknown): value is string | null => value === null || text(value);

function isMeterComparison(value: unknown): value is MeterComparison {
  return (
    record(value) &&
    text(value.meter_id) &&
    num(value.energy_kwh) &&
    num(value.hours_with_reading) &&
    num(value.running_threshold_kwh) &&
    num(value.running_hours) &&
    num(value.closed_kwh) &&
    numOrNull(value.closed_share) &&
    num(value.peak_kwh) &&
    num(value.events) &&
    num(value.negative_hours) &&
    num(value.negative_kwh)
  );
}

function isMachine(value: unknown): value is Machine {
  return record(value) && numOrNull(value.share_of_main) && isMeterComparison(value);
}

function isMainMeter(value: unknown): value is MainMeter {
  return record(value) && typeof value.chosen === 'boolean' && isMeterComparison(value);
}

export function isMachineComparison(value: unknown): value is MachineComparison {
  return (
    record(value) &&
    typeof value.available === 'boolean' &&
    textOrNull(value.message) &&
    text(value.building_id) &&
    text(value.dataset_id) &&
    text(value.dataset_name) &&
    (value.data_kind === 'synthetic' || value.data_kind === 'observed') &&
    text(value.timezone) &&
    textOrNull(value.first_reading) &&
    textOrNull(value.last_reading) &&
    Array.isArray(value.open_days) &&
    value.open_days.every(num) &&
    num(value.open_from) &&
    num(value.open_to) &&
    (value.main === null || isMainMeter(value.main)) &&
    Array.isArray(value.machines) &&
    value.machines.every(isMachine) &&
    numOrNull(value.unmetered_kwh) &&
    numOrNull(value.unmetered_share) &&
    Array.isArray(value.not_compared) &&
    value.not_compared.every(text) &&
    record(value.definitions) &&
    Object.values(value.definitions).every(text) &&
    Array.isArray(value.caveats) &&
    value.caveats.every(text)
  );
}

/** A building's meters against its main meter, from `GET /api/v1/buildings/{id}/machines`. */
export function fetchMachines(
  buildingId: string,
  query: MachineQuery,
  signal?: AbortSignal,
): Promise<MachineComparison> {
  const params = new URLSearchParams({
    open_days: query.days.join(','),
    open_from: String(query.from),
    open_to: String(query.to),
  });
  if (query.main) params.set('main_meter_id', query.main);
  return getJson(
    `/api/v1/buildings/${encodeURIComponent(buildingId)}/machines?${params.toString()}`,
    isMachineComparison,
    signal ? { signal } : {},
  );
}
