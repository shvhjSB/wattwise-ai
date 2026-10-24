# WattWise AI — Roadmap

This roadmap breaks the product into small, independently testable tasks. Each task has an
objective, a limited scope, acceptance criteria, validation steps and dependencies.

**Status values**
- **Done**: acceptance criteria verified, committed and pushed.
- **In progress**: work has started.
- **Not started**: no work yet.
- **Blocked**: cannot proceed; the reason is recorded in [PROJECT_STATUS.md](PROJECT_STATUS.md).

A task is never marked Done just because its files exist. If a task proves too large, it is
split here *before* implementation, with new IDs appended (e.g. `T014a`, `T014b`).

Requirement sources: [specs/CLAUDE_CODE_PROMPT.md](specs/CLAUDE_CODE_PROMPT.md),
[specs/DATASET_CATALOG.md](specs/DATASET_CATALOG.md) and the owner's build instructions
(condensed in [../CLAUDE.md](../CLAUDE.md)). Precedence rules are in [DECISIONS.md](DECISIONS.md) (D001).

## Summary

| ID | Title | Milestone | Depends on | Status |
|---|---|---|---|---|
| T001 | Repository audit, project records and hygiene | M1 | — | Done |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | M1 | T001 | Done |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | M1 | T002 | Done |
| T004 | CI baseline (GitHub Actions) | M1 | T002, T003 | Done |
| T005 | Canonical data contracts and CSV upload format | M2 | T002 | Done |
| T006 | Deterministic synthetic fixture generator | M2 | T005 | Done |
| T007 | BDG2 acquisition tooling and dataset documentation | M2 | T005 | Done |
| T007b | Supplementary dataset evaluation | M2 | T007, T009b | Done |
| T007c | LEAD 1.0 anomaly labels (local, joined to BDG2) | M2 | T007b, T009c, owner decision | Done |
| T007d | Weather enrichment: ERA5 solar radiation, derived humidity | M2 | T007b, T009c, owner decision | Done |
| T008 | Data-quality engine and report | M3 | T005, T006 | Done |
| T009a | BDG2 timestamp-convention audit | M3 | T007 | Done |
| T009b | BDG2 preprocessing pipeline | M3 | T008, T009a | Done |
| T009c | BDG2 site metadata corrections (Fox time zone, Wolf longitude, site regions) | M3 | T009a, T007b | Done |
| T010 | Leakage-safe split utilities | M3 | T005, T006 | Done |
| T011 | Evaluation harness and metrics | M4 | T010 | Done |
| T012 | Seasonal and historical baselines | M4 | T009b, T011 | Done |
| T013 | Leakage-safe feature engineering | M5 | T009b, T010 | Done |
| T014 | ML forecaster vs baselines | M5 | T012, T013 | Not started |
| T015 | Model artifacts, metadata and registry | M5 | T014 | Not started |
| T016 | Residual-based detector and event grouping | M6 | T012 | Not started |
| T017 | Anomaly signature rules | M6 | T008, T016 | Not started |
| T018 | Injected-anomaly benchmark | M6 | T016, T017 | Not started |
| T019 | Prediction intervals | M7 | T010, T012 | Not started |
| T020 | Alert explanations | M7 | T017, T019 | Not started |
| T021a | Sourced carbon-factor and price reference tables | M8 | T007b, T009c | Not started |
| T021 | Excess energy, cost and carbon estimates | M8 | T019, T021a | Not started |
| T022 | Alert prioritisation | M8 | T020, T021 | Not started |
| T023 | Database foundation and readiness | M9 | T002, T004 | Not started |
| T024 | Buildings, meters, series and summary APIs | M9 | T023, T006 | Not started |
| T025 | Alerts and feedback API | M9 | T022, T023 | Not started |
| T026 | CSV upload and analysis endpoint | M9 | T005, T015, T023 | Not started |
| T027 | Model metadata, metrics and monitoring records | M9 | T015, T023 | Not started |
| T028 | Design system and application shell | M10 | T003 | Not started |
| T029 | Energy overview page | M10 | T024, T028 | Not started |
| T030 | Building and meter explorer | M10 | T024, T028 | Not started |
| T031 | Anomaly investigation queue and alert detail | M10 | T025, T030 | Not started |
| T032 | Cost-impact analysis and tariff configuration | M10 | T021, T024, T028 | Not started |
| T033 | Model evaluation lab, dataset and model information | M10 | T027, T028 | Not started |
| T034 | API integration and pipeline end-to-end tests | M11 | T026, T027 | Not started |
| T035 | Browser end-to-end tests for key flows | M11 | T031, T033 | Not started |
| T036 | Dockerfiles and Docker Compose | M12 | T023, T028 | Not started |
| T037 | Security hardening | M12 | T026 | Not started |
| T038 | Deployment recipe and guide | M12 | T036 | Not started |
| T039 | Final documentation | M12 | T034, T038 | Not started |
| T040 | Detector checks on a sub-metered building (LBNL Building 59) | M6 | T007b, T017 | Not started |
| T041 | Generalisation test on independent buildings (HKUST) | M5 | T007b, T014 | Not started |

