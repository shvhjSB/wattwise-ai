import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { jsonResponse } from '../test/http';
import { ANALYSIS, DATASET, EVALUATION, METADATA, MODEL_METRICS } from '../test/modelFixture';
import { summaryOf } from '../test/summaryFixture';

const DRIFT = {
  available: true,
  dataset_id: 'synthetic-sample',
  data_kind: 'synthetic',
  datasets: ['synthetic-sample'],
  model_version: 'demo-model',
  interval_nominal: 0.9,
  period: 'week',
  reference_end: '2016-01-25T00:00:00Z',
  window_start: '2016-01-25T00:00:00Z',
  window_end: '2016-02-29T00:00:00Z',
  periods: [
    {
      start: '2016-01-25T00:00:00Z',
      readings: 672,
      meters: 4,
      median_level_ratio: 0.97,
      wape: 0.094,
      bias: 3.75,
      coverage: null,
    },
    {
      start: '2016-02-15T00:00:00Z',
      readings: 672,
      meters: 4,
      median_level_ratio: 0.84,
      wape: 0.134,
      bias: 1.49,
      coverage: 0.729,
    },
  ],
  latest_period: '2016-02-15T00:00:00Z',
  meters: {
    items: [
      {
        meter_id: 'syn-office-d:electricity',
        readings: 168,
        level_ratio: 0.758,
        wape: 0.32,
        coverage: 0.607,
      },
    ],
    total: 4,
    limit: 10,
    offset: 0,
  },
  definitions: { level_ratio: 'A meter’s mean reading in the period over its training mean.' },
  note: 'Drift describes change, not failure.',
};

