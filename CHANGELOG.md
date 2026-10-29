# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/) once it has a first release.

## [Unreleased]

### Added
- Repository hygiene: `.gitignore` (secrets, datasets, model artifacts, local databases),
  `.gitattributes` (LF normalisation), `.editorconfig`. (T001)
- Project records: roadmap, project status, decisions log, work log, this changelog. (T001)
- `CLAUDE.md` working agreement for Claude Code sessions. (T001)
- Product and dataset specifications moved, unchanged, to `docs/specs/`. (T001)
- Backend foundation: `wattwise` Python package with environment-based settings, a FastAPI app
  factory, and a `GET /api/v1/health` liveness endpoint with OpenAPI docs. (T002)
- Backend tooling: pytest (10 tests), ruff lint and format, strict mypy. (T002)
- `.env.example` documenting `WATTWISE_ENVIRONMENT`. (T002)
- Frontend foundation: React 19 + TypeScript + Vite 8 + Tailwind CSS 4 app shell, with a
  page showing the live API connection status (loading, online and error-with-retry
  states). (T003)
- Typed API client that validates every response at runtime and reports network, HTTP and
  invalid-response errors. The dev server proxies `/api` to the backend. (T003)
- Frontend tooling: Vitest + React Testing Library (21 tests), ESLint (typescript-eslint strict,
  React hooks, jsx-a11y), Prettier and a locked `package-lock.json`. (T003)
- Continuous integration baseline: GitHub Actions workflow (`.github/workflows/ci.yml`) running
  all backend checks (ruff, mypy, pytest) and frontend checks (Prettier, ESLint, tsc, Vitest,
  Vite build) on Ubuntu 24.04 runners. It uses SHA-pinned actions, a checksum-verified uv
  download and lockfile-keyed dependency caching. (T004)
- Backend dependency locking: multi-platform lockfile `backend/uv.lock`, PEP 735
  `[dependency-groups]`, a pinned uv version range and a pinned build backend
  (`build-constraint-dependencies`) in `backend/pyproject.toml` (D010). (T004)
- Version environment files: `backend/.python-version` (3.13) and `frontend/.nvmrc` (24). (T004)
- Data contract v1.0 (`wattwise.data`): canonical `readings`, `buildings` and `weather`
  tables, a meter-type and unit vocabulary with one canonical unit per meter type, a
  validator with 21 stable issue codes and actionable messages, conversion to canonical form,
  and a CSV reader for the documented upload format. (T005)
- `docs/DATA_CONTRACT.md`: the specification, CSV upload format and issue-code reference. A
  test keeps it in sync with the code and checks that its examples behave as documented. (T005)
- Backend dependencies: pandas 3.0, numpy, tzdata; `pandas-stubs` for strict typing. (T005)
- Synthetic data generator (`python -m wattwise.data.synthetic`). It is deterministic per seed,
  generates load in local time with heating and weekend effects, and injects six labelled
  anomalies (spike, sustained excess, overnight base load, gradual drift, flatline, missing
  data). (T006)
- Committed synthetic sample in `data/sample/synthetic/` (about 564 KB) with a generated README
  and a hash manifest; every table passes the data contract. (T006)
- Verified dataset acquisition (`wattwise.data.acquisition`). It streams to `.part`, enforces
  the expected size, checks SHA-256 and renames atomically. It never re-downloads verified files,
  never overwrites mismatching files without `--force`, and gives clear messages for offline,
  quota and LFS-pointer cases. (T007)
- BDG2 source definition and CLI (`python -m wattwise.data.bdg2 list|fetch|verify`), pinned to
  commit `753598e0` with checksums from the Git LFS pointers. It writes a provenance manifest,
  `data/manifests/bdg2.json`. (T007)
- Data-quality engine (`wattwise.data.quality`, `python -m wattwise.data.quality`). It runs after
  the contract and reports nine checks without rejecting data: gaps, irregular intervals,
  missing values, low coverage, negatives, zero runs, flatlines, extreme values (5× the 99th
  percentile) and implausible intensity. Thresholds are configurable, and the JSON and Markdown
  reports are deterministic. (T008)
