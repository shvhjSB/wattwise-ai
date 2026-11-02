import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { isDatasetQuality, type DatasetQuality, type MeterQuality } from '../api/quality';
import { App } from '../App';
import { jsonResponse } from '../test/http';
import { ANALYSIS, DATASET } from '../test/modelFixture';
import { summaryOf } from '../test/summaryFixture';

const METER: MeterQuality = {
  meter_id: 'syn-lab-c:electricity',
  building_id: 'syn-lab-c',
  meter_type: 'electricity',
  unit: 'kWh',
  interval_minutes: 60,
  first: '2016-01-04T00:00:00Z',
  last: '2016-02-28T23:00:00Z',
  expected_intervals: 1344,
  present_rows: 1344,
  absent_intervals: 0,
  missing_values: 6,
  available_values: 1338,
  coverage_pct: 99.6,
  negative_values: 0,
  zero_values: 0,
  warnings: 1,
  findings: [
    {
      check: 'flatlines',
      severity: 'warning',
      message: '1 run of 12 identical non-zero readings (possible stuck meter).',
      count: 12,
      start: '2016-02-20T00:00:00Z',
      end: '2016-02-20T11:00:00Z',
    },
  ],
};

function quality(meters: MeterQuality[] = [METER], total = 4): DatasetQuality {
  return {
    available: true,
    dataset_id: DATASET.dataset_id,
    name: DATASET.name,
    data_kind: 'synthetic',
    assessed_at: '2026-11-02T08:00:00Z',
    quality_version: '1',
    contract_version: '1.0',
    thresholds: { min_coverage_pct: 95, flatline_min_intervals: 6 },
    summary: {
      meters: 4,
      rows: 5376,
      first: '2016-01-04T00:00:00Z',
      last: '2016-02-28T23:00:00Z',
      expected_intervals: 5376,
      available_values: 5370,
      coverage_pct: 99.9,
      meters_with_warnings: 1,
    },
    checks: [
      { check: 'gaps', definition: 'Intervals with no row.', meters: 0 },
      { check: 'flatlines', definition: 'Long runs of identical non-zero readings.', meters: 1 },
    ],
    duplicates_note: 'Duplicate timestamps are rejected by the data contract (duplicate_key).',
    uploads_note: 'Uploaded files are not stored.',
    meters: { items: meters, total, limit: 25, offset: 0 },
  };
}

function stubApi(options: { notAudited?: boolean; failure?: boolean } = {}) {
  const fetch = vi.fn(async (input: string | URL | Request) => {
    await Promise.resolve();
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      'http://localhost',
    );
    if (url.pathname.endsWith('/summary'))
      return jsonResponse({ ...summaryOf(), datasets: [DATASET] });
    if (url.pathname.endsWith('/quality')) {
      if (options.failure) return jsonResponse({}, 503);
      if (options.notAudited)
        return jsonResponse({
          available: false,
          dataset_id: DATASET.dataset_id,
          name: DATASET.name,
          data_kind: 'synthetic',
          message: 'Run python -m wattwise.db.quality to audit it.',
        });
      return jsonResponse(quality());
    }
    if (url.pathname.endsWith('/analysis-runs'))
      return jsonResponse({ items: [ANALYSIS], total: 1, limit: 10, offset: 0 });
    if (url.pathname.endsWith('/health'))
      return jsonResponse({
        status: 'ok',
        service: 'wattwise-api',
        version: '0',
        environment: 'test',
      });
    throw new Error(`Unexpected request ${url.pathname}`);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

function qualityUrls(fetch: ReturnType<typeof stubApi>): URL[] {
  return fetch.mock.calls
    .map(([input]) =>
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
    )
    .map((href) => new URL(href, 'http://localhost'))
    .filter((url) => url.pathname.endsWith('/quality'));
}

beforeEach(() => {
  window.history.replaceState(null, '', '/data');
});
afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Data health', () => {
  it('shows the audit summary, every check, duplicates and the meters', async () => {
    stubApi();
    render(<App />);

    const audit = await screen.findByRole('region', { name: 'Data-quality audit' });
    expect(await within(audit).findByText('99.9% of expected intervals')).toBeInTheDocument();
    expect(within(audit).getByText('1 of 4')).toBeInTheDocument();
    expect(within(audit).getByRole('button', { name: 'Flatlines' })).toBeInTheDocument();
    const checks = within(audit).getByRole('table');
    expect(within(checks).getByText('Gaps')).toBeInTheDocument(); // no meters: not a filter
    expect(within(checks).queryByRole('button', { name: 'Gaps' })).not.toBeInTheDocument();
    expect(within(checks).getByText('Duplicate timestamps')).toBeInTheDocument();
    expect(within(audit).getByText(/possible stuck meter/)).toBeInTheDocument();
    expect(within(audit).getByText(/describe the data, not the buildings/)).toBeInTheDocument();
    expect(within(audit).getByText('Synthetic')).toBeInTheDocument();
    const uploads = screen.getByRole('region', { name: 'Recent uploads' });
    expect(await within(uploads).findByText(/Analysis #/)).toBeInTheDocument();
  });

  it('filters meters by check and by warnings, through the address', async () => {
    const fetch = stubApi();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'Flatlines' }));
    expect(window.location.search).toContain('check=flatlines');
    await user.click(screen.getByRole('checkbox', { name: 'Warnings only' }));
    expect(window.location.search).toContain('warnings=1');

    const last = qualityUrls(fetch).at(-1);
    expect(last?.searchParams.get('check')).toBe('flatlines');
    expect(last?.searchParams.get('warnings_only')).toBe('true');
  });

  it('explains how to audit a dataset loaded before audits were stored', async () => {
    stubApi({ notAudited: true });
    render(<App />);

    expect(await screen.findByText('Not audited yet')).toBeInTheDocument();
    expect(screen.getByText(/python -m wattwise.db.quality/)).toBeInTheDocument();
  });

  it('shows an error with a retry when the audit cannot be loaded', async () => {
    stubApi({ failure: true });
    render(<App />);

    expect(await screen.findByText('Data-quality audit unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('is in the main navigation', async () => {
    stubApi();
    render(<App />);

    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Data health' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await screen.findByRole('region', { name: 'Data-quality audit' });
  });
});

describe('isDatasetQuality', () => {
  it('accepts an audit and a not-audited answer, and rejects a wrong check', () => {
    expect(isDatasetQuality(quality())).toBe(true);
    expect(
      isDatasetQuality({
        available: false,
        dataset_id: 'x',
        name: 'x',
        data_kind: 'observed',
        message: 'm',
      }),
    ).toBe(true);
    const wrong: unknown = {
      ...quality(),
      meters: {
        items: [{ ...METER, findings: [{ ...METER.findings[0], check: 'nope' }] }],
        total: 1,
        limit: 25,
        offset: 0,
      },
    };
    expect(isDatasetQuality(wrong)).toBe(false);
  });
});