---

## M1 — Repository audit and application foundation

### T001 — Repository audit, project records and hygiene
- **Objective:** a safe repository baseline, and the records used to plan and track work.
- **Scope:**
  - `.gitignore`, `.gitattributes`, `.editorconfig`
  - README, `CLAUDE.md`, CHANGELOG and the `docs/` records
  - move the spec files, unchanged, to `docs/specs/`
  - no application code
- **Acceptance:**
  - Ignore rules exclude secrets, datasets, model artifacts, local DBs, virtualenvs and `node_modules`.
  - `.env.example` and `data/sample/` remain committable.
  - No secrets are committed.
- **Validation:** `git check-ignore -v` on representative paths; diff review.

### T002 — Backend foundation
- **Objective:** a runnable, tested, typed FastAPI service skeleton that all backend work builds on.
- **Scope:**
  - `backend/pyproject.toml` (dependencies plus ruff/mypy/pytest configuration)
  - `wattwise` package (src layout)
  - environment-based settings (`WATTWISE_` prefix) and an app factory
  - `GET /api/v1/health` (liveness), tests, backend README, `.env.example`
  - no database, no ML
- **Acceptance:**
  - A fresh venv install works.
  - pytest passes; `ruff check` and `ruff format --check` are clean; `mypy --strict` is clean.
  - uvicorn serves `/api/v1/health` (200) and `/openapi.json`.
- **Validation:** `pytest`, `ruff check .`, `ruff format --check .`, `mypy src tests`, plus a uvicorn smoke test.

### T003 — Frontend foundation
- **Objective:** a runnable, tested React + TypeScript app shell that talks to the API through a typed client.
- **Scope:**
  - Vite + React + TypeScript + Tailwind CSS in `frontend/`
  - API base URL from the environment (`VITE_API_BASE_URL`)
  - a typed fetch client with explicit error handling
  - a minimal page showing API health with loading and error states
  - ESLint, `tsc`, Vitest and React Testing Library
  - the chart library is chosen in T030
- **Acceptance:**
  - `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` pass.
  - The health page renders against the running backend.
  - The error state renders when the API is unreachable (tested with a mocked fetch).
- **Validation:** the npm scripts above, plus a manual check against the local backend.

### T004 — CI baseline
- **Objective:** run backend and frontend checks automatically on every push and pull request.
- **Scope:**
  - `.github/workflows/ci.yml` with a backend job (Python 3.13: ruff, mypy, pytest)
  - a frontend job (Node LTS: `npm ci`, lint, typecheck, test, build)
  - dependency caching
  - a dependency lock strategy (D003 follow-up)
- **Acceptance:**
  - The workflow runs green on GitHub for the pushed commit.
  - A failing check fails the job.