- `docs/DATA_QUALITY.md` and an example report for the synthetic sample
  (`docs/reports/synthetic-data-quality.md`), kept up to date by a test. (T008)
- Timestamp-convention analysis (`wattwise.data.time_convention`): daylight-saving transitions
  from the time zone database, profile-shift evidence for human and solar signals, a
  classifier that must hold at every margin, and `to_utc`. `to_utc` drops non-existent and
  repeated wall-clock hours instead of guessing. (T009a)
- BDG2 timestamp audit (`python -m wattwise.data.bdg2_audit`), with per-site verdicts pinned
  and re-checkable against the data: 11 wall-clock, 3 standard and 5 undetermined sites for
  electricity, and standard time for weather (D016). (T009a)
- BDG2 preprocessing pipeline (`python -m wattwise.data.bdg2_prepare`). It does the following:
  - verifies the inputs against the pinned checksums
  - keeps electricity only and converts each site to UTC with its pinned clock, dropping and
    counting unconvertible hours
  - logs every excluded meter with a reason
  - draws a seeded sample
  - writes canonical Parquet tables, a quality report and a manifest whose outputs are
    byte-identical across runs (D017)
  Outputs stay in git-ignored `data/processed/`. (T009b)
- Backend dependency: pyarrow 26 for Parquet. (T009b)
- Leakage-safe evaluation splits (`wattwise.ml.splits`):
  - Chronological train/validation/test splits and rolling-origin folds with expanding
    windows, from explicit UTC windows with an optional gap.
  - A building or site holdout; held-out buildings are tested only in the future window, as
    `test_unseen`.
  - A reading counts only if its whole interval fits its window.
  - Every split re-checks itself on the rows (`LeakageError`) and writes a deterministic
    manifest that can re-create it (D018). (T010)
- `docs/EVALUATION.md`: the evaluation method, starting with splits. No metrics yet. (T010)
- Supplementary dataset evaluation in `docs/DATASETS.md`. For each gap BDG2 leaves, it records
  a verified, cited recommendation, or that no source can fill it (D019). (T007b) The gaps:
  - anomaly labels
  - carbon factors and prices
  - solar radiation, holidays and daylight
  - sub-metered and independent buildings
- A site-geography table from the BDG2 coordinates. It records three metadata problems: two
  "US/Eastern" sites are in Canada, Wolf's longitude sign is flipped, and Fox is probably on
  Arizona time. (T007b)
- Roadmap tasks T007c, T007d, T009c, T021a, T040 and T041 to acquire and use the recommended
  data. (T007b)
- BDG2 metadata corrections (`wattwise.data.bdg2_sites`). Each correction is pinned with its
  evidence and refuses changed source data (D020). (T009c)
  - Fox's time zone: `US/Mountain` → `America/Phoenix`.
  - Wolf's longitude sign.
  - Each site's ISO country and region.
- A zone check in the timestamp audit, which a time-zone correction must pass against the
  readings. It allows no occupant shift and no daylight-saving fingerprint (empty, displaced,
  copied or merged clock-change hours). It rejected all 18 other sites in a falsification test.
  (T009c)
- `time_convention.repeated_hours` for the autumn hours that occur twice. (T009c)
- Evaluation harness (`wattwise.ml.evaluation`), D021. (T011)
  - Metrics: MAE, RMSE, bias, and WAPE when total actual consumption is at least
    `wape_min_total` (1 kWh).
  - Results per meter, per building, overall and as macro averages, plus a summary across folds.
  - Only evaluation roles are scored, predictions must cover exactly their rows, and missing
    predictions are counted.
  - JSON and Markdown reports embed the split manifest, a content fingerprint of the readings
    and the code version, and are byte-identical for the same inputs.
