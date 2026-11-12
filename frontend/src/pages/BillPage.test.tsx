import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

function pathOf(input: string | URL | Request): string {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  return new URL(raw, 'http://localhost').pathname;
}

/** The shell's own calls only: the analyser itself never calls the API. */
function stubShell() {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const path = pathOf(input);
    if (path === '/api/v1/health') return Promise.resolve(jsonResponse(HEALTH));
    if (path === '/api/v1/dashboard/summary')
      return Promise.resolve(jsonResponse(summaryOf(kindSummary('synthetic'))));
    return Promise.reject(new Error(`unexpected request: ${path}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function region(name: string) {
  return within(screen.getByRole('region', { name }));
}

async function fillExample() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Fill in a synthetic example' }));
  return user;
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, '', '/bill');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Bill analyser', () => {
  it('says what a bill can and cannot show, and that nothing is saved', async () => {
    stubShell();
    render(<App />);

    const note = await screen.findByRole('note', { name: 'How the bill analyser works' });
    expect(note).toHaveTextContent('Nothing you enter is sent anywhere or saved');
    expect(note).toHaveTextContent('cannot show which machine uses the most electricity');
    expect(
      region('Checks against the bill').getByText(/Enter the charges and the total/),
    ).toBeVisible();
  });

  it('does not label typed-in figures with the stored data’s demo banner', async () => {
    stubShell();
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('note', { name: 'How the bill analyser works' });
    await user.click(screen.getByRole('link', { name: 'Overview' }));
    expect(await screen.findByRole('note', { name: 'Demo data' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Bill analyser' }));
    await screen.findByRole('note', { name: 'How the bill analyser works' });
    expect(screen.queryByRole('note', { name: 'Demo data' })).not.toBeInTheDocument();
  });

  it('checks the synthetic example against its own totals and labels it synthetic', async () => {
    stubShell();
    await fillExample();

    expect(screen.getByText('Made-up figures, not a real bill.')).toBeInTheDocument();
    const checks = region('Checks against the bill');
    expect(
      checks.getByText('The charges add up to the total payable: ₹507,280.00.'),
    ).toBeInTheDocument();
    expect(
      checks.getByText('Energy charges equal the energy billed × the energy rate.'),
    ).toBeInTheDocument();
    expect(
      checks.getByText(/printed power factor matches kWh ÷ kVAh \(0\.941\)/),
    ).toBeInTheDocument();
    expect(
      checks.getByText(/time-of-day surcharge matches the windows: ₹8,400\.00/),
    ).toBeInTheDocument();
    expect(
      checks.getByText(/time-of-day rebate matches the windows: -₹6,300\.00/),
    ).toBeInTheDocument();
    expect(checks.queryByText('Check')).not.toBeInTheDocument();
  });

  it('shows a typing mistake as a difference from the total payable', async () => {
    stubShell();
    const user = await fillExample();

    const fuel = screen.getByLabelText(/Fuel and other surcharges/);
    await user.clear(fuel);
    await user.type(fuel, '3600');

    expect(
      region('Checks against the bill').getByText(
        /add up to ₹474,880\.00, but the total payable is ₹507,280\.00: a difference of ₹32,400\.00/,
      ),
    ).toBeInTheDocument();
  });

  it('breaks the bill down and derives the demand rate from the bill itself', async () => {
    stubShell();
    await fillExample();

    const money = region('Where the money goes');
    const demandRow = money.getByRole('row', { name: /Fixed or demand charges/ });
    expect(demandRow).toHaveTextContent('₹105,000.00');
    expect(demandRow).toHaveTextContent('20.7%'); // 105,000 of 507,280
    expect(money.getByText(/₹10\.52 per kWh/)).toBeInTheDocument(); // 504,780 / 48,000
    const demand = region('Demand and capacity');
    expect(demand.getByText(/₹350\.00 per kVA/)).toBeInTheDocument();
    expect(demand.getByText(/every 10 kVA of billing demand costs ₹3,500\.00/)).toBeInTheDocument();
    expect(
      demand.getByText(
        /billed on 90 kVA more than the highest demand recorded, which cost ₹31,500\.00/,
      ),
    ).toBeInTheDocument();
    expect(demand.getByText(/not a recommendation/)).toBeInTheDocument();
  });

  it('prices moving consumption between time-of-day windows as a hypothesis', async () => {
    stubShell();
    const user = await fillExample();

    const tod = region('Time of day');
    await user.selectOptions(tod.getByLabelText('Move from'), '1');
    await user.selectOptions(tod.getByLabelText('Move to'), '2');
    await user.clear(tod.getByLabelText('kWh to move'));
    await user.type(tod.getByLabelText('kWh to move'), '2000');

    const status = tod.getByRole('status');
    expect(status).toHaveTextContent(/Moving 2,000 kWh from 18:00–22:00 \(\+10%\) to 22:00–06:00/);
    expect(status).toHaveTextContent('would save ₹2,450.00');
    expect(status).toHaveTextContent('Hypothetical');

    await user.clear(tod.getByLabelText('kWh to move'));
    await user.type(tod.getByLabelText('kWh to move'), '10000');
    expect(tod.getByRole('status')).toHaveTextContent(
      'capped at the 9,000 kWh that window recorded',
    );
  });

  it('reads the history as questions, and flags the late-payment surcharge', async () => {
    stubShell();
    await fillExample();

    const past = region('Consumption history');
    expect(past.getByText('No consumption in 2025-12.')).toBeInTheDocument();
    expect(past.getByText('Largest fall: −41% from 2026-05 to 2026-06.')).toBeInTheDocument();
    expect(past.getByText('Largest rise: +62% from 2026-06 to 2026-07.')).toBeInTheDocument();
    expect(past.getByText(/not confirmed anomalies/)).toBeInTheDocument();
    expect(region('Power factor and payment').getByText('₹2,500.00')).toBeInTheDocument();
  });

  it('works out the contract-demand what-if under the rules entered', async () => {
    stubShell();
    await fillExample();

    const what = region('Contract demand what-if');
    // Rate from the bill: 105,000 / 300 kVA = 350. Figures checked independently in Python.
    expect(what.getByText('₹1,263,500.00')).toBeInTheDocument(); // now, 400 kVA
    expect(what.getByText('₹1,027,250.00')).toBeInTheDocument(); // with 300 kVA
    expect(what.getByText('would have saved ₹236,250.00')).toBeInTheDocument();
    expect(what.getByText('2026-03', { selector: 'dd' })).toBeInTheDocument(); // the only month above 300 kVA
    expect(
      what.getByText(/^267 kVA \(₹1,009,225\.00\); the highest recorded demand was 310 kVA/),
    ).toBeInTheDocument();
    const march = what.getByRole('row', { name: /^2026-03/ });
    expect(march).toHaveTextContent('10 kVA above the contract');
    expect(what.getByText(/This is not a recommendation/)).toBeInTheDocument();
  });

  it('asks for the tariff rules instead of assuming any', async () => {
    stubShell();
    const user = await fillExample();

    const share = screen.getByLabelText(/Minimum billing demand/);
    await user.clear(share);

    expect(
      region('Contract demand what-if').getByText(/To work this out, enter the rules/),
    ).toBeInTheDocument();
  });

  it('prints a report once there are results', async () => {
    stubShell();
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    render(<App />);
    await screen.findByRole('note', { name: 'How the bill analyser works' });
    expect(screen.queryByRole('button', { name: 'Print this report' })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Fill in a synthetic example' }));
    await user.click(screen.getByRole('button', { name: 'Print this report' }));

    expect(print).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/WattWise electricity check-up: bill/)).toBeInTheDocument();
    expect(screen.getByText(/nothing was sent or stored/)).toBeInTheDocument();
    print.mockRestore();
  });

  it('stops calling edited figures the synthetic example, but never a real bill', async () => {
    stubShell();
    const user = await fillExample();
    expect(screen.getByText(/Synthetic example: made-up figures/)).toBeInTheDocument();

    const fuel = screen.getByLabelText(/Fuel and other surcharges/);
    await user.clear(fuel);
    await user.type(fuel, '3600');

    expect(screen.queryByText(/Synthetic example: made-up figures/)).not.toBeInTheDocument();
    expect(screen.getByText(/Started from the synthetic example and edited/)).toBeInTheDocument();
    expect(screen.queryByText(/Figures typed in from one monthly bill/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText(/Figures typed in from one monthly bill/)).toBeInTheDocument();
  });

  it('lists entries that cannot be right', async () => {
    stubShell();
    const user = await fillExample();

    const currency = screen.getByLabelText(/Currency/);
    await user.clear(currency);
    await user.type(currency, 'RS');

    expect(
      region('Entries to check').getByText('Currency must be a three-letter code, such as INR.'),
    ).toBeInTheDocument();
  });

  it('keeps the figures out of the URL and browser storage, and clears them', async () => {
    const fetchMock = stubShell();
    const user = await fillExample();

    expect(window.location.search).toBe('');
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i) ?? '';
      expect(window.localStorage.getItem(key)).not.toContain('507280');
    }
    expect(window.sessionStorage.length).toBe(0);
    const paths = fetchMock.mock.calls.map(([input]) => pathOf(input));
    const shell = new Set(['/api/v1/health', '/api/v1/dashboard/summary']);
    expect(paths.filter((path) => !shell.has(path))).toEqual([]); // nothing of the bill's

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.queryByText('Made-up figures, not a real bill.')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Where the money goes' })).not.toBeInTheDocument();
  });
});