- **Validation:**
  - `actionlint` on the workflow.
  - Both jobs replayed in Linux containers from the committed tree before pushing.
  - `gh run list` / `gh run view` for the pushed commit.
- **Known risk:** pushing workflow files needs a credential with the `workflow` scope. The
  `shvhjSB` `gh` token, which this repo pushes with (D006), currently lacks it. If the push is
  rejected, report it and give the owner the fix: `gh auth refresh -h github.com -s workflow`,
  run while `shvhjSB` is selected.

## M2 — Data contracts, schemas and dataset acquisition

### T005 — Canonical data contracts and CSV upload format
- **Objective:** one internal representation of meter readings, meters/buildings and weather,
  shared by every pipeline stage and the API.
- **Scope:**
  - Typed column contracts:
    - readings: timezone-aware UTC `timestamp`, `meter_id`, `building_id`, `meter_type`, `unit`, `value`
    - building metadata
    - site weather
  - A unit vocabulary: electricity in kWh; other meter types explicitly labelled.
  - Validators that return actionable errors.
  - `docs/DATA_CONTRACT.md`, documenting the CSV upload format with examples.
- **Acceptance:** valid frames pass. Frames with any of the following fail with clear messages,
  and each case has a test:
  - missing columns
  - naive timestamps
  - unknown units
  - non-numeric values
  - duplicate keys

### T006 — Deterministic synthetic fixture generator
- **Objective:** a small, reproducible, clearly synthetic dataset for tests, demo mode and
  injected-anomaly benchmarks.
- **Scope:**
  - A seeded generator covering a few buildings and meters, with daily/weekly seasonality,
    temperature dependence and documented injected anomalies whose labels are marked synthetic.
  - A tiny committed fixture under `data/sample/` with a README stating it is synthetic.
- **Acceptance:**
  - The same seed produces byte-identical output (hash test).
  - The fixture conforms to T005 and is under 1 MB.
  - Labels exist only for injected events.

### T007 — BDG2 acquisition tooling and dataset documentation
- **Objective:** make downloading BDG2 an explicit, verifiable, documented action, and resolve
  its licence terms.
- **Scope:**
  - Inspect the actual BDG2 repository layout and README.
  - `scripts/fetch_bdg2.py` downloads only the needed files (electricity readings, metadata,
    weather) to `data/raw/bdg2/` and records sizes and checksums.
  - `data/manifests/datasets.yaml`: source URL and ref, access date, citation, licence URL and
    status, checksums.
  - `docs/DATASETS.md`: attribution, plus the investigation of the licence discrepancy
    (CC BY 4.0 on the portal vs CC BY-SA 4.0 in the repo).
- **Acceptance:**
  - The script fetches the files and writes the manifest.
  - A re-run verifies checksums without re-downloading.
  - It fails clearly when offline, and never overwrites files silently.
  - Nothing under `data/raw/` is tracked.
  - Unit tests use mocked HTTP.

### T007b — Supplementary dataset evaluation
- **Objective:** BDG2 lacks data the product needs. For each gap, find the best available data
  from verified evidence, without inventing or guessing.
- **Gaps:**
  - real anomaly labels
  - carbon factors and electricity prices for the sites' countries, regions and years
  - solar radiation and the weather variables BDG2 lacks
  - holidays
  - sub-metered or occupancy data for cause hypotheses
  - independent commercial buildings for generalisation
- **Scope:**
  - For each candidate, verify at the primary source:
    - publisher, access and licence
    - period, resolution, geography and size
    - label or factor definitions
    - overlap with BDG2
  - Check the site geography the joins depend on, from the BDG2 metadata.
  - Inspect small samples where needed to confirm content, e.g. that labels join to BDG2 meters.
  - Recommend one source per gap, or "no adequate source", and plan acquisition and integration
    as follow-up roadmap tasks.
- **Acceptance:**
  - `docs/DATASETS.md` has a candidate table with the evidence and a recommendation per gap.
  - Every licence and number links to its source, and anything unverified is marked as such.
  - Gaps no source can fill are stated plainly.
  - The roadmap holds the follow-up tasks.