- The test helpers for canonical readings moved to `tests/ml/conftest.py`. (T011)
- LEAD 1.0 anomaly labels (`python -m wattwise.data.lead fetch|verify|prepare`), local use only
  by owner decision. (T007c)
  - A pinned download, verified by SHA-256 and GitHub's git hash. Provenance is in
    `data/manifests/lead.json`.
  - The labels join to BDG2 meters in UTC through the audited site clocks. Every excluded row
    has one reason, and a per-row flag records whether LEAD's reading equals BDG2's.
  - Outputs: a label table, an exclusion log, a report and a manifest. They are deterministic
    and git-ignored (D022).
- The BDG2 test fixture's metadata now carries `building_id_kaggle`. (T007c)
- Weather enrichment (`python -m wattwise.data.era5 fetch|verify|prepare`), D023. (T007d)
  - **Sources:** ERA5 radiation (global, direct, diffuse, direct-normal) and cloud cover from
    the Open-Meteo archive (`models=era5`, UTC) for the 15 located BDG2 sites, plus relative
    humidity derived from BDG2's observed temperature and dew point (Magnus formula) for all 19.
  - **Provenance:** in the column names (`_era5`, `_derived`). Nothing is gap-filled across
    sources.
  - **Time convention:** radiation is relabelled to interval starts. Two checks run over the
    whole period and in every calendar quarter, and `prepare` writes nothing unless every site
    passes:
    - the radiation's solar-noon centre, within 30 min
    - the ERA5 temperature phase, stable within 0.5 h across quarters and within 0.75 h of
      zero
  - **Manifest:** a git-ignored manifest (`data/raw/era5/manifest.json`) records each request,
    its file and content hashes, and the grid cell. It is saved after every site, and a
    response recorded for another request is refused.
- `bdg2_prepare.site_weather` is public, so the enrichment reuses the observed-weather
  conversion. (T007d)
- Baselines (`python -m wattwise.ml.baselines --data ...`), D024. (T012)
  - `seasonal-naive-1w` (the reading one week earlier) and `hour-of-week-median` (training
    rows only, in local wall time).
  - Both are scored with the T011 harness, overall and on the rows both predict.
  - First results on the BDG2 sample's test quarter: MAE 8.76 kWh and WAPE 8.6% (seasonal)
    against 10.89 kWh and 10.7% (profile). Details in `docs/EVALUATION.md`.
- Leakage-safe features (`python -m wattwise.ml.features --data ...`), feature set 1, D025.
  (T013)
  - **Groups:** 32 float features in calendar (local time), holiday (`holidays` 0.106, known
    regions only), weather (observed BDG2, derived humidity, ERA5), sun and consumption
    history.
  - **Leakage:** conditions never describe a later interval. History uses only readings at
    least the horizon (1–168 h, default 168) before the target. Tests prove both, including
    the exact first hour a change can reach.
  - **Missing data:** NaN with availability flags; nothing is fitted or filled.
  - **Outputs:** `features.parquet` and a manifest (version, rules, provenance, hashes,
    missing shares), byte-identical across runs.
  - `docs/FEATURES.md` lists every feature, and a test keeps it in sync.
- `wattwise.data.solar`: NOAA sun position (elevation, declination, day length), cross-checked
  against pvlib's NREL SPA. (T013)
- ML models and their comparison with the baselines (`python -m wattwise.ml.models --data
  ...`), D026. (T014)
  - **Candidates:** ridge, HistGradientBoosting and LightGBM, each with all features
    (target scaled by the meter's recent week) or without consumption history (scaled by the
    training mean, with a training weekly profile).
  - **Procedure:** everything is fitted on training rows; settings and the winner are chosen
    on validation; test is scored once; building and site holdouts test unseen buildings.
  - **Result on the BDG2 sample:** LightGBM with all features is adopted for seen buildings:
    test MAE 7.49 kWh against 8.76 for seasonal-naive (−14.6% on common rows). It is not
    adopted for unseen buildings (a tie, and a site-holdout loss). No-history models lose to
    seasonal-naive.
  - **Outputs:** `comparison.json` and `comparison.md`, plus T011 reports per model, in
    git-ignored `data/processed/evaluation/models/`.
- New runtime dependencies scikit-learn 1.9.1 and LightGBM 4.7.0, with scipy 1.18.1, joblib,
  threadpoolctl, narwhals and cloudpickle; every new lock entry is at least two weeks old.
  (T014)
