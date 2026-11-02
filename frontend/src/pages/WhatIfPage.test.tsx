import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { building, meter, page, series } from '../test/expectationFixture';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };
const METER = 'B1:electricity';

function stubApi(options: { expectation?: Response; meterStatus?: number } = {}) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(raw, 'http://localhost').pathname;
    if (path === '/api/v1/health') return Promise.resolve(jsonResponse(HEALTH));
    if (path === '/api/v1/dashboard/summary')
      return Promise.resolve(jsonResponse(summaryOf(kindSummary('observed'))));
    if (path === '/api/v1/meters') return Promise.resolve(jsonResponse(page([meter(METER, 'B1')])));
    if (path === `/api/v1/meters/${encodeURIComponent(METER)}`)
      return Promise.resolve(
        options.meterStatus
          ? jsonResponse({ detail: 'not found' }, options.meterStatus)
          : jsonResponse(meter(METER, 'B1')),
      );
    if (path === '/api/v1/buildings/B1') return Promise.resolve(jsonResponse(building('B1')));
    if (path.endsWith('/expectation'))
      return Promise.resolve(options.expectation ?? jsonResponse(series()));
    return Promise.reject(new Error(`unexpected request: ${raw}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function totals() {
  return within(screen.getByRole('table', { name: 'Scenario totals' }));
}

beforeEach(() => {
  window.history.replaceState(null, '', '/whatif');
});
afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('What-if lab', () => {
  it('asks for a meter first, with suggestions', async () => {
    stubApi();
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('Choose a meter')).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('Meter ID'), METER);
    await user.click(screen.getByRole('button', { name: 'Explore' }));
    expect(window.location.search).toContain(`meter=${encodeURIComponent(METER)}`);
    expect(await screen.findByRole('region', { name: 'Scenario' })).toBeInTheDocument();
  });

  it('shows recorded, expected and potential excess above the interval', async () => {
    window.history.replaceState(null, '', `/whatif?meter=${METER}&days=all`);
    stubApi();
    render(<App />);

    await screen.findByRole('region', { name: 'Scenario' });
    // 719 readings of 100 plus ten of 150 (one reading missing); the spike is 40 above 110
    expect(totals().getByText('72,400 kWh')).toBeInTheDocument();
    expect(totals().getByText('400 kWh')).toBeInTheDocument();
    expect(totals().getByText(/10 hours above the line/)).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(/recorded readings are unchanged/);
    expect(screen.getByText(/hours with a reading have no threshold/)).toBeInTheDocument();
    expect(screen.getByText('America/New_York', { exact: false })).toBeInTheDocument();
  });

  it('applies a hypothetical cut in local hours without changing what was recorded', async () => {
    window.history.replaceState(null, '', `/whatif?meter=${METER}&days=all`);
    stubApi();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('region', { name: 'Scenario' });

    const cut = screen.getByLabelText('Cut, percent');
    await user.clear(cut);
    await user.type(cut, '50');
    await user.selectOptions(screen.getByLabelText('Cut from, local hour'), '8');
    await user.selectOptions(screen.getByLabelText('Cut to, local hour'), '18');

    expect(totals().getByText('72,400 kWh')).toBeInTheDocument(); // recorded is unchanged
    expect(totals().getByText(/Hypothetical cut \(50%, 08:00–18:00 local\)/)).toBeInTheDocument();
    // the spike falls at 08:00–17:00 New York time, so the scenario leaves no excess
    const after = totals().getByText('Potential excess under the scenario').closest('tr');
    expect(after).not.toBeNull();
    expect(within(after as HTMLElement).getByText('0 kWh')).toBeInTheDocument();
    expect(screen.getAllByTestId('scenario-line').length).toBeGreaterThan(0);
  });

  it('shows costs only with an entered tariff', async () => {
    window.history.replaceState(null, '', `/whatif?meter=${METER}&days=all`);
    stubApi();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('region', { name: 'Scenario' });

    expect(totals().queryByText(/\$/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Price per kWh'), '0.2');
    await user.type(screen.getByLabelText('Currency code'), 'usd');
    expect(totals().getByText(/\$80\.00/)).toBeInTheDocument();
  });

  it('can count excess above a margin over the expectation instead', async () => {
    window.history.replaceState(null, '', `/whatif?meter=${METER}&days=all`);
    stubApi();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('region', { name: 'Scenario' });

    const margin = screen.getByLabelText('Margin above expected, percent');
    await user.clear(margin);
    await user.type(margin, '40');
    // threshold 140: ten hours of 10 above it, and the first day now has a threshold too
    expect(totals().getByText('100 kWh')).toBeInTheDocument();
    expect(totals().getByText(/above expected \+ 40%/)).toBeInTheDocument();
    expect(screen.queryByText(/hours with a reading have no threshold/)).not.toBeInTheDocument();
  });

  it('explains an unknown meter and a meter without an expectation', async () => {
    window.history.replaceState(null, '', `/whatif?meter=${METER}`);
    stubApi({ meterStatus: 404 });
    const { unmount } = render(<App />);
    expect(await screen.findByText(`There is no meter ${METER}.`)).toBeInTheDocument();
    unmount();

    stubApi({
      expectation: jsonResponse(
        series({
          available: false,
          reason: 'no_expectation_stored',
          message: 'No model expectation is stored for this dataset.',
          meta: null,
          points: [],
        }),
      ),
    });
    render(<App />);
    expect(await screen.findByText('No expectation for this meter')).toBeInTheDocument();
  });
});
