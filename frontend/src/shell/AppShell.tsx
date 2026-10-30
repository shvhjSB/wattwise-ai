import type { MouseEvent, ReactNode } from 'react';

import type { DataKind } from '../api/summary';
import { DemoBanner } from '../design/Provenance';
import { ROUTES } from '../design/routes';
import { isThemeChoice, type ThemeChoice } from '../design/theme';

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

/** Plain left clicks navigate in the app; modified clicks keep the browser's behaviour. */
function isPlainClick(event: MouseEvent): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export function AppShell({
  path,
  navigate,
  dataKinds,
  theme,
  onThemeChange,
  children,
}: {
  path: string;
  navigate: (path: string) => void;
  dataKinds: readonly DataKind[] | null;
  theme: ThemeChoice;
  onThemeChange: (theme: ThemeChoice) => void;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-surface text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-raised focus:px-3 focus:py-2 focus:text-sm focus:shadow"
      >
        Skip to content
      </a>

      <header className="border-b border-line bg-raised">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-4">
          <div className="mr-auto">
            <h1 className="text-lg font-semibold tracking-tight">WattWise AI</h1>
            <p className="text-xs text-muted">Explainable energy-waste detection</p>
          </div>

          <nav aria-label="Main" className="min-w-0 basis-full md:basis-auto">
            <ul className="flex flex-wrap gap-1 text-sm">
              {ROUTES.map((route) => {
                const current = route.path === path;
                return (
                  <li key={route.path}>
                    <a
                      href={route.path}
                      aria-current={current ? 'page' : undefined}
                      onClick={(event) => {
                        if (!isPlainClick(event)) return;
                        event.preventDefault();
                        navigate(route.path);
                      }}
                      className={`block rounded-md px-3 py-1.5 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                        current
                          ? 'bg-accent text-accent-ink'
                          : 'text-muted hover:bg-sunken hover:text-ink'
                      }`}
                    >
                      {route.label}
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>

          <label className="flex items-center gap-2 text-xs text-muted">
            Theme
            <select
              value={theme}
              onChange={(event) => {
                if (isThemeChoice(event.target.value)) onThemeChange(event.target.value);
              }}
              className="rounded-md border border-edge bg-raised px-2 py-1 text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              {THEMES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {dataKinds ? <DemoBanner kinds={dataKinds} /> : null}

      <main
        id="main"
        tabIndex={-1}
        className="mx-auto max-w-6xl space-y-6 px-6 py-8 focus:outline-none"
      >
        {children}
      </main>
    </div>
  );
}
