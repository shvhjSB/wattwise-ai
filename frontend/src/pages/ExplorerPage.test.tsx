import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import {
  alertAt,
  building,
  meter,
  page,
  series,
  WINDOW_START,
  HOUR,
} from '../test/expectationFixture';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

interface Stub {
  expectation?: () => Response;
  alerts?: () => Response;
  buildings?: (url: URL) => Response;
}

/** Stub the whole API; routes can be overridden per test. */
function stubApi(overrides: Stub = {}) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost');
    const path = url.pathname;
    if (path === '/api/v1/health') return Promise.resolve(jsonResponse(HEALTH));
    if (path === '/api/v1/dashboard/summary') {
      return Promise.resolve(jsonResponse(summaryOf(kindSummary('observed'))));
    }
    if (path === '/api/v1/buildings') {
      return Promise.resolve(
        overrides.buildings?.(url) ??
          jsonResponse(page([building('B1'), building('B2', { primary_use: 'Office' })], 2, 20, 0)),
      );
    }
    if (path === '/api/v1/meters') {
      const b = url.searchParams.get('building_id') ?? '';
      return Promise.resolve(jsonResponse(page([meter(`${b}:electricity`, b)])));
    }
    if (path.endsWith('/expectation')) {
      return Promise.resolve(overrides.expectation?.() ?? jsonResponse(series()));
    }
    if (path === '/api/v1/alerts') {
      return Promise.resolve(
        overrides.alerts?.() ?? jsonResponse(page([alertAt(7, 300, 310, 80)], 1, 200, 0)),
      );
    }
    return Promise.reject(new Error(`unexpected request: ${raw}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function urlsOf(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(([input]) => (typeof input === 'string' ? input : ''));
}

beforeEach(() => {
  window.history.replaceState(null, '', '/explorer');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

async function openMeter() {
  await userEvent.click(await screen.findByRole('button', { name: /^B1/ }));
  await userEvent.click(await screen.findByRole('button', { name: /electricity/ }));
}

describe('Explorer: finding a meter', () => {
  it('lists buildings and asks the user to choose a meter', async () => {
    stubApi();

    render(<App />);

    expect(await screen.findByRole('button', { name: /^B1/ })).toBeInTheDocument();
    expect(screen.getByText('Showing 2 of 2 buildings')).toBeInTheDocument();
    expect(screen.getByText('Choose a meter')).toBeInTheDocument();
    expect(screen.getAllByText('Observed').length).toBeGreaterThan(0);
  });

  it('searches, sending the text to the API', async () => {
    const fetchMock = stubApi();
    render(<App />);
    await screen.findByRole('button', { name: /^B1/ });

    await userEvent.type(
      screen.getByRole('searchbox', { name: /Search buildings/ }),
      'Office{Enter}',
    );

    await vi.waitFor(() => {
      expect(urlsOf(fetchMock).some((u) => u.includes('q=Office'))).toBe(true);
    });
  });

  it('says so when nothing matches', async () => {
    stubApi({ buildings: () => jsonResponse(page([], 0)) });

    render(<App />);

    expect(await screen.findByText('No buildings loaded')).toBeInTheDocument();
  });

  it('offers to show more, up to the limit', async () => {
    const fetchMock = stubApi({ buildings: () => jsonResponse(page([building('B1')], 50, 20, 0)) });
    render(<App />);

    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }));

    await vi.waitFor(() => {
      expect(urlsOf(fetchMock).some((u) => u.includes('limit=40'))).toBe(true);
    });
  });

  it('explains a missing database and offers a retry', async () => {
    stubApi({ buildings: () => jsonResponse({ detail: { database: 'not_configured' } }, 503) });

    render(<App />);

    expect(await screen.findByText('Buildings are unavailable')).toBeInTheDocument();
    expect(screen.getByText('The API has no database to read from.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('opens a building, lists its meters, and puts the selection in the address', async () => {
    stubApi();
    render(<App />);

    await openMeter();

    expect(window.location.search).toBe('?building=B1&meter=B1%3Aelectricity');
    expect(await screen.findByRole('region', { name: 'Meter B1:electricity' })).toBeInTheDocument();
  });

  it('opens a linked meter directly', async () => {
    stubApi();
    window.history.replaceState(null, '', '/explorer?building=B1&meter=B1%3Aelectricity');

    render(<App />);

    expect(await screen.findByRole('region', { name: 'Meter B1:electricity' })).toBeInTheDocument();
  });
});

describe('Explorer: a meter', () => {
  async function loaded() {
    stubApi();
    render(<App />);
    await openMeter();
    return screen.findByRole('region', { name: 'Meter B1:electricity' });
  }

  it('says what the model is, where it applies, and how well its interval held', async () => {
    const region = await loaded();

    expect(region).toHaveTextContent('Model model-1');
    expect(region).toHaveTextContent('2017-07-01 to 2017-07-31');
    expect(region).toHaveTextContent('where it was not trained on the readings');
    expect(region).toHaveTextContent('87.2%');
    expect(within(region).getByTitle(/Measured by real meters/)).toBeInTheDocument(); // the badge
  });

  it('starts on the top alert, with its window shaded and its hours outside the interval counted', async () => {
    const region = await loaded();

    // The spike is hours 300-309, with three days either side.
    const summary = within(region).getByRole('status', { name: 'Range summary' });
    expect(summary).toHaveTextContent('2017-07-10');
    expect(summary).toHaveTextContent('10 of');
    expect(summary).toHaveTextContent('above 10, below 0');
    expect(screen.getAllByTestId('alert-window')).toHaveLength(1);
    expect(screen.getAllByTestId('outside-marker')).toHaveLength(10);
  });

  it('has two labelled charts', async () => {
    await loaded();

    expect(
      screen.getByRole('img', { name: /observed and expected energy in kWh per hour/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /observed minus expected/ })).toBeInTheDocument();
  });

  it('shows a gap, not a zero, for a missing reading', async () => {
    const region = await loaded();

    await userEvent.click(within(region).getByRole('button', { name: 'Whole window' }));

    expect(screen.getAllByTestId('observed-line')).toHaveLength(2); // hour 50 is not measured
    expect(within(region).getByText('A gap is a missing reading, not zero.')).toBeInTheDocument();
  });

  it('zooms and pans', async () => {
    const region = await loaded();
    const summary = () => within(region).getByRole('status', { name: 'Range summary' }).textContent;
    const before = summary();

    await userEvent.click(within(region).getByRole('button', { name: '7 days' }));
    const zoomed = summary();
    await userEvent.click(within(region).getByRole('button', { name: 'Later ▶' }));
    const panned = summary();

    expect(zoomed).not.toBe(before);
    expect(panned).not.toBe(zoomed);
    expect(within(region).getByRole('button', { name: '7 days' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('returns to the latest fortnight and to the top alert', async () => {
    const region = await loaded();
    await userEvent.click(within(region).getByRole('button', { name: 'Latest' }));
    expect(screen.queryAllByTestId('alert-window')).toHaveLength(0); // the alert ended before

    await userEvent.click(within(region).getByRole('button', { name: 'Top alert' }));

    expect(screen.getAllByTestId('alert-window')).toHaveLength(1);
  });

  it('reads out a single hour from the slider', async () => {
    const region = await loaded();

    // The view starts three days before the spike (hour 300), so slider 80 is hour 308: in it.
    fireEvent.change(within(region).getByRole('slider', { name: 'Inspect hour' }), {
      target: { value: '80' },
    });

    const readout = region.querySelector('output')?.textContent ?? '';
    expect(readout).toContain('2017-07-13 20:00 UTC');
    expect(readout).toContain('Observed: 150.0 kWh');
    expect(readout).toContain('Expected: 100.0 kWh');
    expect(readout).toContain('Interval: 90.0 to 110.0 kWh');
    expect(readout).toContain('Difference: +50.0 kWh');
    expect(readout).toContain('Above the interval');
  });

  it('offers the data as a table, with missing values shown as dashes', async () => {
    const region = await loaded();

    await userEvent.click(within(region).getByRole('button', { name: 'Show data table' }));
    await userEvent.click(within(region).getByRole('button', { name: 'Whole window' }));

    const table = within(region).getByRole('table', { name: /Hourly readings/ });
    expect(within(table).getAllByRole('row').length).toBeGreaterThan(100);
    const cells = within(table)
      .getAllByRole('cell')
      .map((c) => c.textContent);
    expect(cells).toContain('—'); // the missing reading and the early hours with no interval
    expect(within(region).getByText(/The first 500 of 720 hours/)).toBeInTheDocument();
  });

  it('lists the alerts in the range and jumps to one', async () => {
    stubApi({
      alerts: () =>
        jsonResponse(page([alertAt(7, 300, 310, 80), alertAt(8, 100, 110, 30)], 2, 200, 0)),
    });
    render(<App />);
    await openMeter();
    const region = await screen.findByRole('region', { name: 'Meter B1:electricity' });
    await userEvent.click(within(region).getByRole('button', { name: 'Whole window' }));

    const list = within(region).getByRole('region', { name: 'Alerts in this range' });
    expect(within(list).getAllByRole('button')).toHaveLength(2);
    const second = within(list).getAllByRole('button')[1];
    if (!second) throw new Error('expected two alerts');
    await userEvent.click(second);

    expect(within(region).getByRole('status', { name: 'Range summary' })).toHaveTextContent(
      new Date(WINDOW_START + 28 * HOUR).toISOString().slice(0, 10),
    );
  });

  it('repeats the caveats from the API', async () => {
    const region = await loaded();

    expect(within(region).getByText(/not a target/)).toBeInTheDocument();
  });
});

describe('Explorer: when there is nothing to show', () => {
  it('says there is no expectation for a dataset without one', async () => {
    stubApi({
      expectation: () =>
        jsonResponse(
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

    await openMeter();

    expect(await screen.findByText('No expectation to show')).toBeInTheDocument();
    expect(
      screen.getByText('No model expectation is stored for this dataset.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('says so when the range has no expectation, and still shows the readings', async () => {
    stubApi({
      expectation: () =>
        jsonResponse(
          series({
            points: series().points.map((p) => ({
              ...p,
              expected: null,
              lower: null,
              upper: null,
            })),
          }),
        ),
      alerts: () => jsonResponse(page([], 0, 200, 0)),
    });
    render(<App />);

    await openMeter();

    expect(await screen.findByText('No expectation in this range')).toBeInTheDocument();
    expect(screen.queryAllByTestId('expected-line')).toHaveLength(0);
    expect(screen.getAllByTestId('observed-line').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/no hours here have both a reading and an interval/),
    ).toBeInTheDocument();
  });

  it('defaults to the latest fortnight when the meter has no alerts', async () => {
    stubApi({ alerts: () => jsonResponse(page([], 0, 200, 0)) });
    render(<App />);

    await openMeter();

    const region = await screen.findByRole('region', { name: 'Meter B1:electricity' });
    expect(within(region).queryByRole('button', { name: 'Top alert' })).not.toBeInTheDocument();
    expect(within(region).getByRole('status', { name: 'Range summary' })).toHaveTextContent(
      '2017-07-17',
    );
  });

  it('reports an unknown meter from a stale link', async () => {
    stubApi({ expectation: () => jsonResponse({ detail: 'meter not found' }, 404) });
    window.history.replaceState(null, '', '/explorer?meter=nope');

    render(<App />);

    expect(await screen.findByText('This meter is unavailable')).toBeInTheDocument();
    expect(screen.getByText('There is no meter nope.')).toBeInTheDocument();
  });

  it('reports a failure to load alerts', async () => {
    stubApi({ alerts: () => jsonResponse({ detail: 'broken' }, 500) });
    window.history.replaceState(null, '', '/explorer?building=B1&meter=B1%3Aelectricity');

    render(<App />);

    expect(await screen.findByText('The alerts on this meter are unavailable')).toBeInTheDocument();
  });
});
