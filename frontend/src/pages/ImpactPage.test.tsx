import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import type { ImpactSummary } from '../api/impact';
import { impactSummary } from '../test/impactFixture';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

interface ApiOptions {
  empty?: boolean;
  impactError?: number;
}

function withoutTariff(summary: ImpactSummary): ImpactSummary {
  return {
    ...summary,
    tariff: null,
    by_kind: summary.by_kind.map((kind) => ({
      ...kind,
      total_cost: null,
      by_geography: kind.by_geography.map((group) => ({ ...group, cost: null })),
    })),
  };
}

function stubApi(options: ApiOptions = {}) {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost');
    if (url.pathname === '/api/v1/health') return jsonResponse(HEALTH);
    if (url.pathname === '/api/v1/dashboard/summary') {
      return jsonResponse(summaryOf(kindSummary('observed')));
    }
    if (url.pathname === '/api/v1/impact/summary') {
      if (options.impactError)
        return jsonResponse({ detail: 'impact unavailable' }, options.impactError);
      if (options.empty) return jsonResponse(impactSummary({ tariff: null, by_kind: [] }));
      const geography = url.searchParams.get('tariff_geography');
      const currency = url.searchParams.get('currency');
      const rate = Number(url.searchParams.get('rate_per_kwh'));
      if (geography && currency && rate > 0) {
        const configured = impactSummary();
        return jsonResponse({
          ...configured,
          tariff: { geography, currency, rate_per_kwh: rate },
          by_kind: configured.by_kind.map((kind) => ({
            ...kind,
            total_cost: { value: 1520 * rate, currency, events: 6 },
            by_geography: kind.by_geography.map((group) =>
              group.tariff_geography === geography
                ? {
                    ...group,
                    cost: {
                      value: group.potential_excess_kwh * rate,
                      currency,
                      events: group.events,
                    },
                  }
                : { ...group, cost: null },
            ),
          })),
        });
      }
      return jsonResponse(withoutTariff(impactSummary()));
    }
    return Promise.reject(new Error(`unexpected request: ${raw}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function urls(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(([input]) =>
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
  );
}

beforeEach(() => {
  window.history.replaceState(null, '', '/impact');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Cost impact page', () => {
  it('shows loading, potential totals, sourced carbon, and explicit unconfigured states', async () => {
    stubApi();
    render(<App />);

    expect(screen.getByText('Loading impact estimates...')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'observed data' })).toBeInTheDocument();
    expect(
      within(screen.getByLabelText('Potential excess energy')).getByText('1.8'),
    ).toBeInTheDocument();
    expect(screen.getByText('EPA eGRID2016 Summary Tables Table 1')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Carbon not configured' })).toBeInTheDocument();
    expect(screen.getByText(/Carbon remains not configured, not zero/)).toBeInTheDocument();
    expect(
      within(screen.getByLabelText('Scenario cost')).getByText('Not configured'),
    ).toBeInTheDocument();
  });

  it('applies an explicit tariff through the URL and API query', async () => {
    const fetchMock = stubApi();
    render(<App />);
    const form = await screen.findByRole('form', { name: 'Tariff configuration' });

    await userEvent.type(within(form).getByLabelText('Currency code'), 'usd');
    await userEvent.type(within(form).getByLabelText('Rate per kWh'), '0.2');
    await userEvent.click(within(form).getByRole('button', { name: 'Apply scenario' }));

    await vi.waitFor(() => {
      expect(window.location.search).toBe('?tariff=US-MN&currency=USD&rate=0.2');
      expect(
        urls(fetchMock).some(
          (url) =>
            url.includes('/impact/summary?') &&
            url.includes('tariff_geography=US-MN') &&
            url.includes('currency=USD') &&
            url.includes('rate_per_kwh=0.2'),
        ),
      ).toBe(true);
    });
    expect(await screen.findByText(/Active: 0.2 USD\/kWh for US-MN/)).toBeInTheDocument();
    expect(within(screen.getByLabelText('Scenario cost')).getByText('304.00')).toBeInTheDocument();
  });

  it('uses a published reference only after the reviewer chooses it', async () => {
    stubApi();
    render(<App />);

    await userEvent.click(await screen.findByRole('button', { name: 'Use reference' }));

    await vi.waitFor(() => {
      expect(window.location.search).toBe('?tariff=US-MN&currency=USD&rate=0.1048');
    });
  });

  it('validates manual tariff fields before changing the scenario', async () => {
    stubApi();
    render(<App />);
    const form = await screen.findByRole('form', { name: 'Tariff configuration' });

    await userEvent.type(within(form).getByLabelText('Currency code'), 'US');
    await userEvent.type(within(form).getByLabelText('Rate per kWh'), '2');
    await userEvent.click(within(form).getByRole('button', { name: 'Apply scenario' }));

    expect(screen.getByRole('alert')).toHaveTextContent('three-letter currency');
    expect(window.location.search).toBe('');
  });

  it('shows empty and API failure states plainly', async () => {
    stubApi({ empty: true });
    const empty = render(<App />);
    expect(await screen.findByText('No impact to estimate')).toBeInTheDocument();

    empty.unmount();
    stubApi({ impactError: 503 });
    render(<App />);
    expect(await screen.findByText('Impact estimates are unavailable')).toBeInTheDocument();
  });
});
