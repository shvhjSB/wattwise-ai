import { describe, expect, it, vi } from 'vitest';

import { impactSummary } from '../test/impactFixture';
import { jsonResponse } from '../test/http';
import { fetchImpact, isImpactSummary } from './impact';

describe('impact API', () => {
  it('validates an impact summary and rejects incomplete geography data', () => {
    expect(isImpactSummary(impactSummary())).toBe(true);
    expect(
      isImpactSummary({
        ...impactSummary(),
        by_kind: [{ ...impactSummary().by_kind[0], by_geography: [{ events: 2 }] }],
      }),
    ).toBe(false);
  });

  it('fetches the unconfigured kWh-only view without inventing query values', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(impactSummary({ tariff: null })));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchImpact()).resolves.toMatchObject({ status: 'potential', tariff: null });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/impact/summary', expect.any(Object));
  });

  it('encodes all explicit tariff scenario fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(impactSummary()));
    vi.stubGlobal('fetch', fetchMock);

    await fetchImpact({ geography: 'US-MN', currency: 'USD', rate_per_kwh: 0.1048 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/v1/impact/summary?tariff_geography=US-MN&currency=USD&rate_per_kwh=0.1048',
    );
  });
});
