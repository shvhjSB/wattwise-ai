# Project status

**Last updated:** 2026-10-23 · **Current milestone:** M2 — Data contracts, schemas and dataset acquisition (M1 complete)

## Summary

The application foundation runs end to end locally, and CI checks it automatically on GitHub:

- **Backend:** a FastAPI service with a liveness endpoint (`GET /api/v1/health`) and OpenAPI
  docs. It passes pytest, ruff and strict mypy. Dependencies are locked across platforms in
  `backend/uv.lock`, and the build backend is pinned too.
- **Frontend:** a React + TypeScript + Vite + Tailwind shell. It calls the API through a typed,
  runtime-validated client and shows loading, online and error-with-retry states. It passes
  type checking, ESLint (including accessibility rules), Prettier and Vitest, and builds for
  production.
- **CI:** a GitHub Actions workflow (`.github/workflows/ci.yml`) runs all backend and frontend
  checks on Ubuntu 24.04 for pushes to `main` and for pull requests. It uses SHA-pinned actions,
  a checksum-verified uv download and lockfile-keyed caches. The first run on GitHub was green:
  [run 39951620258](https://github.com/shvhjSB/wattwise-ai/actions/runs/39951620258) for
  `6948af4`. CI reports results but does not block merges; `main` has no branch protection (D011).
- **Data contract (v1.0):** one canonical shape for readings, buildings and weather, with a
  validator that turns CSV uploads or in-memory tables into canonical form. It reports every
  structural problem with a stable code, the affected rows and a fix hint.
  [docs/DATA_CONTRACT.md](DATA_CONTRACT.md) documents it, and a test keeps the document truthful.

No dataset has been downloaded and no model has been trained, so no ML metrics exist yet.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | 2026-10-23 |
| T004 | CI baseline (GitHub Actions, uv lock, SHA-pinned workflow) | 2026-10-23 |
| T005 | Canonical data contracts and CSV upload format | 2026-10-23 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T006 — Deterministic synthetic fixture generator**: a seeded generator for a few buildings
and meters, with daily and weekly patterns, temperature dependence and documented injected
anomalies (labels marked synthetic). It produces a tiny committed fixture under `data/sample/`
that conforms to the T005 contract. See
[ROADMAP.md](ROADMAP.md#t006--deterministic-synthetic-fixture-generator).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 4 / 4 |
| M2 Data contracts and acquisition | T005–T007 | 1 / 3 |
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

The `workflow`-scope push blocker was resolved on 2026-10-23. At the owner's request, `shvhjSB`'s
`gh` token was refreshed with the `workflow` scope (device-flow approval by the owner). The
global active account was then switched back to `aman-agntworksai`. This repo still commits and
pushes only as `shvhjSB` (D006).

## Development environment

| Component | Status |
|---|---|
| Python 3.13 + `backend/.venv` | Verified (T002). Managed by uv since T004 |
| uv 0.12.24 (winget `astral-sh.uv`) | Verified 2026-10-23: `uv sync --locked` and all backend checks pass |
| Node 24 / npm 11 | Verified (T003) |
| PostgreSQL 18.6 (service `postgresql-x64-18`, local connections only) | Verified 2026-10-23 (D007) |
| Docker Desktop 4.96.3 (engine 29.9.2, Compose v5.6.1, WSL2) | Verified 2026-10-23 after the restart: `docker run --rm hello-world` succeeded |
| GitHub push identity `shvhjSB` (scopes: repo, workflow, gist, read:org) | Verified 2026-10-23 by pushing `.github/workflows/ci.yml` |

## Known risks

| Risk | Affects | Mitigation |
|---|---|---|
| The push identity is pinned only in this clone's `.git/config` | Every push from another clone | Repeat the D006 setup in any new clone. The commands are in WORK_LOG (T002) |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence discrepancy (CC BY 4.0 vs CC BY-SA 4.0) | T007, T009 | Resolve and document in T007 before using the data |
| BDG2 data files are stored in Git LFS (the repository holds 130-byte pointer files) | T007 | Download through GitHub's LFS media endpoint. GitHub LFS bandwidth limits may apply |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
| Pinned action SHAs, uv version and uv checksum do not update themselves | Security updates | Deliberate upgrades under the two-week rule. A uv upgrade changes three places together (D011) |
