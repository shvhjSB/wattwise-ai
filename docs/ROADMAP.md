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
| T014 | ML forecaster vs baselines | M5 | T012, T013 | Done |
| T015 | Model artifacts, metadata and registry | M5 | T014 | Done |
| T016 | Residual-based detector and event grouping | M6 | T012 | Done |
| T017 | Anomaly signature rules | M6 | T008, T016 | Done |
| T018 | Injected-anomaly benchmark | M6 | T016, T017 | Done |
| T018b | Detector check against LEAD human labels | M6 | T007c, T018 | Done |
| T019 | Prediction intervals | M7 | T010, T012 | Done |
| T019b | Season-adaptive model detector, re-benchmarked | M7 | T018, T019 | Done |
| T020 | Alert explanations | M7 | T017, T019 | Done |
| T021a | Sourced carbon-factor and price reference tables | M8 | T007b, T009c | Done |
| T021 | Excess energy, cost and carbon estimates | M8 | T019, T021a | Done |
| T022 | Alert prioritisation | M8 | T020, T021 | Done |
| T023 | Database foundation and readiness | M9 | T002, T004 | Done |
| T024 | Buildings, meters, series and summary APIs | M9 | T023, T006 | Done |
| T025 | Alerts and feedback API | M9 | T022, T023 | Done |
| T026 | CSV upload and analysis endpoint | M9 | T005, T015, T023 | Done |
| T027 | Model metadata, metrics and monitoring records | M9 | T015, T023 | Done |
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
| T042 | Full-scale data, memory-efficient features and quality masking | M5b | T009b, T013 | Done |
| T043 | Best model at full scale | M5b | T042, T014 | Done |
| T044a | Downstream pipeline at full scale: evaluation model, intervals, detection, explanations, impact | M5b | T043, T019b, T020, T021 | Done |
| T044b | Detector benchmark at full scale | M5b | T044a, T018 | Done |
| T044c | LEAD human-label check with a full-scale H1-2016 model | M5b | T044a, T018b | Done |

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

## M5b — Scale-up and model quality (owner request, 2026-10-25)

The owner asked to fix the issues found so far, to stop training on a small sample, and to get
the best model the data supports. Until now every result came from a seeded sample of 20
meters at 9 sites, under 2% of the 1,148 eligible meters (D017).

### T042 — Full-scale data, memory-efficient features and quality masking
- **Objective:** make every eligible meter usable for training and evaluation on this machine
  (15 GB RAM), and keep known data faults out of what models learn from.
- **Scope:**
  - Prepare all eligible cleaned meters (`--sample-meters 0`).
  - Build features in meter batches as float32, written to disk.
  - A quality mask for training targets and calibration: identical runs of 24 hours or
    more (which covers daily totals spread evenly), long zero runs and negative readings.
    Detection still sees every reading (D035).
  - Baselines at full scale.
- **Acceptance:**
  - Features for all eligible meters build within the memory budget, and match the in-memory
    features exactly on a sample (tested).
  - The masking rules are tested, and their share of rows is reported.
  - Full-scale baseline metrics are recorded.

### T043 — Best model at full scale
- **Objective:** the strongest model the data supports, chosen without touching the test window.
- **Scope:**
  - A model search on validation only: LightGBM with more trees and early stopping on a
    validation fold, L2, L1 and Huber losses, tree size, with and without history, and the
    T042 quality mask.
  - Seen-building, unseen-building and unseen-site evaluation at scale, with per-site and
    per-meter breakdowns.
  - A production refit on train plus validation, saved alongside the evaluated model.
- **Acceptance:**
  - Adopted only if it beats seasonal-naive on the same test rows, scored once.
  - Results labelled; the registry is updated.
