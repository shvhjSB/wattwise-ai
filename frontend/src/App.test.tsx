import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { THEME_STORAGE_KEY } from './design/theme';
import { jsonResponse } from './test/http';
import { kindSummary, summaryOf } from './test/summaryFixture';

const HEALTH = { status: 'ok', service: 'wattwise-api', version: '0.1.0', environment: 'test' };

/** Stub the API: health, and the dashboard summary with the given data kinds (or a failure). */
function stubApi(kinds: ('synthetic' | 'observed')[] | 'unavailable') {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/v1/health')) return Promise.resolve(jsonResponse(HEALTH));
      if (url.endsWith('/api/v1/dashboard/summary')) {
        return Promise.resolve(
          kinds === 'unavailable'
            ? jsonResponse({ detail: { database: 'not_configured' } }, 503)
            : jsonResponse(summaryOf(...kinds.map((kind) => kindSummary(kind)))),
        );
      }
      return Promise.reject(new Error(`unexpected request: ${url}`));
    }),
  );
}

beforeEach(() => {
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  window.history.replaceState(null, '', '/');
});

describe('App shell', () => {
  it('renders the product shell and the API connection panel', async () => {
    stubApi([]);

    render(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'WattWise AI' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'API connection' })).toBeInTheDocument();
    expect(await screen.findByText('Online')).toBeInTheDocument();
  });

  it('has a skip link and a labelled main navigation', () => {
    stubApi([]);

    render(<App />);

    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(nav).toBeInTheDocument();
    expect(screen.getAllByRole('link', { current: 'page' })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Overview', current: 'page' })).toBeInTheDocument();
  });

  it('navigates between pages without a reload and marks the current one', async () => {
    stubApi([]);
    render(<App />);

    await userEvent.click(screen.getByRole('link', { name: 'Alerts' }));

    expect(window.location.pathname).toBe('/alerts');
    expect(screen.getByRole('heading', { level: 2, name: 'Alerts' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Alerts', current: 'page' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { current: 'page' })).toHaveLength(1);
  });

  it('says plainly that a later page is not built yet, and which task builds it', () => {
    stubApi([]);
    window.history.replaceState(null, '', '/models');

    render(<App />);

    expect(screen.getByRole('heading', { level: 2, name: 'Model lab' })).toBeInTheDocument();
    expect(screen.getByText('Not built yet')).toBeInTheDocument();
    expect(screen.getByText(/roadmap task T033/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'API connection' })).not.toBeInTheDocument();
  });

  it('shows a not-found page for an unknown address, with a way home', async () => {
    stubApi([]);
    window.history.replaceState(null, '', '/nowhere');

    render(<App />);

    expect(screen.getByText('Page not found')).toBeInTheDocument();
    expect(screen.queryAllByRole('link', { current: 'page' })).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: 'Go to the overview' }));
    expect(window.location.pathname).toBe('/');
    expect(screen.getByRole('heading', { level: 2, name: 'Overview' })).toBeInTheDocument();
  });

  it('lets a modified click open the page the browser’s way', () => {
    stubApi([]);
    render(<App />);
    const link = screen.getByRole('link', { name: 'Alerts' });

    // fireEvent returns false when the handler called preventDefault.
    const notPrevented = fireEvent.click(link, { ctrlKey: true });

    expect(notPrevented).toBe(true);
    expect(window.location.pathname).toBe('/');
    expect(fireEvent.click(link)).toBe(false); // a plain click is handled in the app
    expect(window.location.pathname).toBe('/alerts');
  });
});

describe('demo-data banner', () => {
  it('appears when only synthetic data is stored', async () => {
    stubApi(['synthetic']);

    render(<App />);

    const note = await screen.findByRole('note', { name: 'Demo data' });
    expect(note).toHaveTextContent('Everything shown is synthetic');
  });

  it('stays on every page', async () => {
    stubApi(['synthetic']);
    window.history.replaceState(null, '', '/alerts');

    render(<App />);

    expect(await screen.findByRole('note', { name: 'Demo data' })).toBeInTheDocument();
  });

  it('is absent for observed data', async () => {
    stubApi(['observed']);

    render(<App />);

    await screen.findByText('Online');
    await waitFor(() => {
      expect(screen.queryByRole('note')).not.toBeInTheDocument();
    });
  });

  it('is absent when the summary is unavailable, and the overview explains why', async () => {
    stubApi('unavailable');

    render(<App />);

    await screen.findByText('Online');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    // The banner stays silent; the overview page says what is wrong and how to fix it.
    expect(await screen.findByText('The overview is unavailable')).toBeInTheDocument();
  });
});

describe('theme', () => {
  it('switches theme from the header, applies it and remembers it', async () => {
    stubApi([]);
    render(<App />);

    await userEvent.selectOptions(screen.getByLabelText('Theme'), 'dark');

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(screen.getByLabelText('Theme')).toHaveValue('dark');
  });

  it('follows the system until a theme is chosen', () => {
    stubApi([]);

    render(<App />);

    expect(screen.getByLabelText('Theme')).toHaveValue('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});
