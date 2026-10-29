import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  applyThemeChoice,
  isThemeChoice,
  readThemeChoice,
  THEME_STORAGE_KEY,
  useTheme,
} from './theme';

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

describe('theme choice', () => {
  it('recognises only the three choices', () => {
    expect(['system', 'light', 'dark'].every(isThemeChoice)).toBe(true);
    expect(isThemeChoice('sepia')).toBe(false);
    expect(isThemeChoice(null)).toBe(false);
  });

  it('defaults to following the system', () => {
    expect(readThemeChoice()).toBe('system');
  });

  it('ignores a saved value that is not a choice', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'sepia');

    expect(readThemeChoice()).toBe('system');
  });

  it('survives storage being unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(readThemeChoice()).toBe('system');
  });

  it('sets data-theme for light and dark and removes it for system', () => {
    const root = document.createElement('html');

    applyThemeChoice('dark', root);
    expect(root.getAttribute('data-theme')).toBe('dark');
    applyThemeChoice('light', root);
    expect(root.getAttribute('data-theme')).toBe('light');
    applyThemeChoice('system', root);
    expect(root.hasAttribute('data-theme')).toBe(false);
  });
});

describe('useTheme', () => {
  it('applies and remembers a choice', () => {
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.setChoice('dark');
    });

    expect(result.current.choice).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('starts from the remembered choice', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');

    const { result } = renderHook(() => useTheme());

    expect(result.current.choice).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('still applies a choice when it cannot be saved', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.setChoice('dark');
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });
});
