# WattWise AI — frontend

React 19 + TypeScript + Vite 8 + Tailwind CSS 4. Tested with Vitest and React Testing Library.
Tooling choices and version constraints are recorded in
[docs/DECISIONS.md](../docs/DECISIONS.md), D008 and D009.

```
src/
  api/          typed HTTP client (runtime-validated responses) and one module per API resource
  design/       colour-token themes, routes, provenance badge and demo banner, shared states (D050)
  design/chart/ hand-written SVG charts and their tested arithmetic (D052)
  features/     feature folders: components, hooks and their tests, side by side
                (`summary/` shares the dashboard summary; `alerts/` is the investigation workflow)
  pages/        overview, explorer and alert workflows, planned pages and the not-found page
  shell/        the application frame: header, navigation, theme switch
  test/         test setup and shared test helpers
  App.tsx       routing and composition
  main.tsx      entry point
```

## Design system

Colours are tokens declared in [`src/index.css`](src/index.css) (D050). Use the token utilities
(`bg-surface`, `bg-raised`, `text-ink`, `text-muted`, `border-line`, `border-edge`, `bg-accent`,
`text-danger`, ...), never raw palette colours: a theme is a set of token values. `border-line` is for
decorative dividers; controls use `border-edge`. A test (`design/tokens.test.ts`) checks WCAG
contrast for every pair in both themes, so a new pair is added to its list.

Every page marks where its data comes from with `ProvenanceBadge`, and the shell shows
`DemoBanner` while synthetic data is stored. Show loading, empty and error states with the shared
`LoadingState`, `EmptyState` and `ErrorState`. Pages are listed in `design/routes.ts`.

## Setup

Requires Node.js `^22.22.2`, `^24.15.0` or `>=26`. That range comes from the locked test
toolchain (jsdom); see `engines` in `package.json`. The project is developed on Node 24, and CI
uses the latest Node 24 release per [`.nvmrc`](.nvmrc).

```bash
cd frontend
npm ci
```

## Develop

Start the backend first (see [backend/README.md](../backend/README.md)), then:

```bash
npm run dev
```

Open <http://127.0.0.1:5173>. The dev server proxies `/api/*` to the backend at
`http://127.0.0.1:8000`, so the browser makes same-origin requests and needs no CORS
configuration.

## Checks

Run these before every commit:

```bash
npm run typecheck      # tsc -b, strict
npm run lint           # ESLint: typescript-eslint strict, React hooks, jsx-a11y; zero warnings
npm run format:check   # Prettier
npm test               # Vitest + React Testing Library (jsdom)
npm run build          # type check + production build to dist/
```

## Configuration

Copy [`.env.example`](.env.example) to `.env.local` for local overrides. Variables prefixed with
`VITE_` are embedded in the public bundle, so never put secrets in them.

| Variable                  | Used by         | Default                 | Purpose                                            |
| ------------------------- | --------------- | ----------------------- | -------------------------------------------------- |
| `VITE_API_BASE_URL`       | browser bundle  | empty (same origin)     | Absolute API URL when the API is on another origin |
| `WATTWISE_DEV_API_TARGET` | dev server only | `http://127.0.0.1:8000` | Where `npm run dev` proxies `/api`                 |
