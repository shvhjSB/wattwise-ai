import { getJson } from './client';

export type DeploymentEnvironment = 'development' | 'test' | 'production';

/** Mirrors `HealthResponse` in `backend/src/wattwise/api/schemas/health.py`. */
export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  environment: DeploymentEnvironment;
}

const ENVIRONMENTS: readonly unknown[] = ['development', 'test', 'production'];

export function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === 'ok' &&
    typeof candidate.service === 'string' &&
    typeof candidate.version === 'string' &&
    ENVIRONMENTS.includes(candidate.environment)
  );
}

/** Liveness of the API process. It does not check downstream dependencies. */
export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson('/api/v1/health', isHealthResponse, signal ? { signal } : {});
}