### T007c — LEAD 1.0 anomaly labels
- **Objective:** real human anomaly labels for BDG2 meters, kept local.
- **Precondition:** the owner accepts local-only use of the unlicensed data.
- **Scope:**
  - A pinned, checksum-verified download of `lead1.0-small.zip` to git-ignored `data/raw/lead/`.
  - Join the labels to BDG2 readings on `building_id_kaggle` and the local timestamp, then
    convert to UTC with each site's clock.
  - Use LEAD's labels only, never its readings.
  - A label table plus a report: buildings per site, label rate, and readings that disagree
    with BDG2.
- **Acceptance:**
  - Join coverage is measured on the full file.
  - Exclusions have reasons.
  - Tests run on a mini fixture.
  - No LEAD data is committed.

### T007d — Weather enrichment
- **Objective:** add the weather drivers BDG2 lacks.
- **Precondition:** the owner chooses the Copernicus CDS or Open-Meteo.
- **Scope:**
  - ERA5 hourly global, direct and diffuse radiation (and cloud cover) for the 15 sites with
    coordinates, 2016–2017, in UTC, labelled "modelled (reanalysis)".
  - Relative humidity derived from BDG2 temperature and dew point, labelled "derived".
  - Kept as separate columns. Nothing is gap-filled across sources.
- **Acceptance:**
  - Pinned requests or files, with provenance in a manifest.
  - Alignment is checked: radiation peaks near local solar noon.
  - Sites without coordinates get none.

## M3 — Data validation and preprocessing

### T008 — Data-quality engine and report
- **Objective:** detect data problems before training and report them transparently.
- **Scope:**
  - Checks: duplicate timestamps, gaps, missing values, negative or implausible values,
    flatlined meters and unit issues.
  - Per-meter and overall summaries.
  - A JSON and Markdown report with configurable, documented thresholds.
- **Acceptance:**
  - Each check is tested on crafted inputs, covering both true positives and true negatives.
  - A report is generated for the synthetic fixture.

### T009 — BDG2 preprocessing (split into T009a and T009b)

T009 was split before implementation. The first experiment showed that BDG2's timestamp
convention **differs by site**, which made the convention audit a substantial task of its own.

### T009a — BDG2 timestamp-convention audit
- **Objective:** determine, per BDG2 site, which clock the electricity and weather timestamps
  follow, using reproducible evidence, so that conversion to UTC is correct rather than assumed.
- **Scope:**
  - `wattwise.data.time_convention` (generic):
    - daylight-saving transitions from the time zone database
    - the profile-shift measurement
    - a margin-stable classifier for human and solar signals
    - `to_utc`, which drops non-existent and repeated wall-clock hours instead of guessing
  - `wattwise.data.bdg2_audit`: per-site evidence and verdicts, with the verdicts pinned and a
    CLI that re-checks the pins against the data.
  - A mini BDG2-format fixture builder for tests, also used by T009b.
- **Acceptance:**
  - Known conventions are recovered from synthetic series: standard and wall-clock in two time
    zones, and a solar signal. A flat 24/7 profile is "undetermined".
  - Borderline, mixed or conflicting evidence is "undetermined", never guessed.
  - The audit reproduces the pinned verdicts on the real data.
  - The per-site verdicts are documented, with a sync test.

### T009b — BDG2 preprocessing pipeline
- **Objective:** deterministically convert raw BDG2 files into the canonical format for a
  laptop-sized subset.
- **Scope:** a module CLI, `wattwise.data.bdg2_prepare`, which handles:
  - electricity meters only
  - `--sample-meters N` with a fixed seed
  - reshaping from wide to long
  - converting to UTC with the T009a pinned per-site clocks (`to_utc`), excluding
    undetermined sites and counting dropped non-existent and repeated hours
  - the interval-start assumption, documented
  - choosing raw vs cleaned electricity per purpose, with the reason recorded
  - joining weather by site, with weather converted using its own clock
  - an exclusion log with reasons (non-electric meters, undetermined clock, no data, ...)
  - a T008 data-quality report
  - Parquet output to `data/processed/`
  - provenance recorded in the manifest