function stubApi(
  options: { unavailable?: boolean; failure?: boolean; empty?: boolean; mismatch?: boolean } = {},
) {
  const fetch = vi.fn(async (input: string | URL | Request) => {
    await Promise.resolve();
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      'http://localhost',
    );
    if (url.pathname.endsWith('/summary'))
      return jsonResponse({ ...summaryOf(), datasets: options.empty ? [] : [DATASET] });
    if (options.failure && url.pathname.endsWith('/metadata')) return jsonResponse({}, 503);
    if (options.unavailable && /\/models\/(metadata|metrics)$/.test(url.pathname))
      return jsonResponse({
        available: false,
        reason: 'no_model_promoted',
        message: 'No model has been promoted.',
      });
    if (url.pathname.endsWith('/metadata')) return jsonResponse(METADATA);
    if (url.pathname.endsWith('/metrics'))
      return jsonResponse({
        ...MODEL_METRICS,
        version: options.mismatch ? 'another-model' : MODEL_METRICS.version,
      });
    if (url.pathname.endsWith('/evaluation'))
      return jsonResponse(
        options.unavailable
          ? {
              ...EVALUATION,
              available: false,
              message: 'Reports missing.',
              buildings: [],
              model_metrics: null,
              baseline_metrics: null,
              total: 0,
            }
          : EVALUATION,
      );
    if (url.pathname.endsWith('/drift'))
      return jsonResponse(
        options.unavailable
          ? { available: false, message: 'No dataset has stored expectations.', datasets: [] }
          : DRIFT,
      );
    if (url.pathname.endsWith('/analysis-runs'))
      return jsonResponse({
        items: options.empty ? [] : [ANALYSIS],
        total: options.empty ? 0 : 12,
        limit: 10,
        offset: Number(url.searchParams.get('offset')),
      });
    throw new Error(`Unexpected request ${url.pathname}`);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

beforeEach(() => {
  window.history.replaceState(null, '', '/models');
});
afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Model lab', () => {
  it('shows model provenance, missing metrics, windows, baseline coverage and dataset health', async () => {
    stubApi();
    render(<App />);
    expect(screen.getByText('Loading served model...')).toBeInTheDocument();
    expect(await screen.findByText('fixture-model-v1')).toBeInTheDocument();
    expect(await screen.findByText('Metrics not recorded')).toBeInTheDocument();
    expect(screen.getByText(/2017-10-01T00:00:00Z → 2018-01-02/)).toBeInTheDocument();
    expect(await screen.findByText('seasonal-naive-1w')).toBeInTheDocument();
    expect(screen.getByText('2,100')).toBeInTheDocument();
    expect(screen.getByText('Building Alpha')).toBeInTheDocument();
    expect(screen.getByText('Missing values: 100 (2.5%)')).toBeInTheDocument();
    expect(
      within(screen.getByRole('region', { name: 'Dataset health' })).getByRole('link', {
        name: 'Data health',
      }),
    ).toHaveAttribute('href', '/data');
    expect(screen.getByText(/Unavailable: no model/)).toBeInTheDocument();
  });

  it('keeps building filtering and both pagers in the URL', async () => {
    const fetch = stubApi();
    render(<App />);
    await userEvent.type(await screen.findByLabelText('Building identifier'), 'Alpha & Beta');
    await userEvent.click(screen.getByRole('button', { name: 'Find building' }));
    expect(new URLSearchParams(window.location.search).get('building')).toBe('Alpha & Beta');
    await vi.waitFor(() => {
      expect(
        fetch.mock.calls.some(([input]) =>
          (typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.href
              : input.url
          ).includes('q=Alpha+%26+Beta'),
        ),
      ).toBe(true);
    });
    await userEvent.click(
      within(
        await screen.findByRole('navigation', { name: 'Building evaluation pages' }),
      ).getByRole('button', { name: 'Next' }),
    );
    expect(new URLSearchParams(window.location.search).get('buildingOffset')).toBe('25');
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Analysis pages' })).getByRole('button', {
        name: 'Next',
      }),
    );
    expect(new URLSearchParams(window.location.search).get('runOffset')).toBe('10');
  });

  it('shows unavailable reports and empty histories without hiding other resources', async () => {
    stubApi({ unavailable: true, empty: true });
    render(<App />);
    expect(await screen.findByText('Model unavailable')).toBeInTheDocument();
    expect(await screen.findByText('Metrics unavailable')).toBeInTheDocument();
    expect(await screen.findByText('Reports missing.')).toBeInTheDocument();
    expect(await screen.findByText('No datasets loaded')).toBeInTheDocument();
    expect(await screen.findByText('No recorded analyses')).toBeInTheDocument();
    expect(screen.queryByText('0.000')).not.toBeInTheDocument();
  });

  it('retries one failed resource while keeping the dataset panel usable', async () => {
    stubApi({ failure: true });
    render(<App />);
    expect(await screen.findByText('Served model unavailable')).toBeInTheDocument();
    expect(screen.getByText('Evaluation fixture')).toBeInTheDocument();
    stubApi();
    await userEvent.click(
      within(screen.getByRole('region', { name: 'Served model' })).getByRole('button', {
        name: 'Retry',
      }),
    );
    expect(await screen.findByText('fixture-model-v1')).toBeInTheDocument();
  });

  it('hides metrics belonging to a different served version', async () => {
    stubApi({ mismatch: true });
    render(<App />);
    expect(await screen.findByText('Model version changed')).toBeInTheDocument();
    expect(screen.queryByText('Validation and test errors')).not.toBeInTheDocument();
  });

  it('shows drift by period against the training level, with the meters that moved most', async () => {
    stubApi();
    const user = userEvent.setup();
    render(<App />);

    const drift = await screen.findByRole('region', { name: 'Data drift' });
    const table = await within(drift).findByRole('table');
    expect(within(table).getByText('−16%')).toBeInTheDocument();
    expect(within(table).getByText('No interval yet')).toBeInTheDocument();
    expect(within(table).getByText('In interval (nominal 90%)')).toBeInTheDocument();
    expect(within(drift).getByText(/syn-office-d/)).toBeInTheDocument();
    expect(within(drift).getByText(/not failure/)).toBeInTheDocument();
    await user.selectOptions(within(drift).getByLabelText(/Group by/), 'month');
    expect(window.location.search).toContain('driftPeriod=month');
  });

  it('says why drift is unavailable', async () => {
    stubApi({ unavailable: true });
    render(<App />);

    const drift = await screen.findByRole('region', { name: 'Data drift' });
    expect(
      await within(drift).findByText('No dataset has stored expectations.'),
    ).toBeInTheDocument();
  });
});
