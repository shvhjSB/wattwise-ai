import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from '../test/http';
import { alertTotals, kindSummary, summaryOf } from '../test/summaryFixture';
import { fetchSummary, isAlertTotals, isDashboardSummary, isKindSummary } from './summary';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isAlertTotals', () => {
  it('accepts valid totals', () => {
    expect(isAlertTotals(alertTotals({ alerts: 3, by_kind: { above_expected: 3 } }))).toBe(true);
  });

  it.each([
    ['a missing field', { ...alertTotals(), open: undefined }],
    ['a text count', { ...alertTotals(), alerts: '3' }],
    ['a non-numeric breakdown', { ...alertTotals(), by_kind: { above_expected: 'many' } }],
    ['an array breakdown', { ...alertTotals(), by_review_status: [] }],
    ['null', null],
  ])('rejects %s', (_name, value) => {
    expect(isAlertTotals(value)).toBe(false);
  });
});

describe('isKindSummary', () => {
  it('accepts a kind with no readings (null share and range)', () => {
    expect(
      isKindSummary(
        kindSummary('observed', { missing_share: null, first_reading: null, last_reading: null }),
      ),
    ).toBe(true);
  });

  it('rejects uploaded data, which is never stored', () => {
    expect(isKindSummary({ ...kindSummary('observed'), kind: 'uploaded' })).toBe(false);
  });

  it('rejects a summary without its alert totals', () => {
    expect(isKindSummary({ ...kindSummary('observed'), alerts: undefined })).toBe(false);
  });
});

describe('isDashboardSummary', () => {
  it('accepts an empty database', () => {
    expect(isDashboardSummary({ data_kinds: [], by_kind: [] })).toBe(true);
  });

  it.each([
    ['unknown kinds', { data_kinds: ['simulated'], by_kind: [] }],
    ['no by_kind', { data_kinds: [] }],
    ['an invalid kind entry', { data_kinds: [], by_kind: [{ kind: 'observed' }] }],
    ['text', 'synthetic'],
  ])('rejects %s', (_name, value) => {
    expect(isDashboardSummary(value)).toBe(false);
  });
});

describe('fetchSummary', () => {
  it('reads the dashboard summary', async () => {
    const body = summaryOf(kindSummary('synthetic'));
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(body)));
    vi.stubGlobal('fetch', fetchMock);

    const summary = await fetchSummary();

    expect(summary.data_kinds).toEqual(['synthetic']);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/dashboard/summary', expect.any(Object));
  });

  it('rejects a response that is not a summary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ data_kinds: ['made-up'], by_kind: [] }))),
    );

    await expect(fetchSummary()).rejects.toMatchObject({ kind: 'invalid-response' });
  });
});