- **Acceptance:**
  - Identical inputs and seed produce an identical output hash.
  - The pipeline runs on the mini BDG2-format test fixture.
  - On the real download it records row counts, date ranges and meter counts.
  - Non-electric meters and undetermined-clock sites are excluded with explicit reasons.

### T009c — BDG2 site metadata corrections
- **Objective:** fix the metadata errors found in T007b, with evidence, instead of excluding
  the data.
- **Scope:**
  - A pinned correction table, applied before the audit and preparation:
    - Fox → `America/Phoenix` (Arizona has no daylight saving time).
    - Wolf longitude → −6.2603.
    - Each site's country and region, from its coordinates. There are none for Bobcat, Eagle,
      Gator and Swan.
  - Re-run the T009a audit for Fox under the corrected zone, and update the pins only if the
    evidence agrees.
  - Re-run T009b.
- **Acceptance:**
  - Every correction cites its evidence.
  - The audit result for Fox is reported whatever it is.
  - DATASETS.md and the pins stay in sync, with tests.

### T010 — Leakage-safe split utilities
- **Objective:** make temporal leakage structurally hard.
- **Scope:**
  - A chronological train/validation/test split.
  - Rolling-origin (expanding window) folds.
  - A building-level holdout for unseen-building generalisation.
  - A split manifest saved with every evaluation.
- **Acceptance:** tests assert that:
  - in every fold, the latest training timestamp is earlier than the earliest test timestamp
  - holdout buildings never appear in training
  - splits are deterministic from their config

## M4 — Baseline forecasting and evaluation

### T011 — Evaluation harness and metrics
- **Objective:** one trusted way to score any forecaster.
- **Scope:**
  - MAE and RMSE.
  - WAPE, reported only when its denominator (total actual consumption) is meaningfully positive.
  - Per-meter and per-building results, plus macro averages.
  - A JSON and Markdown report that includes the split manifest, the data fingerprint and the
    code version.
- **Acceptance:**
  - Metrics are tested against hand-computed values.
  - The WAPE guard is tested.
  - Reports are reproducible.

### T012 — Seasonal and historical baselines
- **Objective:** establish the bar every ML model must beat.
- **Scope:**
  - Two baselines: seasonal-naive (same hour, previous week) and an hour-of-week median
    profile from the training window.
  - Both are evaluated on the BDG2 sample with T011.
  - Results go in `docs/EVALUATION.md`, together with the exact command used.
- **Acceptance:**
  - Metrics come from a real run, or are reported as "not run" with the reason.
  - Tests show the baselines use only past/training data.

## M5 — Improved forecasting model

### T013 — Leakage-safe feature engineering
- **Objective:** time-aware features that never use future information.
- **Scope:**
  - Calendar features: hour, day of week, month/season.
  - Holidays, only where the site country is known: the `holidays` package (MIT), using the
    T009c site regions.
  - BDG2 site weather, plus the T007d radiation and derived humidity where available.
  - Sun elevation and daylight, computed with NOAA's equations and checked against pvlib (D025).
  - Lags of at least the forecast horizon, and rolling statistics shifted to exclude the current target.
  - A versioned feature list.
- **Acceptance:**
  - Leakage tests: changing future targets does not change past features.
  - Missing weather is handled explicitly.
  - Feature generation is deterministic.

### T014 — ML forecaster vs baselines
- **Objective:** adopt a stronger model only if it measurably beats the baselines.
- **Scope:**
  - Candidates: ridge regression, HistGradientBoosting and LightGBM (if installable), all on T013 features.
  - Evaluation on both a future period and unseen buildings, with fixed seeds.
  - A comparison table.
  - Imputation and scaling fitted on training rows only. Report the feature groups used, with
    and without the `history` group (D025).
