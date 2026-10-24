# Project status

**Last updated:** 2026-10-24 · **Current milestone:** M4 — Baseline forecasting and evaluation (M1, M2 and M3 complete)

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

- **BDG2 timestamp audit:** BDG2's local timestamps follow a **different clock per site**.
  - **Electricity:** 11 wall-clock sites, 4 fixed-offset (standard) sites including Fox, and 4
    undetermined, excluded (385 buildings).
  - **Weather:** standard time at all 19 sites.
  - The verdicts are evidence-based, pinned, and re-checkable with
    `python -m wattwise.data.bdg2_audit` (D016, D020, [DATASETS.md](DATASETS.md)).

- **BDG2 metadata corrections (T009c, D020):**
  - **Fox's time zone:** corrected to `America/Phoenix`, because Arizona has no daylight saving
    time. The readings passed a zone check that rejected all 18 other sites when each was wrongly
    "corrected". This recovers 135 eligible meters.
  - **Wolf's longitude:** the sign is fixed.
  - **Regions:** each site's country and region is pinned, for holidays, prices and carbon
    later.

- **BDG2 preprocessing:** `python -m wattwise.data.bdg2_prepare` converts the download into
  canonical Parquet tables in git-ignored `data/processed/bdg2/`.
  - It also writes an exclusion log with a reason for every meter not used, a quality report and
    a manifest recording the metadata corrections.
  - The outputs are byte-identical across runs (D017).
  - The current run (pipeline version 2) used a seeded sample of 20 of 1,148 eligible meters
    from 9 sites: 350,816 readings, 95.65% coverage
    ([DATASETS.md](DATASETS.md#preparing-bdg2-for-analysis)).
- **Leakage-safe splits:** `wattwise.ml.splits` builds chronological and rolling-origin splits
  from explicit UTC windows, optionally holding out buildings or whole sites. Held-out buildings
  are tested only in the future window. Every split re-checks itself on the actual rows, raises
  `LeakageError` on any violation, and records a deterministic manifest (D018,
  [EVALUATION.md](EVALUATION.md)).
- **Evaluation harness (T011, D021):** `wattwise.ml.evaluation` scores any forecaster's
  predictions on a split.
  - **Metrics:** MAE, RMSE, bias, and WAPE only when total actual consumption is at least 1 kWh.
    They are reported per meter, per building, overall and as macro averages.
  - **Rules:** only evaluation roles are scored, predictions must cover exactly their rows, and
    missing predictions are counted.
  - **Reports:** JSON and Markdown, embedding the split manifest, a data fingerprint and the
    code version. The same inputs give byte-identical reports.
- **Supplementary data evaluated (T007b, D019):** every gap BDG2 leaves now has a recommended,
  source-verified option, or is stated as unfillable
  ([DATASETS.md](DATASETS.md#supplementary-data-evaluation-t007b)).
  - **Labels:** LEAD 1.0, human anomaly labels on 200 BDG2 meters in 2016, which join to our
    data exactly.
  - **Carbon factors:** eGRID2016, DESNZ, SEAI and the ECCC National Inventory Report.
  - **Prices:** EIA, DESNZ and CSO.
  - **Weather:** ERA5 solar radiation; humidity derived from BDG2.
  - **Calendar:** holidays and sun position.
  - **Other buildings:** Building 59 (sub-metered) and HKUST (independent).
  - **Metadata errors found in BDG2:** two "US/Eastern" sites are in Canada, and Fox and Wolf
    had the errors corrected in T009c.
  - **LEAD labels acquired and joined (T007c, D022):**
    - 1,438,672 usable hourly label rows on 173 BDG2 buildings in 2016, with 31,166 anomalies.
    - Of those anomalies, 16,848 have LEAD readings that match BDG2's raw data, so those labels
      are trusted.
    - Kept locally only, by owner decision.
  - **Weather enrichment acquired (T007d, D023):** ERA5 radiation and cloud cover for the 15
    located sites (Open-Meteo, `models=era5`), plus humidity derived from BDG2's observations
    for all 19 sites.
    - Both alignment checks passed at every site and in all 8 quarters. Solar-noon per-site
      medians were −8.6 to +2.0 minutes. The ERA5 temperature phase against BDG2's observed
      temperature was −0.50 to +0.30 h, stable across quarters.
  - **M2 data is complete.** Still to acquire later, when their tasks run: T021a (carbon and
    price tables), T040 (Building 59) and T041 (HKUST).

No model has been trained, so no ML metrics exist yet.

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
| T009b | BDG2 preprocessing pipeline | 2026-10-24 |
| T010 | Leakage-safe split utilities | 2026-10-24 |
| T007b | Supplementary dataset evaluation | 2026-10-24 |
| T009c | BDG2 site metadata corrections | 2026-10-24 |
| T011 | Evaluation harness and metrics | 2026-10-24 |
| T007c | LEAD 1.0 anomaly labels (local, joined to BDG2) | 2026-10-24 |
| T007d | Weather enrichment (ERA5 radiation, derived humidity) | 2026-10-24 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T012 — Seasonal and historical baselines**: establish the bar every ML model must beat. It
covers:
- Seasonal-naive (the same hour in the previous week).
- An hour-of-week median profile from the training window.
- Both evaluated on the BDG2 sample with the T011 harness, with results and the exact command in
  EVALUATION.md.

Tests must show the baselines use only past or training data. See
[ROADMAP.md](ROADMAP.md#t012--seasonal-and-historical-baselines).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 4 / 4 |
| M2 Data contracts and acquisition | T005–T007, T007b, T007c, T007d | 6 / 6 |
| M3 Validation and preprocessing | T008, T009a, T009b, T009c, T010 | 5 / 5 |
| M4 Baselines | T011–T012 | 1 / 2 |
| M5 Improved model | T013–T015, T041 | 0 / 4 |
| M6 Anomaly detection | T016–T018, T040 | 0 / 4 |
| M7 Explainability and uncertainty | T019–T020 | 0 / 2 |
| M8 Business impact | T021a, T021, T022 | 0 / 3 |
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
| 4 of 19 BDG2 sites (385 buildings, including Rat with 305) have an undetermined electricity clock and are excluded | T009b and later | Excluded rather than guessed (D016). Fox was a metadata error, corrected with a falsifiable check (D020). Per-building classification for mixed sites such as Rat is possible later |
| LEAD 1.0 has no licence on GitHub, and the Kaggle rules forbid redistribution | T018 | Owner decision (D022): local evaluation only, never committed or redistributed, cited. Data lives only in git-ignored folders (tested) |
| LEAD's readings differ from BDG2's at 46% of labelled anomalies | T018 | Trust a label only where the readings match (per-row flag); report the others separately (D022) |
| Supplementary sources differ by country and year; 4 BDG2 sites have no location | T021a, T007d | Per-site sourced tables; unlocated sites get "not configured", never a guess (D019) |
| BDG2 interval start/end cannot be determined from the data | T009b and later | Interval-start assumed explicitly: at most a 1-hour labelling uncertainty (D016). Recorded in every manifest |
| The default BDG2 sample is 20 meters from 9 sites, not stratified | T012 and later | Results are reported for the sampled sites only. `--sample-meters 0` uses all 1,148 eligible meters (D017) |
| BDG2 metadata may hold more errors like Fox's and Wolf's | Joins by location or time zone | Corrections are pinned with evidence and refuse changed data; a time-zone correction must pass the zone check (D020) |
| BDG2 "cleaned" data still has flatlines (12 of 20 sampled meters) and gaps | T012, T016 | Shown in the quality report; baselines and detectors must handle gaps and flag flatlines as data issues, not waste |
| Splits cannot stop features from looking ahead, or repeated use of the test window | T013, T014 | Feature leakage tests in T013; model selection on validation or rolling folds only (D018) |
| GitHub LFS bandwidth for future re-downloads | Re-fetching BDG2 | Verified local copies are never re-downloaded; HTTP 403/429 messages explain quota limits |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
| Pinned action SHAs, uv version and uv checksum do not update themselves | Security updates | Deliberate upgrades under the two-week rule. A uv upgrade changes three places together (D011) |
