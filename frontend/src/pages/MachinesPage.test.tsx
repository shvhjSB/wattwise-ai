import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import type { MachineComparison, MeterComparison } from '../api/machines';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

function meter(id: string, overrides: Partial<MeterComparison> = {}): MeterComparison {
  return {
    meter_id: id,
    energy_kwh: 0,
    hours_with_reading: 672,
    running_threshold_kwh: 0.2,
    running_hours: 0,
    closed_kwh: 0,
    closed_share: null,
    peak_kwh: 0,
    events: 0,
    negative_hours: 0,
    negative_kwh: 0,
    ...overrides,
  };
}

/** The synthetic test factory's figures (backend/tests/factory_data.py). */
function comparison(overrides: Partial<MachineComparison> = {}): MachineComparison {
  return {
    available: true,
    message: null,
    building_id: 'test-factory',
    dataset_id: 'test-factory',
    dataset_name: 'Synthetic test factory (tests only)',
    data_kind: 'synthetic',
    timezone: 'Europe/Berlin',
    first_reading: '2016-10-03T00:00:00Z',
    last_reading: '2016-10-30T23:00:00Z',
    open_days: [0, 1, 2, 3, 4],
    open_from: 6,
    open_to: 18,
    main: {
      ...meter('test-factory:main', {
        energy_kwh: 24784,
        running_hours: 672,
        closed_kwh: 13904,
        closed_share: 13904 / 24784,
        peak_kwh: 52,
        events: 1,
      }),
      chosen: false,
    },
    machines: [
      {
        ...meter('test-factory:press', {
          energy_kwh: 3280,
          running_hours: 164,
          closed_kwh: 80,
          closed_share: 80 / 3280,
          peak_kwh: 20,
          events: 1,
        }),
        share_of_main: 3280 / 24784,
      },
      {
        ...meter('test-factory:pump', {
          energy_kwh: 1344,
          running_hours: 672,
          closed_kwh: 864,
          closed_share: 864 / 1344,
          peak_kwh: 2,
          negative_hours: 3,
          negative_kwh: -0.03,
        }),
        share_of_main: 1344 / 24784,
      },
    ],
    unmetered_kwh: 20160,
    unmetered_share: 20160 / 24784,
    not_compared: ['test-factory:water'],
    definitions: { energy_kwh: 'The sum of the meter’s hourly readings.' },
    caveats: ['Events are anomalies to investigate, not confirmed waste.'],
    ...overrides,
  };
}

