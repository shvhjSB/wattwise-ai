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

### Fixed
- `docs/DATASETS.md` no longer states the T007 hypothesis that all BDG2 sites use local
  standard time. The T009a audit refuted it, and the document now records the evidence and the
  per-site clocks. (T009a)
- The audit records wrongly stated which credential git pushes with. They now describe the real
  cause of the initial HTTP 403 push failure. (T001)