- **Done (2026-10-27, D036):** LightGBM, L1 loss, 255 leaves, 1,779 trees. Adopted and
  promoted: test MAE 13.700 vs seasonal-naive 16.705 (+18.0%); the production refit scores
  13.660 (+18.2%). Beats seasonal-naive even on unseen sites (+8.5%), reversing T014's
  sample-scale finding. The old D026 sample-trained model loses to seasonal-naive at full scale
  (−4.4%) ([EVALUATION.md](EVALUATION.md#best-model-at-full-scale-t043-d036)).

### T044 — Downstream re-run at full scale (split into T044a, T044b, T044c)
- **Objective:** re-check every downstream result with the full-scale model.
- **Why split (2026-10-27):** at the start of the task, every downstream command failed with the
  T043 production refit promoted (its split has no validation window, and calibrating on a
  window it trained on would use in-sample residuals); the benchmark and the LEAD check rebuild
  features in memory, which does not fit at full scale; and the interval code was quadratic in
  meters. Each part is a task of its own.
- **Acceptance (all three):** defaults change only under the rules already fixed (D030, D032);
  every changed number is recorded with the command that produced it.

### T044a — Downstream pipeline at full scale
- **Scope:**
  - An evaluation model: the T043 chosen model (training window only), rebuilt
    deterministically, saved with its out-of-sample validation window and promoted only if it
    reproduces T043's recorded validation MAE.
  - Downstream inputs read from the T042 store for the model's windows (`--store`).
  - Interval code that scales with rows, not meters x days x rows; the D035 quality mask
    applied to calibration (intervals and the model detector).
  - Re-run at full scale: prediction intervals (coverage), detection (default and model
    detector), explanations and impact.
- **Acceptance:** the shared acceptance above; the linear interval code equals the original on
  test data; every command runs at full scale on this machine.
- **Done (2026-10-28, D039, D040, D041):** everything above runs at full scale in under 13
  minutes per step (intervals 12 min, peak 4.3 GB; TreeSHAP influences take hours). Three defects the sample could not show were found
  and fixed: the downstream tools could not run on the production refit (D039); meter problems
  were counted as potential excess, 42% of the first full-scale total (D040); and an outage left
  an "echo week" of near-zero levels that made 31 meters' intervals 5-2,190 times their mean
  reading (D041). Rolling stays the default interval method under D032's criteria; the alert
  load of both detectors matches the sample; the corrected potential excess is 558,722 kWh and
  220,140 kg CO2e
  ([EVALUATION.md](EVALUATION.md#downstream-pipeline-at-full-scale-t044a-d039-d040-d041)).

### T044b — Detector benchmark at full scale
- **Scope:** the T018 injected-anomaly benchmark (all detectors, the same pre-stated rule)
  against the full-scale evaluation model, with features recomputed only for the injected
  meters.
- **Done (2026-10-28, D042):** the same rule gives the same answer: neither model detector is
  kept; the rolling z-score (70.0% recall at 0.341 alerts per meter-week) stays the default.
  One finding reverses: the model's recall advantage on the sample is gone (62% against 70%).
  1,133 injections per phase, in about 40 minutes
  ([EVALUATION.md](EVALUATION.md#detector-benchmark-at-full-scale-t044b-d042)).

### T044c — LEAD check with a full-scale H1-2016 model
- **Scope:** the T018b check with a model trained at full scale on January–May 2016, scored on
  the trusted LEAD labels for July–December 2016.
- **Done (2026-10-28, D043):** the full-scale model beats seasonal-naive on the labelled meters
  (MAE 17.35 against 19.72) and finds more labelled segments than the rolling z-score (29.6%
  against 18.9%), but is less precise (event precision 9.3% against 22.7%). No default changes
  ([EVALUATION.md](EVALUATION.md#detector-check-against-lead-labels-at-full-scale-t044c-d043)).

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
  - Inject known anomalies into held-out real BDG2 series: spike, sustained, long sustained,
    overnight, drift, flatline and dropout. The synthetic fixture (8 weeks) is too short to
    train, calibrate and detect out-of-sample, so synthetic injections are covered by tests on
    the 100-day synthetic load.
  - Measure:
    - recall per pattern
    - detection latency
    - signature agreement
    - the alert rate outside injected windows (an upper bound on false alerts, since real data
      has unlabelled anomalies)
  - Compare against a rolling same-hour z-score baseline. Isolation Forest is optional and not
    done.
  - Tune detector thresholds on injections in the first third of the test window, and evaluate
    once on fresh injections in the rest.
- **Acceptance:**
  - The benchmark command is reproducible.
  - Results are labelled "synthetic benchmark" in `docs/EVALUATION.md`.
  - A model-based detector is kept only where it beats the simple baseline.

### T018b — Detector check against LEAD human labels
- **Objective:** score detection against human labels on real data.
- **Scope:**
  - LEAD's labels cover 2016, which is inside the adopted model's training period.
    Chronological evaluation therefore needs a model trained on the first half of 2016 and
    scored on the second half.
  - Use LEAD's meters, prepared from BDG2. Only labels whose readings match BDG2 are trusted
    (D022).
- **Acceptance:** results are reported separately as "real data, human labels without measured
  agreement", or "not run" with the reason.

## M7 — Explanation and uncertainty

### T019 — Prediction intervals
- **Objective:** uncertainty intervals that are tested, not assumed.
- **Scope:**
  - Split-conformal intervals from a calibration window, optionally stratified by meter or hour-of-day.
  - Empirical coverage measured on the test window.
  - Seasonal drift (D028, D030): the model's residual scale is too narrow in winter when
    calibrated in summer. Compare a static per-meter interval with one that scales with the
    meter's recent level (past-only), with coverage measured per month.
- **Acceptance:**
  - Coverage is reported from real runs.
  - The word "calibrated" is used only when coverage falls within a stated tolerance.
  - Tests use synthetic data with known noise.

### T019b — Season-adaptive model detector, re-benchmarked
- **Objective:** find out whether the model-based detector can become the alert source again.
- **Scope:** score model residuals with the season-adaptive scale chosen in T019, and re-run the
  T018 benchmark (same windows, seeds and budget).
- **Acceptance:** the model detector becomes the default again only if it beats the rolling
  z-score's recall within the alert budget, in tuning and in evaluation (D030 rule).

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
- **Done (2026-10-26, D037):** `wattwise.data.reference` and the committed
  `data/reference/*.csv` tables. US factors are average (total output); UK uses the publisher's
  own reporting year. **Ontario is deferred, not guessed:** a prior task's cited value could not
  be re-verified against its own source file this task, so it is not committed
  ([DATASETS.md](DATASETS.md#carbon-factors-and-electricity-prices-acquired-and-integrated-t021a)).

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
- **Done (2026-10-27, D038):** `wattwise.ml.impact`, wired into every T020 evidence bundle.
  Priced per event's own BDG2 site; cost summed only within one named geography at a time.
  The first sample-scale figures were superseded in T044a (D040: meter problems are not
  consumption); see
  [EVALUATION.md](EVALUATION.md#downstream-pipeline-at-full-scale-t044a-d039-d040-d041).

### T022 — Alert prioritisation
- **Objective:** rank alerts by likely business impact, not by anomaly score alone.
- **Scope:**
  - A documented score built from estimated impact, persistence, severity and confidence.
  - Deterministic tie-breaking.
- **Acceptance:**
  - Ordering tests on crafted alerts.
  - The formula is documented.
- **Done (2026-10-28, D044):** `wattwise.ml.prioritisation`: 100 x (0.4 impact + 0.2 persistence
  + 0.2 severity + 0.2 confidence), logarithmic, with the weights and caps as stated product
  assumptions. On the 5,546 full-scale alerts the top 200 hold 61.2% of the potential excess
  ([EVALUATION.md](EVALUATION.md#alert-prioritisation-t022-d044)).

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
- **Done (2026-10-28, D045):** `wattwise.db` (buildings and meters, baseline migration `0001`),
  `GET /api/v1/ready` (200 only when reachable and at the head revision; 503 names the reason
  without connection details), a schema-per-test strategy and a CI service container
  ([DATABASE.md](DATABASE.md)). The tests first ran against a PostgreSQL 18.6 container while the
  local service was stuck in recovery; after it was restarted, the local role and databases were
  created and the tests pass on the local server too.

### T024 — Buildings, meters, series and summary APIs
- **Scope:** `GET /buildings`, `/meters`, `/meters/{id}/series` (time range) and
  `/dashboard/summary`, with pagination and Pydantic schemas.
- **Acceptance:** API tests cover success, filters, validation errors and 404s.
- **Done (2026-10-28, D046):** the four endpoints plus `/buildings/{id}` and `/meters/{id}`;
  readings and labelled datasets in PostgreSQL (migration `0002`) and a contract-validated loader
  (`python -m wattwise.db.load`). Every response carries `data_kind`; timestamps are UTC (a bug
  found by running the server on a non-UTC machine, now tested).

### T025 — Alerts and feedback API
- **Scope:**
  - `GET /alerts` with pagination and filters: building, meter, signature, severity, review
    status and date.
  - `GET /alerts/{id}` with the evidence bundle.
  - `POST /alerts/{id}/feedback`, persisted with timestamps. The label set is decided here (see D001).
  - No automatic retraining.
- **Acceptance:** API tests, including rejection of invalid feedback.
- **Done (2026-10-29, D047):** the three endpoints; `alerts` and `alert_feedback` (migration
  `0003`); `python -m wattwise.db.alerts`, which scores bundles with T022 and keeps reviews across
  reloads. Labels: the spec's four, mapped onto the master instructions' three. Feedback is an
  append-only history; nothing is retrained from it.

### T026 — CSV upload and analysis endpoint
- **Scope:**
  - `POST /data/upload`: a strict size limit, T005 validation, safe filenames, no filesystem
    path access and a useful error report.
  - `POST /inference/analyze`.
- **Acceptance:**
  - Tests for oversize, malformed and valid uploads.
  - The analysis returns predictions and alerts.
- **Done (2026-10-29, D048):** both endpoints. Uploads are validated in memory and not stored
  (10 MB limit, 413; safe display names). The analysis uses the evaluation model for the
  expectation (settling D039 for now) and the default detector for alerts, and still answers
  without a model. On the synthetic sample the default detector finds 1 of 6 injected anomalies.

### T027 — Model metadata, metrics and monitoring records
- **Scope:**
  - `GET /models/metadata` and `/models/metrics`.
  - A record for every analysis run: model version, prediction timestamp and input data range.
- **Acceptance:**
  - API tests.
  - Missing models and metrics return explicit "unavailable" responses, not fabricated values.
- **Done (2026-10-29, D049):** `/models/metadata` and `/models/metrics` (recorded values only;
  `available: false` with a reason for a missing, tampered or incompatible model) and
  `analysis_runs` (migration `0004`) with `/analysis-runs`. Every analysis is recorded without
  storing its readings.

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