- **Acceptance:**
  - The comparison comes from real runs.
  - The decision is recorded in DECISIONS.md.
  - If no ML model beats the baseline, the baseline stays the default.

### T015 — Model artifacts, metadata and registry
- **Objective:** versioned, reproducible model artifacts the API can load safely.
- **Scope:**
  - `artifacts/models/<version>/` holds the model plus metadata: training period, dataset
    fingerprint, code version, config, features, metrics and `created_at`.
  - Atomic promotion of a new model.
  - Graceful handling when no model exists.
  - Train and evaluate CLIs.
- **Acceptance:**
  - Tests for save/load round-trip, atomic replacement and missing-model handling.
  - Artifacts are git-ignored.

## M6 — Anomaly detection and test scenarios

### T016 — Residual-based detector and event grouping
- **Objective:** turn observed-minus-expected residuals into stable anomaly events.
- **Scope:**
  - Residuals normalised by a robust scale (MAD) or by interval width.
  - Thresholds with persistence and hysteresis.
  - Event grouping that records start, end, peak, magnitude and duration.
- **Acceptance:** tests cover threshold crossing, hysteresis and the merging of adjacent windows.
  One long event yields one alert.

### T017 — Anomaly signature rules
- **Objective:** classify events into transparent, explainable patterns.
- **Scope:**
  - Signatures: spike, sustained elevated usage, overnight/base-load excess, gradual drift,
    flatlined/stuck meter and data-quality fault.
  - Configurable, documented thresholds.
- **Acceptance:** each rule is tested on crafted series, with positive and negative cases.

### T018 — Injected-anomaly benchmark
- **Objective:** measure detection quality honestly, without inventing labels for real data.
- **Scope:**
  - Inject known anomalies into held-out real BDG2 series and into the synthetic fixture.
  - Measure:
    - recall per pattern
    - detection latency
    - false-alert rate on uninjected windows
  - Compare against a rolling z-score baseline and, optionally, Isolation Forest.
  - If T007c is done, also score against LEAD's human labels (BDG2 meters, 2016). These results
    are reported separately as "real data, human labels without measured agreement".
- **Acceptance:**
  - The benchmark command is reproducible.
  - Results are labelled "synthetic benchmark" or "LEAD labels" in `docs/EVALUATION.md`.
  - A model-based detector is kept only where it beats the simple baseline.

## M7 — Explanation and uncertainty

### T019 — Prediction intervals
- **Objective:** uncertainty intervals that are tested, not assumed.
- **Scope:**
  - Split-conformal intervals from a calibration window, optionally stratified by meter or hour-of-day.
  - Empirical coverage measured on the test window.
- **Acceptance:**
  - Coverage is reported from real runs.
  - The word "calibrated" is used only when coverage falls within a stated tolerance.
  - Tests use synthetic data with known noise.

### T020 — Alert explanations
- **Objective:** every alert carries the evidence an operator needs.
- **Scope:**
  - An evidence bundle: actual, expected, interval, residual, persistence, time range,
    signature and top contributing features.
  - SHAP for tree models, as an optional dependency with a safe fallback.
  - Wording templates that phrase causes as hypotheses.
- **Acceptance:**
  - Every alert has an explanation.
  - Inference works when SHAP is absent.
  - Tests guard against causal wording.

## M8 — Cost and potential-impact calculations

### T021a — Sourced carbon-factor and price reference tables
- **Objective:** real, cited factors and prices for the BDG2 sites, so estimates need no
  invented numbers.
- **Scope:** versioned reference tables, each value with its source, URL, year, unit and
  geography, from the sources chosen in T007b:
  - **Carbon:**
    - US: eGRID2016, with subregions from a point-in-polygon lookup on the 2016 shapefiles.
    - UK: DESNZ conversion factors 2016/2017.
    - Ireland: SEAI.
    - Ontario: the ECCC National Inventory Report.
  - **Prices:**
    - US: EIA-861 state commercial averages.
    - UK: DESNZ Quarterly Energy Prices.
    - Ireland: CSO TMEGB04.
    - Ontario: none.
  - Decide and record (D-entry) whether US factors are average or non-baseload, and which UK
    factor-year convention applies.