- Model registry (`python -m wattwise.ml.registry train|evaluate|list|promote`), D027. (T015)
  - **Artifacts:** versioned folders in git-ignored `artifacts/models/`, holding LightGBM's text
    model, a JSON state file and metadata. The metadata covers model, settings, features, data
    fingerprint, training period, split, code and library versions, metrics, `created_at` and
    file hashes.
  - **Safety:** never pickled. Files are hash-checked before parsing; incompatible versions and
    unsafe names are refused.
  - **Atomic:** a staging folder is renamed into place, and `CURRENT` is replaced by an atomic
    rename after verification. Old versions stay for rollback, and a missing model gives
    `NoModelError`.
  - **Reproducible:** `evaluate` re-scores an artifact on its recorded split and must reproduce
    its recorded metrics exactly; it did for the promoted D026 model.
  - `docs/MODELS.md` documents the layout, metadata and commands.
- Residual-based anomaly detection (`python -m wattwise.ml.detection --data ...`), D028.
  (T016)
  - **Scores:** robust z-scores per meter (median and MAD from the promoted model's validation
    quarter, with a scale floor). Detection runs only on later rows.
  - **Events:** high and low, with hysteresis (open at 4, continue at 2), gap bridging, and
    persistence or a spike to keep an event. Each records start, end, duration, flagged,
    missing and reference hours, peak, residual sum and whether it is ongoing.
  - **Long events:** after a week, scored against the meter's own pre-event week, so a sustained
    anomaly the model absorbs stays one event.
  - **Outputs:** `events.csv`, `scores.parquet`, `summary.json` and `report.md` in git-ignored
    `data/processed/detection/`. `docs/DETECTION.md` documents the method and the first results:
    355 events on the BDG2 sample's test quarter, with untuned thresholds and a stated
    calibration issue.
- Anomaly signature rules (`wattwise.ml.signatures`), run by the detection command, D029.
  (T017)
  - **Rules:** `data_fault`, `flatline`, `spike`, `overnight_excess`, `drift`, `sustained`,
    else `unclassified`.
  - **Precedence:** meter problems first. All matches and every rule's measurements are kept as
    JSON evidence in `events.csv`.
  - **Thresholds:** configurable; flatline and zero-run lengths are shared with the T008
    quality engine.
  - **Real result:** 16 of 355 events are meter problems. Gator's whole-day lows are daily
    totals spread over 24 hours in the raw data.
- The detector also returns every event hour (reading, baseline used, score), so rules run on
  exactly what it saw. (T017)
- Injected-anomaly benchmark (`python -m wattwise.ml.benchmark --data ...`), D030. (T018)
  - **Patterns:** seven (spike, sustained, long sustained, overnight, drift, flatline, dropout)
    injected into real BDG2 readings, one per meter per replicate, with the features rebuilt.
  - **Procedure:** tuning on October 2017 (240 injections), evaluation once on Nov–Dec (240).
  - **Measures:** recall, latency, coverage and signature agreement per pattern, and alerts
    outside injections (an upper bound on false alerts).
  - **Detectors:** the model detector against a rolling same-hour z-score baseline, with the
    same event rules.
  - **Labelling:** reported as a synthetic benchmark in `docs/EVALUATION.md`.
- A rolling same-hour z-score detector (`detection.rolling_same_hour`), and `--detector
  rolling-z|model` for the detection command. (T018)
- Detector check against LEAD 1.0 human labels (`python -m wattwise.ml.lead_check`), D031.
  (T018b)
  - **Setup:** raw BDG2 readings for LEAD's 173 meters; a model trained Jan–May 2016 and
    calibrated in June; detection Jul–Dec 2016.
  - **Scoring:** trusted labels only, at the hour, segment and event level, against the chance
    rate.
  - **Result:** reported as "real data, human labels without measured agreement". The rolling
    z-score has hour precision 11.5% against 1.5% chance, segment recall 18.9% and event
    precision 22.7%. The outputs are local and git-ignored.
