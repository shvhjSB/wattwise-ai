# Project status

**Last updated:** 2026-10-24 · **Current milestone:** M3 — Data validation and preprocessing (M1 and M2 complete)

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
- **Synthetic sample data:** a deterministic, clearly labelled synthetic dataset in
  [data/sample/synthetic/](../data/sample/synthetic/README.md). It has 4 buildings, 8 weeks of
  hourly electricity and weather, and 6 injected anomalies with labels. It is for tests, the
  demo mode and synthetic benchmarks.
- **BDG2 acquisition:** a pinned, checksum-verified download of the BDG2 files (about 369 MB)
  into git-ignored `data/raw/bdg2/`, with provenance recorded in
  [data/manifests/bdg2.json](../data/manifests/bdg2.json). Licence evidence and data conventions
  are in [docs/DATASETS.md](DATASETS.md). The files were downloaded and verified on 2026-10-23.

- **Data quality:** an engine that runs after the contract and describes the data with nine checks
  (gaps, missing values, coverage, negatives, zero runs, flatlines, extreme values, intensity and
  more) in deterministic JSON and Markdown reports ([docs/DATA_QUALITY.md](DATA_QUALITY.md)). On
  the synthetic sample it finds exactly the two injected data faults
  ([example report](reports/synthetic-data-quality.md)).

- **BDG2 timestamp audit:** BDG2's local timestamps follow a **different clock per site**. The
  audit found 11 wall-clock sites, 3 standard-time sites and 5 undetermined (excluded) for
  electricity, and standard time for weather at all 19 sites. The verdicts are evidence-based,
  pinned, and re-checkable with `python -m wattwise.data.bdg2_audit` (D016,
  [DATASETS.md](DATASETS.md)).

The BDG2 data has been downloaded and audited, but not yet converted to the canonical format
(T009b). No model has been trained, so no
ML metrics exist yet.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | 2026-10-23 |
| T004 | CI baseline (GitHub Actions, uv lock, SHA-pinned workflow) | 2026-10-23 |
| T005 | Canonical data contracts and CSV upload format | 2026-10-23 |
| T006 | Deterministic synthetic fixture generator | 2026-10-23 |
| T007 | BDG2 acquisition tooling and dataset documentation | 2026-10-23 |
| T008 | Data-quality engine and report | 2026-10-23 |
| T009a | BDG2 timestamp-convention audit | 2026-10-24 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T009b — BDG2 preprocessing pipeline**: deterministically convert the downloaded BDG2 files
into the canonical format for a laptop-sized subset. That means:
- electricity only, with a seeded meter sample and wide-to-long reshaping
- UTC conversion with the pinned per-site clocks from T009a, excluding undetermined sites
- a weather join and an exclusion log
- a T008 quality report, with Parquet output and a manifest

See [ROADMAP.md](ROADMAP.md#t009b--bdg2-preprocessing-pipeline).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 4 / 4 |
| M2 Data contracts and acquisition | T005–T007 | 3 / 3 |
| M3 Validation and preprocessing | T008, T009a, T009b, T010 | 2 / 4 |
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
| BDG2 licence: four sources state MIT, CC BY 4.0 or CC BY-SA | T038 (public display) | Handled conservatively (D014): attribution, no redistribution of raw or derived data. Public display of BDG2-derived results is an owner decision at T038 |
| 5 of 19 BDG2 sites (522 buildings, including Rat with 305) have an undetermined electricity clock and are excluded | T009b and later | Excluded rather than guessed (D016). Per-building classification for mixed sites is possible later |
| BDG2 interval start/end cannot be determined from the data | T009b | Interval-start assumed explicitly: at most a 1-hour labelling uncertainty (D016) |
| GitHub LFS bandwidth for future re-downloads | Re-fetching BDG2 | Verified local copies are never re-downloaded; HTTP 403/429 messages explain quota limits |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
| Pinned action SHAs, uv version and uv checksum do not update themselves | Security updates | Deliberate upgrades under the two-week rule. A uv upgrade changes three places together (D011) |
