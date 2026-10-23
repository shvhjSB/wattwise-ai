# Project status

**Last updated:** 2026-10-23 · **Current milestone:** M1 — Repository audit and application foundation

## Summary

The application foundation runs end to end locally. A CI workflow is written and validated
locally, but it has **not yet run on GitHub**:

- **Backend:** a FastAPI service with a liveness endpoint (`GET /api/v1/health`) and OpenAPI
  docs. It passes pytest, ruff and strict mypy. Dependencies are locked across platforms in
  `backend/uv.lock` with PEP 735 `[dependency-groups]`.
- **Frontend:** a React + TypeScript + Vite + Tailwind shell. It calls the API through a typed,
  runtime-validated client and shows loading, online and error-with-retry states. It passes
  type checking, ESLint (including accessibility rules), Prettier and Vitest, and builds for
  production.
- **CI (in progress, T004):** a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs
  all backend and frontend checks on Ubuntu 24.04 for pushes and pull requests. It uses
  SHA-pinned actions and dependency caching. T004 is complete only once a run on GitHub is green.

No dataset has been downloaded and no model has been trained, so no ML metrics exist yet.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | 2026-10-23 |

## Current task

**T004 — CI baseline** (in progress):
- The workflow and the backend lock (`uv.lock`) are written.
- Done locally: actionlint passes, both jobs pass in Linux containers, and the adversarial review
  is complete, with all 6 confirmed findings fixed (see WORK_LOG).
- Remaining: push, then the first green run on GitHub.

## Next task

**T005 — Canonical data contracts and CSV upload format**: one internal representation of
meter readings, meters/buildings and weather, shared by every pipeline stage and the API. See
[ROADMAP.md](ROADMAP.md#t005--canonical-data-contracts-and-csv-upload-format).

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
| Python 3.13 + `backend/.venv` | Verified (T002). Managed by uv since T004 |
| uv 0.12.24 (winget `astral-sh.uv`) | Verified 2026-10-23: `uv sync --locked` and all backend checks pass |
| Node 24 / npm 11 | Verified (T003) |
| PostgreSQL 18.6 (service `postgresql-x64-18`, local connections only) | Verified 2026-10-23 (D007) |
| Docker Desktop 4.96.3 (engine 29.9.2, Compose v5.6.1, WSL2) | Verified 2026-10-23 after the restart: `docker run --rm hello-world` succeeded |

## Known risks

| Risk | Affects | Mitigation |
|---|---|---|
| `shvhjSB`'s `gh` token lacks the `workflow` scope; GitHub rejects pushes that add or change `.github/workflows/*` without it | **T004 (current)** | If the push is rejected, the owner runs three commands. (1) `gh auth switch -h github.com -u shvhjSB`. (2) `gh auth refresh -h github.com -s workflow`, approving in a browser signed in as `shvhjSB`. (3) Switch back to the previously active account with `gh auth switch -h github.com -u aman-agntworksai`. Then the push is retried. Claude never switches the global account itself |
| The push identity is pinned only in this clone's `.git/config` | Every push from another clone | Repeat the D006 setup in any new clone. The commands are in WORK_LOG (T002) |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence discrepancy (CC BY 4.0 vs CC BY-SA 4.0) | T007, T009 | Resolve and document in T007 before using the data |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