- Split-conformal prediction intervals with measured coverage (`python -m wattwise.ml.intervals`),
  D032. (T019)
  - **Methods:** absolute, relative (scaled by the meter's recent level) and rolling (relative,
    recalibrated daily from the 28 days ending 7 days before). Finite-sample conformal
    quantiles come from windows the model did not train on.
  - **Coverage:** measured overall, per month and per meter, with width and the interval score.
    "Calibrated" only within ±2 points overall and per month.
  - **Result:** at nominal 90%, rolling covers 86.7% (relative 85.8%, absolute 83.3%), and is the
    narrowest and most even across meters. None is calibrated; November under-covers.
- A season-adaptive model detector (`--detector model-adaptive`, `detection.adaptive_scores`),
  D033. (T019b)
  - **Score:** the relative residual, centred and scaled daily from the meter's 28 days ending
    7 days before.
  - **Benchmark:** the T018 benchmark now compares three detectors and gives a decision for
    each.
  - **Result:** recall 69% at 0.71 alerts per meter-week (budget 0.5), so it is not adopted.
    The rolling z-score stays the default.
- `intervals.daily_window_statistics`: the shared daily rolling-window helper behind the
  rolling intervals and the adaptive scores. (T019b)
- Alert explanations (`python -m wattwise.ml.explanations`), D034. (T020)
  - **Bundles:** an evidence bundle and a plain-language explanation for every event, covering
    the detector's comparison, the model's expectation with its rolling 90% interval and
    measured coverage, whether the model agrees, persistence, signature evidence, the top
    influences and a check to make.
  - **Influences:** `FeatureModel.contributions` gives LightGBM TreeSHAP contributions in kWh
    (no `shap` dependency), with a safe fallback when they are unavailable.
  - **Wording guard:** no causes, certainty or "waste", enforced by tests and by the command.
- Full-scale tools (`python -m wattwise.ml.scale features|baselines`), D035. (T042)
  - **Feature store:** float32 parquet parts built per batch of meters, hash-checked. It
    matches the in-memory features exactly.
  - **Quality mask** for training and calibration: identical runs of 24 hours or more, zero
    runs of 24 hours or more, and negatives. It drops 9.5% of BDG2's readings.
  - **Full-scale baselines** on all 1,148 meters: seasonal-naive test MAE 15.72 kWh, WAPE 10.8%.
- Sourced carbon-factor and price reference tables (`wattwise.data.reference`), D037. (T021a)
  - 9 carbon-factor rows (7 US eGRID subregions, GB, IE) and 10 price geographies (8 US states,
    GB, IE), each with its source, URL, retrieval date, licence and file SHA-256.
  - US BDG2 sites mapped to their eGRID subregion by a point-in-polygon lookup against the
    published subregion boundaries (`bdg2_sites.EGRID_SUBREGION`).
  - A source with no edition for the requested year (eGRID) falls back to its nearest earlier
    vintage, reported explicitly rather than reused silently.
  - Ontario's 2016/2017 carbon factor is left "not configured": a prior task's cited value could
    not be re-verified against its own source file in this task.
- Excess energy, cost and carbon impact (`wattwise.ml.impact`), D038. (T021)
  - `potential_excess_kwh`: kWh strictly above a T019 interval's upper bound; a negative
    residual never counts, and a missing bound gives "unknown", never zero.
  - Always `ImpactStatus.POTENTIAL`; `VERIFIED` exists only for a future human-confirmed figure
    (T025) and is never set by this module.
  - Wired into every T020 evidence bundle (an `"impact"` section and a rendered sentence).
  - Priced per event's own BDG2 site; cost is only computed for one named geography at a time,
    since summing it across geographies would mix currencies.
- Best model at full scale (`python -m wattwise.ml.fullscale`), D036. (T043)
  - **Adopted and promoted:** LightGBM, L1 loss, 255 leaves, 1,779 trees. Test MAE 13.700 vs
    seasonal-naive 16.705 (+18.0%, scored once); the production refit scores 13.660 (+18.2%).
  - Beats seasonal-naive even on unseen sites (+8.5%), reversing T014's sample-scale finding.
  - The old D026 sample-trained model now loses to seasonal-naive at full scale (−4.4%).
