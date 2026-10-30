import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import type { AlertDetail, Feedback } from '../api/alerts';
import { alertDetail, alertSummary, feedback } from '../test/alertFixture';
import { page, series } from '../test/expectationFixture';
import { jsonResponse } from '../test/http';
import { kindSummary, summaryOf } from '../test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

interface ApiOptions {
  alerts?: ReturnType<typeof alertSummary>[];
  alertError?: number;
  queueError?: number;
  total?: number;
}

function stubApi(options: ApiOptions = {}) {
  let detail: AlertDetail = alertDetail();
  let nextFeedback = 20;
  const alerts = options.alerts ?? [
    alertSummary(1),
    alertSummary(2, {
      building_id: 'B2',
      meter_id: 'B2:electricity',
      severity: 'medium',
      priority_score: 48,
      signature: 'overnight_excess',
    }),
  ];
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost');
    if (url.pathname === '/api/v1/health') return jsonResponse(HEALTH);
    if (url.pathname === '/api/v1/dashboard/summary') {
      return jsonResponse(summaryOf(kindSummary('observed')));
    }
    if (url.pathname === '/api/v1/alerts' && (init?.method ?? 'GET') === 'GET') {
      if (options.queueError) return jsonResponse({ detail: 'broken' }, options.queueError);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      return jsonResponse(page(alerts, options.total ?? alerts.length, 25, offset));
    }
    const match = /^\/api\/v1\/alerts\/(\d+)$/.exec(url.pathname);
    if (match && (init?.method ?? 'GET') === 'GET') {
      if (options.alertError) return jsonResponse({ detail: 'missing' }, options.alertError);
      const id = Number(match[1]);
      const summary = alerts.find((item) => item.alert_id === id) ?? alertSummary(id);
      return jsonResponse({ ...detail, ...summary, alert_id: id });
    }
    const feedbackMatch = /^\/api\/v1\/alerts\/(\d+)\/feedback$/.exec(url.pathname);
    if (feedbackMatch && init?.method === 'POST') {
      if (typeof init.body !== 'string') throw new Error('expected a JSON request body');
      const body = JSON.parse(init.body) as {
        label: Feedback['label'];
        note?: string;
        reviewer?: string;
      };
      const saved = feedback({
        feedback_id: nextFeedback++,
        alert_id: Number(feedbackMatch[1]),
        label: body.label,
        note: body.note ?? null,
        reviewer: body.reviewer ?? null,
      });
      detail = {
        ...detail,
        review_status: saved.label,
        reviewed_at: saved.created_at,
        feedback_count: detail.feedback_count + 1,
        feedback: [...detail.feedback, saved],
      };
      return jsonResponse(saved, 201);
    }
    if (url.pathname.endsWith('/expectation')) return jsonResponse(series());
    return Promise.reject(new Error(`unexpected request: ${raw}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function requestUrls(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(([input]) =>
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
  );
}

beforeEach(() => {
  window.history.replaceState(null, '', '/alerts');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('Alerts page', () => {
  it('shows the loading and empty queue states', async () => {
    stubApi({ alerts: [] });
    render(<App />);

    expect(screen.getByText('Loading alert queue...')).toBeInTheDocument();
    expect(await screen.findByText('No alerts match')).toBeInTheDocument();
    expect(screen.getByText('Choose an alert')).toBeInTheDocument();
  });

  it('opens the highest-priority alert with its evidence, charts, assumptions, and caveats', async () => {
    stubApi();
    render(<App />);

    expect(await screen.findByRole('heading', { level: 3, name: 'B1' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Alerts ordered by priority' })).toBeInTheDocument();
    expect(screen.getByText(/This is an anomaly to investigate/)).toBeInTheDocument();
    expect(
      screen.getByText('Check the operating schedule and equipment overrides.'),
    ).toBeInTheDocument();
    expect(screen.getByText('same hour mean 4w')).toBeInTheDocument();
    expect(screen.getByText(/not confirmed waste/)).toBeInTheDocument();
    expect(
      await screen.findByRole('img', { name: /Observed and expected energy/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Observed minus expected/ })).toBeInTheDocument();
  });

  it('selects another alert and keeps the selection in the address', async () => {
    stubApi();
    render(<App />);

    const queue = await screen.findByRole('list', { name: 'Alerts ordered by priority' });
    await userEvent.click(within(queue).getByRole('button', { name: /B2/ }));

    expect(window.location.search).toBe('?alert=2');
    expect(await screen.findByRole('heading', { level: 3, name: 'B2' })).toBeInTheDocument();
  });

  it('applies supported filters through the URL and API query', async () => {
    const fetchMock = stubApi();
    render(<App />);
    await screen.findByRole('heading', { level: 3, name: 'B1' });
    const filters = screen.getByRole('form', { name: 'Alert filters' });

    await userEvent.selectOptions(within(filters).getByLabelText('Severity'), 'high');
    await userEvent.selectOptions(within(filters).getByLabelText('Review status'), 'unreviewed');
    await userEvent.selectOptions(within(filters).getByLabelText('Pattern'), 'sustained');
    await userEvent.type(within(filters).getByLabelText('Building ID'), 'B1');
    await userEvent.click(within(filters).getByRole('button', { name: 'Apply filters' }));

    await vi.waitFor(() => {
      expect(window.location.search).toContain('severity=high');
      expect(
        requestUrls(fetchMock).some(
          (url) =>
            url.includes('/api/v1/alerts?') &&
            url.includes('severity=high') &&
            url.includes('review_status=unreviewed') &&
            url.includes('signature=sustained') &&
            url.includes('building_id=B1'),
        ),
      ).toBe(true);
    });
  });

  it('paginates the queue without carrying a selected alert', async () => {
    const fetchMock = stubApi({ total: 60 });
    render(<App />);

    await userEvent.click(await screen.findByRole('button', { name: 'Next' }));

    await vi.waitFor(() => {
      expect(window.location.search).toBe('?page=1');
      expect(requestUrls(fetchMock).some((url) => url.includes('offset=25'))).toBe(true);
    });
  });

  it('records feedback, then shows it in the append-only review history', async () => {
    const fetchMock = stubApi();
    render(<App />);
    await screen.findByRole('heading', { level: 3, name: 'B1' });

    await userEvent.click(screen.getByRole('radio', { name: /Expected behaviour/ }));
    await userEvent.type(screen.getByLabelText(/Reviewer/), 'ops-7');
    await userEvent.type(screen.getByLabelText(/Note/), 'Scheduled commissioning.');
    await userEvent.click(screen.getByRole('button', { name: 'Save review' }));

    expect(await screen.findByText('Scheduled commissioning.')).toBeInTheDocument();
    const history = screen.getByRole('heading', { name: 'Review history' }).parentElement;
    if (!history) throw new Error('expected review history section');
    expect(within(history).getByText('Expected behaviour')).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post?.[1]?.body).toBe(
      JSON.stringify({
        label: 'expected_behaviour',
        note: 'Scheduled commissioning.',
        reviewer: 'ops-7',
      }),
    );
  });

  it('shows queue and stale-link failures plainly', async () => {
    stubApi({ queueError: 503 });
    const first = render(<App />);
    expect(await screen.findByText('The alert queue is unavailable')).toBeInTheDocument();

    first.unmount();
    window.history.replaceState(null, '', '/alerts?alert=999');
    stubApi({ alertError: 404 });
    render(<App />);
    expect(await screen.findByText('This alert is unavailable')).toBeInTheDocument();
    expect(screen.getByText('There is no alert 999.')).toBeInTheDocument();
  });
});
