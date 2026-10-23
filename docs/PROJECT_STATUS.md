# Project status

**Last updated:** 2026-10-23 · **Current milestone:** M1 — Repository audit and application foundation

## Summary

The application foundation runs end to end on the development machine:

- **Backend:** a FastAPI service with a liveness endpoint (`GET /api/v1/health`) and OpenAPI
  docs. It passes pytest, ruff and strict mypy.
- **Frontend:** a React + TypeScript + Vite + Tailwind shell. It calls the API through a typed,
  runtime-validated client and shows loading, online and error-with-retry states. It passes
  type checking, ESLint (including accessibility rules), Prettier and Vitest, and builds for
  production.

No dataset has been downloaded and no model has been trained, so no ML metrics exist yet.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | 2026-10-23 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T004 — CI baseline**: a GitHub Actions workflow that runs the backend checks (ruff, mypy,
pytest) and the frontend checks (`npm ci`, lint, typecheck, format, test, build) on every push
and pull request. It also settles the backend dependency-lock strategy. See
[ROADMAP.md](ROADMAP.md#t004--ci-baseline).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 3 / 4 |
| M2 Data contracts and acquisition | T005–T007 | 0 / 3 |
| M3 Validation and preprocessing | T008–T010 | 0 / 3 |
| M4 Baselines | T011–T012 | 0 / 2 |
| M5 Improved model | T013–T015 | 0 / 3 |
| M6 Anomaly detection | T016–T018 | 0 / 3 |
| M7 Explainability and uncertainty | T019–T020 | 0 / 2 |
| M8 Business impact | T021–T022 | 0 / 2 |
| M9 API and persistence | T023–T027 | 0 / 5 |
| M10 Frontend workflows | T028–T033 | 0 / 6 |
| M11 Integration | T034–T035 | 0 / 2 |
| M12 Operations and docs | T036–T039 | 0 / 4 |

## Blockers

None.

## Development environment

| Component | Status |
|---|---|
| Python 3.13 + `backend/.venv` | Verified (T002) |
| Node 24 / npm 11 | Verified (T003) |
| PostgreSQL 18.6 (service `postgresql-x64-18`, local connections only) | Verified 2026-10-23 (D007) |
| Docker Desktop 4.96.3 (engine 29.9.2, Compose v5.6.1, WSL2) | Verified 2026-10-23 after the restart: `docker run --rm hello-world` succeeded |

## Known risks

| Risk | Affects | Mitigation |
|---|---|---|
| `shvhjSB`'s `gh` token lacks the `workflow` scope; GitHub rejects pushes that add or change `.github/workflows/*` without it | **T004 (next)** | If the push is rejected, the owner runs `gh auth refresh -h github.com -s workflow` while `shvhjSB` is selected, then the push is retried |
| The push identity is pinned only in this clone's `.git/config` | Every push from another clone | Repeat the D006 setup in any new clone. The commands are in WORK_LOG (T002) |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence discrepancy (CC BY 4.0 vs CC BY-SA 4.0) | T007, T009 | Resolve and document in T007 before using the data |
| Backend dependencies are bounded but not locked (the frontend is locked) | Reproducible CI and Docker builds | Backend lock strategy decided in T004 (D003) |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