- Downstream pipeline at full scale (T044a), D039-D041.
  - `fullscale --evaluation-model --promote`: the T043 model trained on the training window
    only, promoted only if it reproduces the study's recorded validation MAE exactly.
  - `--store` on `intervals`, `detection`, `explanations` and `impact`: inputs for the
    promoted model's windows read from the T042 store. `explanations --no-influences` skips
    TreeSHAP; `impact --explanations` prices saved explanations.
  - Intervals: linear-time (equal to the old code on test data), calibrated on quality rows
    only (D035), and with no interval where the recent level is not a usable scale (D041).
    The report adds median width and the per-meter width spread.
  - Impact: events the signatures call meter problems (data fault, flatline) are never counted
    as potential excess, cost or carbon, and are reported apart (D040). States the priced cost.
- Detector benchmark at full scale (T044b), D042: `benchmark --store`, with indexed injection
  (equal to the original) and features rebuilt only for the rows the detectors use (equal to
  features on the whole series). The same rule keeps the rolling z-score as the default.
- LEAD check at full scale (T044c), D043: `lead_check --scale-from` trains the check's model
  at full scale (all raw meters, T043 settings) and reports the training scale; the default
  run is unchanged. No default detector changes.
- Alert prioritisation (T022), D044: `wattwise.ml.prioritisation` ranks alerts by a documented
  score (impact, persistence, severity, confidence) with deterministic ties; a product
  assumption, not a probability or a verified saving.
- Database foundation (T023), D045: `wattwise.db` (SQLAlchemy 2 models for buildings and
  meters, Alembic baseline migration), `WATTWISE_DATABASE_URL` as a secret setting,
  `GET /api/v1/ready` (reachable and migrated, else 503 with a reason), a PostgreSQL 18 CI
  service container and `docs/DATABASE.md`.
- Read APIs (T024), D046: `GET /buildings`, `/buildings/{id}`, `/meters`, `/meters/{id}`,
  `/meters/{id}/series` and `/dashboard/summary`; `datasets` and `readings` tables (migration
  `0002`); `python -m wattwise.db.load`. Every response carries `data_kind`; timestamps are UTC.
