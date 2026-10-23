import { describe, expect, it, vi } from 'vitest';

import { jsonResponse } from '../test/http';
import { fetchHealth, isHealthResponse } from './health';

const healthy = {
  status: 'ok',
  service: 'wattwise-api',
  version: '0.1.0',
  environment: 'development',
};

describe('isHealthResponse', () => {
  it('accepts the backend health payload', () => {
    expect(isHealthResponse(healthy)).toBe(true);
  });

  it.each([
    ['null', null],
    ['a string', 'ok'],
    ['a non-ok status', { ...healthy, status: 'degraded' }],
    ['an unknown environment', { ...healthy, environment: 'staging' }],
    ['a missing version', { status: 'ok', service: 'wattwise-api', environment: 'test' }],
    ['a numeric version', { ...healthy, version: 1 }],
  ])('rejects %s', (_label, payload) => {
    expect(isHealthResponse(payload)).toBe(false);
  });
});

describe('fetchHealth', () => {
  it('reads the versioned liveness endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(healthy));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchHealth()).resolves.toEqual(healthy);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.anything());
  });
});
