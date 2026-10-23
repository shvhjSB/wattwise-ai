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

### Fixed
- The audit records wrongly stated which credential git pushes with. They now describe the real
  cause of the initial HTTP 403 push failure. (T001)