- Alerts and feedback API (T025), D047: `GET /alerts`, `GET /alerts/{id}`,
  `POST /alerts/{id}/feedback`; `alerts` and `alert_feedback` (migration `0003`);
  `python -m wattwise.db.alerts`. Labels: confirmed waste, expected behaviour, sensor or data
  fault, needs investigation (a reviewer's judgement). Nothing is retrained from feedback.
- CSV upload and analysis (T026), D048: `POST /data/upload` (validation report, 10 MB limit,
  not stored) and `POST /inference/analyze` (expected consumption from the evaluation model and
  the default detector's alerts; works without a model). Dependency: `python-multipart` 0.0.32.
- Model information and monitoring (T027), D049: `GET /models/metadata`, `/models/metrics`
  (recorded values, or `available: false` with a reason) and `/analysis-runs`; migration `0004`.
- Design system and application shell (T028), D050: colour tokens with light, dark and system
  themes (contrast tested), main navigation across five pages, a demo-data banner, provenance
  badges and shared loading, empty and error components.
- `docs/DATASETS.md`: BDG2 provenance, pin rationale, download instructions, verified data
  conventions (local timestamps that are not daylight-saving wall-clock time; units; raw vs
  cleaned), and the licence evidence with WattWise's conservative handling. (T007)

### Changed
- This repository now commits and pushes as the owner's personal account, `shvhjSB`, through
  repository-local git configuration (D006). (T002)
- Backend setup now uses uv (`uv sync --locked`, `uv run --locked ...`). The pip
  `install -e ".[dev]"` path was removed, because the dev tools became a dependency group. (T004)
- The frontend's declared Node.js range is now `^22.22.2 || ^24.15.0 || >=26.0.0`, matching what
  the locked test toolchain requires. (T004)
- The quality engine's interval rule is public as `wattwise.data.quality.infer_interval`, so
  the splits use the same rule. (T010)
- Fox is now audited as fixed-offset time (UTC−7). Its 137 buildings are no longer excluded;
  135 are eligible. (T009c)
- The BDG2 pipeline is version 2: it applies the corrections first and records them in the
  manifest. With Fox included there are 1,148 eligible meters instead of 1,013, and the seeded
  sample changed. (T009c)
- The equation of time moved from `wattwise.data.era5` to `wattwise.data.solar`, unchanged.
  (T013)
- The synthetic model-test load moved to `tests/ml/conftest.py`, to be shared by the model and
  registry tests. `baselines.utc_argument` (formerly private) parses the date options of both
  commands. `FeatureModel.usable` gives the rows with a usable scale. (T015)
- `registry.read_inputs` is public; the detection command reuses it. (T016)
- `detection.run_detection` takes the buildings table (for local time), and its result carries
  the classified events. (T017)
- **The detection command's default is now the rolling same-hour z-score** (open 4, continue 2,
  3 hours), not the model detector. In the T018 benchmark the model detector's alert rate
  doubled out of sample. `--detector model` keeps it, with the tuned thresholds (open 4,
  continue 3, 6 hours). On the BDG2 test quarter this gives 100 events instead of 355. (T018)
- `detect` accepts precomputed scores (`z=`) without a calibration. (T018)
- T018's LEAD human-label scoring moved to a new task, T018b. (T018)
- New runtime dependency `holidays` 0.106 (MIT). It needs `python-dateutil<3`, so the lock
  moved python-dateutil from 3.0.0 (released 2026-10-21, under the two-week rule) to
  2.9.0.post0. (T013)

### Fixed
- Full-scale runs held 20 million identifiers as strings and paged to disk: a baseline run took
  5.1 hours. Category identifiers give identical results in 10 minutes. (T042)
- The T016 reading of Gator's whole-day low events as possible holidays was wrong. The raw data
  repeats one value every hour on those days, and they are now labelled `flatline`. (T017)
- ERA5 checks and tests, after the rest of the review completed. (T007d)
  - **Phase limit:** tightened from 1 h to 0.75 h; a uniform one-hour clock error at a site
    with natural phase 0 had sat exactly on the limit.
  - **Integrity:** the ERA5 file checksum is now always checked, even when BDG2 input
    verification is skipped.
  - **Tests:** four tests could pass without the behaviour they claim and now cannot:
    - instants keeping their hour
    - a different request not reported as "changed"
    - the previous hash being kept
    - the verify success path
- The evaluation report's `git_dirty` flag now counts new, uncommitted files. Before, it
  counted only changed tracked files, so a run with new code was reported as clean. (T012)
- ERA5 enrichment, after an adversarial review of the first T007d commit. (T007d)
  - **Alignment gate:** it used a single two-year median, so a one-hour mislabel in a third of
    the period passed. It now checks every quarter.
  - **Failed checks:** a failed alignment no longer overwrites good outputs.
  - **Fetch:** the manifest is saved after each site, and different requests are not reported
    as "changed".
  - **Errors:** HTTP errors include Open-Meteo's reason; truncated and invalid responses give
    clear errors; an empty overlap no longer reports an invented lag, and NaN is refused in JSON.
  - **Missing-value counts:** only count rows where a source is meant to have a value.
  - **Elevation:** the field is renamed `dem_elevation_m`; it is the site's terrain height, not
    the grid cell's.
  - **Coordinates:** the ERA5 manifest is no longer committed, because it contained BDG2 site
    coordinates (D014). They remain in commit `a624b5d`, as public BDG2 metadata values.
- `docs/DATASETS.md` no longer states the T007 hypothesis that all BDG2 sites use local
  standard time. The T009a audit refuted it, and the document now records the evidence and the
  per-site clocks. (T009a)
- The audit records wrongly stated which credential git pushes with. They now describe the real
  cause of the initial HTTP 403 push failure. (T001)
