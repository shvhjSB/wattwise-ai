import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchDataKinds, isDataKindsSummary } from './summary';
import { jsonResponse } from '../test/http';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isDataKindsSummary', () => {
  it.each([
    [{ data_kinds: [] }, true],
    [{ data_kinds: ['synthetic'] }, true],
    [{ data_kinds: ['synthetic', 'observed'] }, true],
    [{ data_kinds: ['uploaded'] }, false], // uploads are never stored
    [{ data_kinds: ['simulated'] }, false],
    [{ data_kinds: 'synthetic' }, false],
    [{}, false],
    [null, false],
    ['synthetic', false],
  ])('%j -> %s', (value, expected) => {
    expect(isDataKindsSummary(value)).toBe(expected);
  });
});

describe('fetchDataKinds', () => {
  it('reads the kinds from the dashboard summary', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({ data_kinds: ['synthetic'] })));
    vi.stubGlobal('fetch', fetchMock);

    const summary = await fetchDataKinds();

    expect(summary.data_kinds).toEqual(['synthetic']);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/dashboard/summary', expect.any(Object));
  });

  it('rejects a response that is not a summary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ data_kinds: ['made-up'] }))),
    );

    await expect(fetchDataKinds()).rejects.toMatchObject({ kind: 'invalid-response' });
  });
});
