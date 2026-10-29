import { useCallback, useEffect, useState } from 'react';

/** The application's pages, in navigation order. `task` names the roadmap task that builds it. */
export interface RouteInfo {
  path: string;
  label: string;
  task: string;
  summary: string;
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
    path: '/models',
    label: 'Model lab',
    task: 'T033',
    summary: 'The served model, its recorded metrics, datasets and analysis runs.',
  },
];

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
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => {
      setPath(window.location.pathname);
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
    };
  }, []);

  const navigate = useCallback((next: string) => {
    if (next === window.location.pathname) return;
    window.history.pushState(null, '', next);
    setPath(next);
  }, []);

  return { path, navigate };
}
