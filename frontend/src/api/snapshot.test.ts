import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from '../test/http';
import { resetSnapshot, snapshotAnswer, snapshotKey } from './snapshot';

const INDEX = {
  version: 1,
  entries: {
    '/api/v1/health': 'api/health.json',
    '/api/v1/alerts?limit=25&offset=0&severity=high': 'api/high.json',
    '/api/v1/meters/syn-office-a:electricity': 'api/meter.json',
  },
};

function stubFiles(files: Record<string, unknown>) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const name = url.replace(/^.*\/snapshot\//, '');
    return Promise.resolve(
      name in files ? jsonResponse(files[name]) : jsonResponse({ detail: 'missing' }, 404),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  resetSnapshot();
});
afterEach(() => {
  resetSnapshot();
});

describe('snapshotKey', () => {
  it('sorts parameters and decodes the path, like the recorder', () => {
    expect(snapshotKey('/api/v1/alerts?severity=high&offset=0&limit=25')).toBe(
      '/api/v1/alerts?limit=25&offset=0&severity=high',
    );
    expect(snapshotKey('/api/v1/meters/syn-office-a%3Aelectricity')).toBe(
      '/api/v1/meters/syn-office-a:electricity',
    );
    expect(snapshotKey('/api/v1/models/evaluation?q=&limit=25&offset=0')).toBe(
      '/api/v1/models/evaluation?limit=25&offset=0&q=',
    );
    expect(snapshotKey('/api/v1/health')).toBe('/api/v1/health');
  });
});

describe('snapshotAnswer', () => {
  it('answers a recorded request from its file, whatever the parameter order', async () => {
    const fetchMock = stubFiles({ 'index.json': INDEX, 'api/high.json': { items: [], total: 0 } });

    const answer = await snapshotAnswer('/api/v1/alerts?offset=0&severity=high&limit=25', 'GET');

    expect(answer).toEqual({ kind: 'found', body: { items: [], total: 0 } });
    await snapshotAnswer('/api/v1/alerts?limit=25&offset=0&severity=high', 'GET');
    const indexLoads = fetchMock.mock.calls.filter(([input]) =>
      (typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).endsWith(
        'index.json',
      ),
    );
    expect(indexLoads).toHaveLength(1); // the index is loaded once
  });

  it('finds a path given percent-encoded', async () => {
    stubFiles({ 'index.json': INDEX, 'api/meter.json': { meter_id: 'x' } });

    const answer = await snapshotAnswer('/api/v1/meters/syn-office-a%3Aelectricity', 'GET');

    expect(answer.kind).toBe('found');
  });

  it('says when a request was not recorded, and never answers a write', async () => {
    stubFiles({ 'index.json': INDEX });

    expect(await snapshotAnswer('/api/v1/buildings?q=lab&limit=20&offset=0', 'GET')).toEqual({
      kind: 'missing',
    });
    expect(await snapshotAnswer('/api/v1/alerts/1/feedback', 'POST')).toEqual({ kind: 'refused' });
  });

  it('retries the index after a failure', async () => {
    stubFiles({});
    await expect(snapshotAnswer('/api/v1/health', 'GET')).rejects.toThrow('snapshot index');

    stubFiles({ 'index.json': INDEX, 'api/health.json': { status: 'ok' } });
    expect((await snapshotAnswer('/api/v1/health', 'GET')).kind).toBe('found');
  });
});

describe('the API client in snapshot mode', () => {
  it('turns missing and refused answers into plain errors', async () => {
    vi.resetModules();
    vi.doMock('./snapshot', async (original) => ({
      ...(await original<typeof import('./snapshot')>()),
      SNAPSHOT: true,
    }));
    const { getJson, postJson, ApiError } = await import('./client');
    const snapshot = await import('./snapshot');
    snapshot.resetSnapshot();
    stubFiles({ 'index.json': INDEX, 'api/health.json': { status: 'ok' } });
    const any = (value: unknown): value is unknown => value !== undefined;

    expect(await getJson('/api/v1/health', any)).toEqual({ status: 'ok' });
    await expect(getJson('/api/v1/impact/summary?currency=EUR', any)).rejects.toThrow(
      /not part of the static demo/,
    );
    const refused = postJson('/api/v1/alerts/1/feedback', {}, any);
    await expect(refused).rejects.toBeInstanceOf(ApiError);
    await expect(refused).rejects.toThrow(/read-only/);
    vi.doUnmock('./snapshot');
    vi.resetModules();
  });
});
