import { useCallback, useEffect, useState } from 'react';

/** `system` follows the operating system's light/dark preference. */
export type ThemeChoice = 'system' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'wattwise.theme';
const CHOICES: readonly string[] = ['system', 'light', 'dark'];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return typeof value === 'string' && CHOICES.includes(value);
}

/** The saved choice, or `system`. Storage can be unavailable (private mode); that is not an error. */
export function readThemeChoice(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(saved) ? saved : 'system';
  } catch {
    return 'system';
  }
}

/** Apply a choice to the document: `data-theme` for light/dark, none for system. */
export function applyThemeChoice(
  choice: ThemeChoice,
  root: HTMLElement = document.documentElement,
) {
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

/** The current theme choice, applied to the document and remembered across visits. */
export function useTheme(): { choice: ThemeChoice; setChoice: (choice: ThemeChoice) => void } {
  const [choice, setChoiceState] = useState<ThemeChoice>(readThemeChoice);

  useEffect(() => {
    applyThemeChoice(choice);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Not remembered, but still applied for this visit.
    }
  }, []);

  return { choice, setChoice };
}