- **Acceptance:**
  - Values are checked against the source files by a test or a recorded checksum.
  - Sites without location, or without a source, return "not configured".

### T021 — Excess energy, cost and carbon estimates
- **Objective:** transparent impact estimates with explicit assumptions.
- **Scope:**
  - `potential_excess_kwh`, counted only above the upper interval bound.
  - Tariff configuration: a currency code and a rate per kWh. With no tariff, show kWh only.
  - A carbon factor with source, year and geography. With no factor, show "not configured".
  - "Potential" vs "verified" labelling.
- **Acceptance:** unit tests cover:
  - the excess maths (negative residuals never count)
  - a missing tariff
  - a missing carbon factor
  - currency handling

### T022 — Alert prioritisation
- **Objective:** rank alerts by likely business impact, not by anomaly score alone.
- **Scope:**
  - A documented score built from estimated impact, persistence, severity and confidence.
  - Deterministic tie-breaking.
- **Acceptance:**
  - Ordering tests on crafted alerts.
  - The formula is documented.

## M9 — FastAPI integration and persistence

### T023 — Database foundation and readiness
- **Objective:** persistent storage with migrations, and a truthful readiness check.
- **Scope:**
  - SQLAlchemy models, an Alembic baseline migration and a PostgreSQL URL from the environment.
  - `GET /api/v1/ready`, which checks the database.
  - A test-database strategy, decided in this task.
- **Acceptance:**
  - Migrations upgrade and downgrade cleanly.
  - `/ready` returns 503 without a database and 200 with one.
- **Environment:** PostgreSQL 18 is installed locally (D007) and Docker Desktop is available.
  CI also uses a PostgreSQL 18 service container.

### T024 — Buildings, meters, series and summary APIs
- **Scope:** `GET /buildings`, `/meters`, `/meters/{id}/series` (time range) and
  `/dashboard/summary`, with pagination and Pydantic schemas.
- **Acceptance:** API tests cover success, filters, validation errors and 404s.

### T025 — Alerts and feedback API
- **Scope:**
  - `GET /alerts` with pagination and filters: building, meter, signature, severity, review
    status and date.
  - `GET /alerts/{id}` with the evidence bundle.
  - `POST /alerts/{id}/feedback`, persisted with timestamps. The label set is decided here (see D001).
  - No automatic retraining.
- **Acceptance:** API tests, including rejection of invalid feedback.

### T026 — CSV upload and analysis endpoint
- **Scope:**
  - `POST /data/upload`: a strict size limit, T005 validation, safe filenames, no filesystem
    path access and a useful error report.
  - `POST /inference/analyze`.
- **Acceptance:**
  - Tests for oversize, malformed and valid uploads.
  - The analysis returns predictions and alerts.

### T027 — Model metadata, metrics and monitoring records
- **Scope:**
  - `GET /models/metadata` and `/models/metrics`.
  - A record for every analysis run: model version, prediction timestamp and input data range.
- **Acceptance:**
  - API tests.
  - Missing models and metrics return explicit "unavailable" responses, not fabricated values.

## M10 — React investigation and analytics workflows

**Shared acceptance for T028–T033:**
- Vitest/RTL tests cover the loading, empty, error and populated states.
- Lint, typecheck and build pass.
- Keyboard navigation, labels and contrast meet WCAG AA.
- Every number comes from the API or is visibly labelled demo data.

### T028 — Design system and application shell
- **Scope:**
  - Design tokens, typography, light and dark themes, layout and navigation.
  - A demo-data banner and a provenance badge.
  - Shared loading, empty and error components.

### T029 — Energy overview page
- **Scope:**
  - KPIs: measured kWh, model-expected kWh, estimated excess kWh, active events, data-quality
    health and coverage.
  - Every KPI has a tooltip with its definition and source.

