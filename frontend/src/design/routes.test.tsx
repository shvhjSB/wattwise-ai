import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ROUTES, routeFor, usePath } from './routes';

beforeEach(() => {
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('routes', () => {
  it('has unique paths, starting with the overview', () => {
    expect(ROUTES[0]?.path).toBe('/');
    expect(new Set(ROUTES.map((route) => route.path)).size).toBe(ROUTES.length);
  });

  it('names the task that builds each page', () => {
    expect(ROUTES.map((route) => route.task)).toEqual(['T029', 'T030', 'T031', 'T032', 'T033']);
  });

  it('finds a route by path, ignoring a trailing slash', () => {
    expect(routeFor('/alerts')?.label).toBe('Alerts');
    expect(routeFor('/alerts/')?.label).toBe('Alerts');
    expect(routeFor('/')?.label).toBe('Overview');
  });

  it('has no route for an unknown path', () => {
    expect(routeFor('/nope')).toBeUndefined();
    expect(routeFor('/alerts/1')).toBeUndefined();
  });
});

describe('usePath', () => {
  it('starts at the current address', () => {
    window.history.replaceState(null, '', '/models');

    const { result } = renderHook(() => usePath());

    expect(result.current.path).toBe('/models');
  });

  it('navigates and updates the address bar', () => {
    const { result } = renderHook(() => usePath());

    act(() => {
      result.current.navigate('/alerts');
    });

    expect(result.current.path).toBe('/alerts');
    expect(window.location.pathname).toBe('/alerts');
  });

  it('does not add a history entry for the page it is already on', () => {
    const { result } = renderHook(() => usePath());
    const before = window.history.length;

    act(() => {
      result.current.navigate('/');
    });

    expect(window.history.length).toBe(before);
  });

  it('follows the back button', () => {
    const { result } = renderHook(() => usePath());
    act(() => {
      result.current.navigate('/alerts');
    });

    act(() => {
      window.history.replaceState(null, '', '/impact');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(result.current.path).toBe('/impact');
  });
});
