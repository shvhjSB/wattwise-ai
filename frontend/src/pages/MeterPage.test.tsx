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

/** The shell's own calls only: the meter check never calls the API. */
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

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, '', '/meter');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Meter check', () => {
  it('says the file stays in the browser and that it does not split machines', async () => {
    stubShell();
    render(<App />);

    const note = await screen.findByRole('note', { name: 'How the meter check works' });
    expect(note).toHaveTextContent('never uploaded or saved');
    expect(note).toHaveTextContent('does not split the meter into machines');
    expect(screen.getByText('Choose a meter file')).toBeInTheDocument();
    expect(screen.queryByRole('note', { name: 'Demo data' })).not.toBeInTheDocument();
  });

  it('checks the synthetic example: data, peak, use while closed and the left-on Sunday', async () => {
    stubShell();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Use a synthetic example' }));

    expect(screen.getByText('Made-up readings, not a real site.')).toBeInTheDocument();
    const data = region('Data check');
    expect(data.getByText('15 minutes')).toBeInTheDocument();
    expect(data.getByText('2,688')).toBeInTheDocument();
    expect(data.getByText(/^0 \(0/)).toBeInTheDocument(); // no missing intervals
    const peak = region('Energy and peak demand');
    expect(peak.getByText('50,560 kWh')).toBeInTheDocument();
    expect(peak.getByText(/^120 kW at 2018-01-01 08:00/)).toBeInTheDocument();
    const closed = region('Use while closed');
    expect(closed.getByText('16,000 kWh (31.6% of all use)')).toBeInTheDocument();
    expect(closed.getByText('40 kW (10th percentile)')).toBeInTheDocument();
    const unusual = region('Unusual periods');
    const row = unusual.getByRole('row', { name: /2018-01-21 00:00/ });
    expect(row).toHaveTextContent('8');
    expect(row).toHaveTextContent('higher');
    expect(unusual.getByText(/not confirmed waste/)).toBeInTheDocument();
  });

  it('prices use while closed only with a rate the user enters', async () => {
    stubShell();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Use a synthetic example' }));
    expect(region('Use while closed').queryByText(/At your rate/)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Energy rate per kWh'), '8');

    expect(region('Use while closed').getByText(/^128,000 for the period/)).toBeInTheDocument();
  });

  it('reads an uploaded file with day/month dates, and reports a line it cannot read', async () => {
    stubShell();
    const user = userEvent.setup();
    render(<App />);
    const csv = [
      'Date,Demand (kW)',
      '01/02/2018 00:00,10',
      '01/02/2018 00:30,12',
      'broken,5',
      '01/02/2018 01:00,14',
    ].join('\n');
    await user.upload(
      await screen.findByLabelText('Meter file'),
      new File([csv], 'meter.csv', { type: 'text/csv' }),
    );

    await user.selectOptions(screen.getByLabelText('Date order'), 'dmy');
    await user.selectOptions(screen.getByLabelText('The values are'), 'kw');
    const zone = screen.getByLabelText(/Time zone of the times/);
    await user.clear(zone);
    await user.type(zone, 'UTC');

    const data = region('Data check');
    expect(data.getByText('30 minutes')).toBeInTheDocument();
    expect(data.getByText('2018-02-01 00:00 to 2018-02-01 01:00')).toBeInTheDocument();
    expect(data.getByText(/Line 4: the time "broken"/)).toBeInTheDocument();
    expect(region('Energy and peak demand').getByText('18 kWh')).toBeInTheDocument(); // (10+12+14)/2
  });

  it('refuses a time zone it does not know', async () => {
    stubShell();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Use a synthetic example' }));

    const zone = screen.getByLabelText(/Time zone of the times/);
    await user.clear(zone);
    await user.type(zone, 'Mars/Olympus');

    expect(
      screen.getByText('Not a time zone. Use a name such as Asia/Kolkata.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Data check' })).not.toBeInTheDocument();
  });

  it('prints a report once there are results', async () => {
    stubShell();
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Use a synthetic example' }));
    await user.click(screen.getByRole('button', { name: 'Print this report' }));

    expect(print).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/WattWise electricity check-up: meter/)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic example: made-up readings/)).toBeInTheDocument();
    print.mockRestore();
  });

  it('never sends the readings anywhere or keeps them', async () => {
    const fetchMock = stubShell();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Use a synthetic example' }));

    const shell = new Set(['/api/v1/health', '/api/v1/dashboard/summary']);
    const paths = fetchMock.mock.calls.map(([input]) => pathOf(input));
    expect(paths.filter((p) => !shell.has(p))).toEqual([]);
    expect(window.location.search).toBe('');
    expect(window.sessionStorage.length).toBe(0);
    for (let i = 0; i < window.localStorage.length; i += 1) {
      expect(window.localStorage.getItem(window.localStorage.key(i) ?? '')).not.toContain('2018');
    }
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('Choose a meter file')).toBeInTheDocument();
  });
});