### T030 — Building and meter explorer
- **Scope:**
  - Building and meter navigation.
  - An expected-vs-observed chart with the interval band and residual view.
  - The chart-library decision is recorded in DECISIONS.md.

### T031 — Anomaly investigation queue and alert detail
- **Scope:**
  - A queue ordered by priority, with filters.
  - An alert detail view with the evidence and explanation panel, assumptions, suggested checks
    and feedback buttons.

### T032 — Cost-impact analysis and tariff configuration
- **Scope:**
  - Tariff and carbon-factor configuration.
  - The impact view shows estimates with their assumptions.
  - With no tariff or factor configured, it shows "not configured" rather than invented values.

### T033 — Model evaluation lab, dataset and model information
- **Scope:**
  - Baseline comparisons, evaluation windows, per-building metrics and training metadata.
  - A dataset health page and recent uploads.
  - Clear warnings when metrics are unavailable.

## M11 — Integration and end-to-end testing

### T034 — API integration and pipeline end-to-end tests
- **Scope:**
  - PostgreSQL-backed API tests in CI.
  - A pipeline test: fixture → prepare → train → detect → persist → API.
- **Acceptance:** the pipeline test passes in CI from a clean database.

### T035 — Browser end-to-end tests for key flows
- **Scope:** browser automation for overview → alert → feedback, plus model-lab rendering.
  Added only if UI complexity justifies it. The decision is recorded in DECISIONS.md.

## M12 — Docker, CI, deployment, security and documentation

### T036 — Dockerfiles and Docker Compose
- **Scope:**
  - API and frontend images, with the frontend served by Nginx.
  - Compose with PostgreSQL (health check, named volume) and migrations on start.
  - `docker compose up --build` runs the synthetic demo.
- **Environment:** Docker Desktop is installed locally. Image builds are verified both locally and in CI.

### T037 — Security hardening
- **Scope:**
  - A CORS allow-list from the environment.
  - Request size and time limits, and safe exception handlers.
  - Structured logging.
  - `pip-audit` and `npm audit` in CI, plus secret scanning.

### T038 — Deployment recipe and guide
- **Scope:**
  - A Render blueprint or equivalent, with notes on persistent storage.
  - Health checks, plus rollback and model-version notes.
  - `docs/DEPLOYMENT.md`.
  - The app is never described as deployed unless it actually is.

### T039 — Final documentation
- **Scope:**
  - The README: Mermaid architecture diagram, features, quickstart, ML methodology and limitations.
  - `docs/ARCHITECTURE.md` and `docs/MODEL_CARD.md`.
  - A finalised `docs/DATASETS.md` and `LICENSES.md`.

## Added after T007b (supplementary data)

### T040 — Detector checks on a sub-metered building
- **Objective:** test whether the whole-building detector reacts to known kinds of event, using
  data with end uses, HVAC points and occupancy.
- **Scope:**
  - Download LBNL Building 59 (CC0, Dryad 10.7941/D1N33Q, 263 MB), pinned and git-ignored.
  - Mask the spans its authors imputed.
  - Run the baseline and detector on the whole-building series. Compare the alerts with the
    end-use, HVAC and occupancy data and with the dated events (wildfire damper closures,
    COVID shelter-in-place).
- **Acceptance:**
  - Results are reported as one building's case study.
  - Nothing is claimed about causes in BDG2 buildings.

### T041 — Generalisation test on independent buildings
- **Objective:** measure how the chosen forecaster performs outside BDG2's population and years.
- **Scope:** evaluate on the HKUST campus smart-meter database (CC0, Dryad
  10.5061/dryad.k3j9kd5h6, 2022–2024), pinned and git-ignored, with the T011 harness and the
  T010 splits. It is reported separately from the BDG2 results.
- **Acceptance:**
  - Real-run metrics, or "not run" with the reason.
  - Coverage and missing data are reported per meter.
