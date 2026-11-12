import { useCallback, useEffect, useState } from 'react';

/** The application's pages, in navigation order. `task` names the roadmap task that builds it. */
export interface RouteInfo {
  path: string;
  label: string;
  task: string;
  summary: string;
  /** False for a page that shows no stored data (the Bill analyser): the banner that labels the
   * stored datasets as synthetic would otherwise mislabel figures the user typed in. */
  storedData?: false;
}

export const ROUTES: readonly RouteInfo[] = [
  {
    path: '/',
    label: 'Overview',
    task: 'T029',
    summary: 'Measured and expected energy, potential excess, active alerts and data coverage.',
  },
  {
    path: '/explorer',
    label: 'Buildings & meters',
    task: 'T030',
    summary: 'Each meter’s readings against the model’s expectation and interval.',
  },
  {
    path: '/machines',
    label: 'Machines',
    task: 'T066',
    summary:
      'Each meter of a site against its main meter: energy, share, running hours, use while closed and unusual hours.',
  },
  {
    path: '/alerts',
    label: 'Alerts',
    task: 'T031',
    summary: 'The investigation queue, each alert’s evidence, and reviewer feedback.',
  },
  {
    path: '/impact',
    label: 'Cost impact',
    task: 'T032',
    summary: 'Potential excess energy, cost with a configured tariff, and sourced carbon.',
  },
  {
    path: '/whatif',
    label: 'What-if lab',
    task: 'T049',
    summary: 'A meter’s recorded use against the model, with scenarios that never change history.',
  },
  {
    path: '/bill',
    label: 'Bill analyser',
    task: 'T062',
    storedData: false,
    summary:
      'A monthly electricity bill’s charges, demand, time of day and history, worked out from the figures you enter.',
  },
  {
    path: '/meter',
    label: 'Meter check',
    task: 'T067',
    storedData: false,
    summary:
      'A meter file’s demand, use while closed, time of day and unusual periods, read in your browser and never uploaded.',
  },
  {
    path: '/data',
    label: 'Data health',
    task: 'T047',
    summary: 'Each dataset’s data-quality audit: coverage, gaps, flatlines, out-of-range values.',
  },
  {
    path: '/models',
    label: 'Model lab',
    task: 'T033',
    summary: 'The served model, its recorded metrics, datasets and analysis runs.',
  },
];

/** Where the app is served from, without a trailing slash: '' at the root, '/wattwise-ai' on
 * GitHub Pages (T050). Routes are written without it. */
const BASE = import.meta.env.BASE_URL.replace(/\/+$/, '');

/** A browser path without the base, e.g. '/wattwise-ai/alerts' → '/alerts'. */
export function appPath(pathname: string): string {
  if (BASE && (pathname === BASE || pathname.startsWith(`${BASE}/`))) {
    return pathname.slice(BASE.length) || '/';
  }
  return pathname;
}

/** The browser path of a route, e.g. '/alerts' → '/wattwise-ai/alerts'. */
export function href(path: string): string {
  return `${BASE}${path}`;
}

/** The route for a path; unknown paths have none (the shell shows "not found"). */
export function routeFor(path: string): RouteInfo | undefined {
  const normalised = path.length > 1 ? path.replace(/\/+$/, '') : path;
  return ROUTES.find((route) => route.path === normalised);
}

/**
 * The current path, kept in step with the browser's history (back and forward included).
 * A small history-API router: the app has a handful of fixed pages and no route parameters yet.
 */
export function usePath(): { path: string; navigate: (path: string) => void } {
  const [path, setPath] = useState(() => appPath(window.location.pathname));

  useEffect(() => {
    const onPop = () => {
      setPath(appPath(window.location.pathname));
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
    };
  }, []);

  const navigate = useCallback((next: string) => {
    if (next === appPath(window.location.pathname)) return;
    window.history.pushState(null, '', href(next));
    setPath(next);
  }, []);

  return { path, navigate };
}

/**
 * The query string as parameters, kept in step with the browser's history. `setParams` changes
 * parameters (a `null` value removes one) and adds a history entry, so Back returns to the previous
 * selection. Used for what a person may want to link to, such as the selected meter.
 */
export function useSearch(): {
  params: URLSearchParams;
  setParams: (updates: Record<string, string | null>) => void;
} {
  const [search, setSearch] = useState(() => window.location.search);

  useEffect(() => {
    const onPop = () => {
      setSearch(window.location.search);
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
    };
  }, []);

  const setParams = useCallback((updates: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    const text = next.toString();
    window.history.pushState(null, '', `${window.location.pathname}${text ? `?${text}` : ''}`);
    setSearch(window.location.search);
  }, []);

  return { params: new URLSearchParams(search), setParams };
}
