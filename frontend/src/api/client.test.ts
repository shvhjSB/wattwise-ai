import { describe, expect, it, vi } from 'vitest';

import { jsonResponse } from '../test/http';
import { ApiError, apiUrl, getJson } from './client';

interface Greeting {
  hello: string;
}

function isGreeting(value: unknown): value is Greeting {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { hello?: unknown }).hello === 'string'
  );
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('Expected the promise to reject');
}

describe('apiUrl', () => {
  it('uses same-origin paths when no base URL is configured', () => {
    expect(apiUrl('/api/v1/health')).toBe('/api/v1/health');
  });

  it('prefixes the configured base URL without doubling slashes', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test/');

    expect(apiUrl('/api/v1/health')).toBe('https://api.example.test/api/v1/health');
  });
});

describe('getJson', () => {
  it('returns the validated JSON body and asks for JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ hello: 'world' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getJson('/api/v1/greeting', isGreeting)).resolves.toEqual({ hello: 'world' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/greeting',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
  });

  it('reports a network error when the API cannot be reached', async () => {
    const cause = new TypeError('Failed to fetch');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(cause));

    const error = await rejectionOf(getJson('/api/v1/greeting', isGreeting));

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: 'network', status: undefined, cause });
  });

  it('reports the HTTP status for non-2xx responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'down' }, 503)));

    const error = await rejectionOf(getJson('/api/v1/greeting', isGreeting));

    expect(error).toMatchObject({ kind: 'http', status: 503 });
    expect((error as ApiError).message).toContain('HTTP 503');
  });

  it('rejects a body that is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html></html>')));

    const error = await rejectionOf(getJson('/api/v1/greeting', isGreeting));

    expect(error).toMatchObject({ kind: 'invalid-response', status: 200 });
  });

  it('rejects JSON that does not match the expected shape', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ hello: 42 })));

    const error = await rejectionOf(getJson('/api/v1/greeting', isGreeting));

    expect(error).toMatchObject({ kind: 'invalid-response', status: 200 });
  });

  it('re-throws aborts unchanged so callers can ignore them', async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort));

    const error = await rejectionOf(getJson('/api/v1/greeting', isGreeting));

    expect(error).toBe(abort);
  });
});
