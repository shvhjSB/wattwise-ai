import { getJson } from './client';

/** Where data comes from. `uploaded` is never stored; it labels analysis results. */
export type DataKind = 'synthetic' | 'observed' | 'uploaded';

/** The part of `DashboardSummary` (backend `api/schemas/catalog.py`) the shell needs. */
export interface DataKindsSummary {
  data_kinds: DataKind[];
}

const STORED_KINDS: readonly unknown[] = ['synthetic', 'observed'];

export function isDataKindsSummary(value: unknown): value is DataKindsSummary {
  if (typeof value !== 'object' || value === null) return false;
  const kinds = (value as Record<string, unknown>).data_kinds;
  return Array.isArray(kinds) && kinds.every((kind) => STORED_KINDS.includes(kind));
}

/** The kinds of data stored, from `GET /api/v1/dashboard/summary`. */
export function fetchDataKinds(signal?: AbortSignal): Promise<DataKindsSummary> {
  return getJson('/api/v1/dashboard/summary', isDataKindsSummary, signal ? { signal } : {});
}
