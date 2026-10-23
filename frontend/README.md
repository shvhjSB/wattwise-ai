# WattWise AI — frontend

React 19 + TypeScript + Vite 8 + Tailwind CSS 4. Tested with Vitest and React Testing Library.
Tooling choices and version constraints are recorded in
[docs/DECISIONS.md](../docs/DECISIONS.md), D008 and D009.

```
src/
  api/          typed HTTP client (runtime-validated responses) and one module per API resource
  features/     feature folders: components, hooks and their tests, side by side
  test/         test setup and shared test helpers
  App.tsx       application shell
  main.tsx      entry point
```

## Setup

Requires Node.js 22.12 or newer (developed on Node 24) and npm.

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
