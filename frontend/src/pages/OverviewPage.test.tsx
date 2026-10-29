import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { jsonResponse } from '../test/http';
import { alertTotals, kindSummary, OBSERVED_WITH_ALERTS, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

function stub(summary: () => Response) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith('/api/v1/health')) return Promise.resolve(jsonResponse(HEALTH));
    if (url.endsWith('/api/v1/dashboard/summary')) return Promise.resolve(summary());
    return Promise.reject(new Error(`unexpected request: ${url}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

function summaryCallsOf(fetchMock: ReturnType<typeof stub>) {
  return fetchMock.mock.calls.filter(
    ([url]) => typeof url === 'string' && url.endsWith('/dashboard/summary'),
  );
}

function kpi(name: string) {
  return screen.getByRole('region', { name });
}

describe('Overview page', () => {
  it('shows the six figures for observed data', async () => {
    stub(() => jsonResponse(summaryOf(OBSERVED_WITH_ALERTS)));

    render(<App />);

    const observed = await screen.findByRole('region', { name: 'observed data' });
    expect(within(observed).getAllByRole('heading', { level: 3 })).toHaveLength(7); // title + 6

    expect(within(kpi('Measured energy')).getByText('2,872.66')).toBeInTheDocument();
    expect(kpi('Measured energy')).toHaveTextContent('GWh');
    expect(kpi('Measured energy')).toHaveTextContent('2016-01-01 to 2018-01-01');
    expect(kpi('Open alerts')).toHaveTextContent('5,546');
    expect(kpi('Open alerts')).toHaveTextContent('232 high severity');
    expect(kpi('Data quality')).toHaveTextContent('5.9%');
    expect(kpi('Data quality')).toHaveTextContent('462 meter-problem alerts');
    expect(kpi('Coverage')).toHaveTextContent('1,148');
    expect(kpi('Coverage')).toHaveTextContent('20,137,056 readings');
  });

  it('marks the potential excess as an estimate that is not verified', async () => {
    stub(() => jsonResponse(summaryOf(OBSERVED_WITH_ALERTS)));

    render(<App />);

    const excess = await screen.findByRole('region', { name: 'Potential excess energy' });
    expect(excess).toHaveTextContent('558.7');
    expect(excess).toHaveTextContent('MWh');
    expect(within(excess).getByText('Estimate')).toBeInTheDocument();
    expect(excess).toHaveTextContent('Not verified savings');
  });

  it('says the expectation covers only alert windows', async () => {
    stub(() => jsonResponse(summaryOf(OBSERVED_WITH_ALERTS)));

    render(<App />);

    const expected = await screen.findByRole('region', {
      name: 'Model-expected energy, in alert windows',
    });
    expect(expected).toHaveTextContent('6.76');
    expect(expected).toHaveTextContent('against 7.06 GWh recorded over the same hours');
    expect(
      within(expected).getByRole('button', { name: /About Model-expected/ }),
    ).toHaveAccessibleDescription(/no portfolio-wide expected figure/);
  });

  it('gives every figure a definition and a source', async () => {
    stub(() => jsonResponse(summaryOf(OBSERVED_WITH_ALERTS)));

    render(<App />);

    const buttons = await screen.findAllByRole('button', { name: /^About / });
    expect(buttons).toHaveLength(6);
    for (const button of buttons) {
      expect(button).toHaveAccessibleDescription(/Source:/);
    }
  });

  it('shows synthetic and observed data in separate, labelled sections', async () => {
    stub(() =>
      jsonResponse(summaryOf(OBSERVED_WITH_ALERTS, kindSummary('synthetic', { buildings: 4 }))),
    );

    render(<App />);

    const observed = await screen.findByRole('region', { name: 'observed data' });
    const synthetic = screen.getByRole('region', { name: 'synthetic data' });
    expect(within(observed).getByText('Observed')).toBeInTheDocument();
    expect(within(synthetic).getByText('Synthetic')).toBeInTheDocument();
    expect(within(synthetic).getByRole('region', { name: 'Coverage' })).toHaveTextContent('4');
    // Observed comes first, and no figure adds the two together.
    expect(
      observed.compareDocumentPosition(synthetic) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getAllByRole('region', { name: 'Measured energy' })).toHaveLength(2);
  });

  it('shows dashes, not zeros, for figures that need alerts when there are none', async () => {
    stub(() => jsonResponse(summaryOf(kindSummary('synthetic', { alerts: alertTotals() }))));

    render(<App />);

    const excess = await screen.findByRole('region', { name: 'Potential excess energy' });
    expect(excess).toHaveTextContent('—');
    expect(excess).toHaveTextContent('No alerts');
    expect(kpi('Open alerts')).toHaveTextContent('0');
  });

  it('says so when no data is loaded', async () => {
    stub(() => jsonResponse(summaryOf()));

    render(<App />);

    expect(await screen.findByText('No data loaded')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Measured energy' })).not.toBeInTheDocument();
  });

  it('shows loading, then the figures', async () => {
    stub(() => jsonResponse(summaryOf(OBSERVED_WITH_ALERTS)));

    render(<App />);

    expect(screen.getByText('Loading the overview…')).toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Measured energy' })).toBeInTheDocument();
    expect(screen.queryByText('Loading the overview…')).not.toBeInTheDocument();
  });

  it('explains a missing database and offers a retry', async () => {
    let calls = 0;
    const fetchMock = stub(() => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ detail: { database: 'not_configured' } }, 503)
        : jsonResponse(summaryOf(OBSERVED_WITH_ALERTS));
    });

    render(<App />);

    const alert = await screen.findByText('The overview is unavailable');
    expect(alert).toBeInTheDocument();
    expect(screen.getByText(/WATTWISE_DATABASE_URL/)).toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('region', { name: 'Measured energy' })).toBeInTheDocument();
    const summaryCalls = summaryCallsOf(fetchMock);
    expect(summaryCalls).toHaveLength(2);
  });

  it('uses one summary request for the banner and the page', async () => {
    const fetchMock = stub(() => jsonResponse(summaryOf(kindSummary('synthetic'))));

    render(<App />);

    await screen.findByRole('note', { name: 'Demo data' });
    await screen.findByRole('region', { name: 'Measured energy' });
    const summaryCalls = summaryCallsOf(fetchMock);
    expect(summaryCalls).toHaveLength(1);
  });
});