function stub(answer: () => Response) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost');
    if (url.pathname === '/api/v1/health') return Promise.resolve(jsonResponse(HEALTH));
    if (url.pathname === '/api/v1/dashboard/summary')
      return Promise.resolve(jsonResponse(summaryOf(kindSummary('synthetic'))));
    if (url.pathname === '/api/v1/buildings')
      return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }));
    if (url.pathname.endsWith('/machines')) return Promise.resolve(answer());
    return Promise.reject(new Error(`unexpected request: ${raw}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function machineCalls(fetchMock: ReturnType<typeof stub>): URL[] {
  return fetchMock.mock.calls
    .map(([input]) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      return new URL(raw, 'http://localhost');
    })
    .filter((url) => url.pathname.endsWith('/machines'));
}

beforeEach(() => {
  window.history.replaceState(null, '', '/machines');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Machines page', () => {
  it('asks for a building, and says the tested split of a main meter did not work', async () => {
    const fetchMock = stub(() => jsonResponse(comparison()));
    render(<App />);

    expect(await screen.findByText('Choose a building')).toBeInTheDocument();
    expect(screen.getByText(/did not work\s+on a real factory \(T065\)/)).toBeInTheDocument();
    expect(machineCalls(fetchMock)).toEqual([]);
  });

  it('compares each meter with the main meter, labelled with its source', async () => {
    window.history.replaceState(null, '', '/machines?building=test-factory');
    const fetchMock = stub(() => jsonResponse(comparison()));
    render(<App />);

    const section = await screen.findByRole('region', { name: 'Machine comparison' });
    expect(within(section).getByText('Synthetic')).toBeInTheDocument();
    expect(section).toHaveTextContent('Synthetic test factory (tests only)');
    const press = within(section).getByRole('row', { name: /test-factory:press/ });
    expect(press).toHaveTextContent('3,280 kWh');
    expect(press).toHaveTextContent('13.2%');
    expect(press).toHaveTextContent('164 h');
    expect(press).toHaveTextContent('80 kWh');
    const unmetered = within(section).getByRole('row', { name: /Not metered separately/ });
    expect(unmetered).toHaveTextContent('20,160 kWh');
    expect(unmetered).toHaveTextContent('81.3%');
    expect(section).toHaveTextContent('Not compared (not electricity in kWh): test-factory:water.');
    const [call] = machineCalls(fetchMock);
    expect(call?.pathname).toBe('/api/v1/buildings/test-factory/machines');
    expect(call?.searchParams.get('open_days')).toBe('0,1,2,3,4');
    expect(call?.searchParams.get('open_from')).toBe('6');
    expect(call?.searchParams.get('open_to')).toBe('18');
    expect(call?.searchParams.has('main_meter_id')).toBe(false);
  });

  it('flags a meter that recorded below zero', async () => {
    window.history.replaceState(null, '', '/machines?building=test-factory');
    stub(() => jsonResponse(comparison()));
    render(<App />);

    const pump = await screen.findByRole('row', { name: /test-factory:pump/ });
    expect(pump).toHaveTextContent('3 hours below zero');
    expect(pump).toHaveTextContent('check this meter');
  });

  it('asks again with the chosen main meter and opening days', async () => {
    window.history.replaceState(null, '', '/machines?building=test-factory');
    const user = userEvent.setup();
    const fetchMock = stub(() => jsonResponse(comparison()));
    render(<App />);
    await screen.findByRole('region', { name: 'Machine comparison' });

    await user.selectOptions(screen.getByLabelText('Main meter'), 'test-factory:press');
    await user.click(screen.getByLabelText('Sat'));

    const calls = machineCalls(fetchMock);
    const last = calls[calls.length - 1];
    expect(last?.searchParams.get('main_meter_id')).toBe('test-factory:press');
    expect(last?.searchParams.get('open_days')).toBe('0,1,2,3,4,5');
    expect(window.location.search).toContain('main=test-factory%3Apress');
  });

  it('warns when the chosen main meter does not contain the others', async () => {
    window.history.replaceState(
      null,
      '',
      '/machines?building=test-factory&main=test-factory%3Apress',
    );
    const base = comparison();
    const press = base.machines[0];
    const realMain = base.main;
    if (!press || !realMain) throw new Error('fixture');
    stub(() =>
      jsonResponse(
        comparison({
          main: { ...press, chosen: true },
          machines: [
            { ...realMain, share_of_main: realMain.energy_kwh / press.energy_kwh },
            ...base.machines.slice(1),
          ],
          unmetered_kwh: -22848,
          unmetered_share: -22848 / 3280,
        }),
      ),
    );
    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Check the main meter.');
    expect(alert).toHaveTextContent('test-factory:main used more than test-factory:press');
  });

  it('does not warn when the main meter contains the others', async () => {
    window.history.replaceState(null, '', '/machines?building=test-factory');
    stub(() => jsonResponse(comparison()));
    render(<App />);

    await screen.findByRole('region', { name: 'Machine comparison' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('explains a building with nothing to compare, and an unknown building', async () => {
    window.history.replaceState(null, '', '/machines?building=syn-office-a');
    stub(() =>
      jsonResponse(
        comparison({
          available: false,
          message:
            'A comparison needs at least two electricity meters in kWh with readings; this building has 1.',
          main: null,
          machines: [],
          unmetered_kwh: null,
          unmetered_share: null,
        }),
      ),
    );
    const { unmount } = render(<App />);
    expect(await screen.findByText('No comparison for this building')).toBeInTheDocument();
    expect(screen.getByText(/this building has 1/)).toBeInTheDocument();
    unmount();

    window.history.replaceState(null, '', '/machines?building=nowhere');
    stub(() => jsonResponse({ detail: 'building not found' }, 404));
    render(<App />);
    expect(await screen.findByText('No building nowhere is stored.')).toBeInTheDocument();
  });
});
