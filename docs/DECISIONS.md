# Decisions log

This file records significant architecture and ML decisions, the alternatives considered, and
their consequences. Entries are never deleted. A superseded decision is marked as such and
links to the entry that replaces it.

---

## D001 — Instruction precedence and spec conflicts
- **Date:** 2026-10-23 · **Task:** T001 · **Status:** Accepted
- **Context:** three requirement sources exist:
  - the owner's master build instructions, given to Claude Code and condensed in `CLAUDE.md`
  - [specs/CLAUDE_CODE_PROMPT.md](specs/CLAUDE_CODE_PROMPT.md)
  - [specs/DATASET_CATALOG.md](specs/DATASET_CATALOG.md)

  They mostly agree but conflict in places.
- **Decision:** the master build instructions govern the *workflow* and win any conflict. The
  two spec files remain the detailed product and dataset requirements. The known conflicts are
  resolved as follows:

  | Topic | CLAUDE_CODE_PROMPT.md | Master instructions | Resolution |
  |---|---|---|---|
  | Planning file | `IMPLEMENTATION_PLAN.md` | `docs/ROADMAP.md` and related records | `docs/ROADMAP.md`; no `IMPLEMENTATION_PLAN.md` |
  | Pace | Continue without waiting | One task per run, then stop | One task per run, then stop |
  | Chart library | Recharts or ECharts | Plotly or another suitable library | Open; decided in T030 against the actual chart needs |
  | Feedback labels | confirmed waste / expected behaviour / sensor or data fault / needs investigation | useful / incorrect / needs investigation | Open; decided in T025 |
- **Consequences:** future sessions read `CLAUDE.md` and `docs/PROJECT_STATUS.md` first. The
  open items are tracked in the roadmap tasks named above.

## D002 — Monorepo layout
- **Date:** 2026-10-23 · **Task:** T001 (applied in T002) · **Status:** Accepted
- **Decision:**
  - `backend/` is a single Python project with a **src-layout package `wattwise`**. Subpackages
    are added only when needed: `wattwise.api` (HTTP layer), `wattwise.core` (configuration and
    shared utilities), and later `wattwise.data` (contracts, ingestion, validation) and
    `wattwise.ml` (features, models, evaluation).
  - Dependency rule: `wattwise.ml` and `wattwise.data` must never import `wattwise.api`. The ML
    code stays usable from CLIs and notebooks without the web server.
  - `frontend/` holds the React app.
  - `scripts/` holds thin CLI entry points that call into `wattwise`.
  - `data/sample/` and `data/manifests/` are committed. `data/raw/` and `data/processed/` are git-ignored.
  - `artifacts/` (models, reports) is git-ignored.
- **Alternatives considered:**
  - A separate top-level `ml/` Python package. This gives stronger isolation, but means two
    projects, two environments and cross-package installs for every change. Revisit if the ML
    code ever needs an independent release.
  - A flat `backend/app/` package, the common FastAPI template. The generic name `app` makes CLI
    imports (`python -m app.ml.train`) unclear, and the flat layout allows accidental imports
    from the working directory.
- **Consequences:** one virtual environment and one test suite for all Python code. The
  dependency rule may be enforced by a test later if violations appear.

## D003 — Python tooling
- **Date:** 2026-10-23 · **Task:** T002 · **Status:** Accepted. Environment and locking
  (`venv` + `pip`) are superseded by [D010](#d010--backend-dependency-locking-with-uv); ruff,
  mypy and pytest stand.
- **Decision:**
  - Python `>=3.12`, developed on 3.13.
  - Standard `venv` + `pip`, with `pyproject.toml` built by hatchling. Dependencies use
    compatible-release bounds.
  - **ruff** for linting and formatting, **mypy --strict** with the pydantic plugin, **pytest**.
- **Alternatives considered:**
  - **uv:** faster, with a native lockfile. It is not installed on the development machine, and
    adding it now is not yet justified.
  - **Poetry:** heavier, and adds little at this scale.
- **Consequences:** installs are not fully locked yet. T004 (CI) decides the lock strategy,
  e.g. a compiled requirements lock or adopting uv, so CI and Docker builds are reproducible.
- **Note (T002):** Starlette 1.x builds `TestClient` on **`httpx2`** and treats legacy `httpx` as
  deprecated, so the dev extra depends on `httpx2`. Pytest runs with `filterwarnings = error`,
  so upstream deprecations surface immediately instead of piling up.

## D004 — Liveness vs readiness endpoints
- **Date:** 2026-10-23 · **Task:** T002 · **Status:** Accepted
- **Decision:** `GET /api/v1/health` is a liveness check only: the process is up, and it returns
  the service name, version and environment. `GET /api/v1/ready` is added in T023, when there is
  a real dependency (the database) to check.
- **Alternative considered:** a stub `/ready` that always returns OK. Rejected, because it would
  report readiness that was never checked.

## D005 — Primary dataset: Building Data Genome Project 2
- **Date:** 2026-10-23 · **Task:** T001 · **Status:** Accepted (licence verification pending in T007)
- **Decision:** BDG2 electricity meters are the primary training and evaluation data. They are
  hourly, non-residential data covering about 1,636 buildings in 2016–2017. Other datasets are
  used only for separate, clearly stated research questions and are never pooled with BDG2.
  A deterministic synthetic fixture (T006) runs the tests and the demo mode.
- **Caveats:**
  - Licence discrepancy: the Open Energy Data portal lists CC BY 4.0, while the GitHub
    repository's `LICENSE` shows CC BY-SA 4.0. T007 records the exact source used and resolves
    the applicable terms before any adapted data is shared.
  - The ASHRAE Great Energy Predictor III data overlaps BDG2. It is not independent external
    validation unless the overlap is checked.
  - Raw data is never committed. Downloading is an explicit, documented command.
- **Citation:** Miller, C. et al. (2020), *The Building Data Genome Project 2, energy meter
  data from the ASHRAE Great Energy Predictor III competition*. Scientific Data 7, 368.
  <https://doi.org/10.1038/s41597-020-00712-x>

## D006 — Project-scoped GitHub identity
- **Date:** 2026-10-23 · **Task:** T002 · **Status:** Accepted (owner's instruction)
- **Context:** several GitHub accounts are logged in to `gh` on the development machine. Git used
  `gh auth git-credential`, which returns the *active* account (`aman-agntworksai`, read-only
  here), so the first push failed with HTTP 403. The owner asked that all commits and pushes
  for this project go to their personal account, `shvhjSB`, only.
- **Decision:** pin the identity in this repository's local `.git/config` only:
  - `user.name = shvhjSB` and `user.email` set to the address GitHub links to `shvhjSB`.
  - A local credential helper for `https://github.com` that first resets inherited helpers, then
    answers with `username=shvhjSB` and the token from `gh auth token --user shvhjSB`. The
    token is read from the OS keyring at push time and is **never stored** in the config.
- **Alternatives considered:**
  - `gh auth switch --user shvhjSB`: rejected, because it changes the active account globally
    and would affect the owner's other projects.
  - Granting `aman-agntworksai` write access: rejected, because pushes must come from the personal account.
- **Consequences:**
  - Global account switches do not affect this repo.
  - Commits verified on GitHub are attributed to `shvhjSB`.
  - A fresh clone must repeat the local setup: `git config --local ...`, as recorded in
    `docs/WORK_LOG.md` (T002).
- **Addendum (2026-10-23, owner's instruction):** commit messages and PR descriptions carry
  **no** `Co-Authored-By` or other attribution trailers. Commits `034c2f9`, `9cc423a` and
  `bdbdebc` predate this rule and keep a Claude co-author trailer. Published history is not
  rewritten.

## D007 — PostgreSQL major version 18
- **Date:** 2026-10-23 · **Task:** environment setup (before T003) · **Status:** Accepted
- **Decision:** target PostgreSQL **18**, the newest stable major version available (18.6 at
  install time), everywhere:
  - the local Windows service (`postgresql-x64-18`, port 5432)
  - the CI service container and the Docker Compose image (`postgres:18`), which come later
- **Why:** one major version across local, CI and containers avoids "works on my machine"
  differences in SQL behaviour and migrations.
- **Local security posture:**
  - `pg_hba.conf` allows only `127.0.0.1` and `::1`, with SCRAM-SHA-256.
  - The superuser password is a random 32-character alphanumeric string, stored only in the
    owner's libpq password file.
  - `listen_addresses` is the installer default (`*`). Remote clients are still refused by
    `pg_hba.conf`. Setting it to `localhost` is an optional extra hardening step that needs a
    service restart.
- **Install note:** the EDB installer's cluster initialisation fails when the superuser password
  starts with `-`, because PowerShell parses it as a parameter. Use alphanumeric passwords with
  this installer.

## D008 — Frontend toolchain and version constraints
- **Date:** 2026-10-23 · **Task:** T003 · **Status:** Accepted
- **Decision:**
  - Build and runtime: React 19, Vite 8 (`@vitejs/plugin-react`) and Tailwind CSS 4 (`@tailwindcss/vite`).
  - Tests: Vitest 5 with jsdom, React Testing Library and jest-dom matchers.
  - Linting: ESLint flat config with typescript-eslint `strictTypeChecked` and
    `stylisticTypeChecked`, `react-hooks` (including the React Compiler rules) and
    `react-refresh`, plus **`jsx-a11y`** for accessibility. Lint runs with `--max-warnings=0`.
  - Formatting: Prettier.
  - Installs are locked by `package-lock.json` and installed with `npm ci`.
- **Version constraints:**
  - **TypeScript 6.0, not 7.0.** typescript-eslint 8.72 supports TypeScript `<6.1`. TypeScript 7
    (the native compiler) is the upgrade target once typescript-eslint supports it.
  - **ESLint 9.39, not 10.** `eslint-plugin-jsx-a11y` 6.10 supports ESLint only up to 9.
    Accessibility linting is a product requirement, so it outweighs being on the newest ESLint.
    Considered: ESLint 10 with the `eslint-plugin-jsx-a11y-x` fork (v0.2, far less adoption).
    Revisit when jsx-a11y supports ESLint 10, or when the fork matures.
- **Alternatives considered:**
  - Jest, rejected because Vitest shares Vite's transform pipeline and config.
  - CSS Modules, rejected because Tailwind is required by the stack and keeps styling co-located.

## D009 — Same-origin API access and typed client
- **Date:** 2026-10-23 · **Task:** T003 · **Status:** Accepted
- **Decision:**
  - **Same origin:** the browser calls the API on the same origin, using relative `/api/...` paths.
    - In development, the Vite dev server proxies `/api` to the backend
      (`WATTWISE_DEV_API_TARGET`, default `http://127.0.0.1:8000`).
    - In production, the reverse proxy (T036) does the same.
    - `VITE_API_BASE_URL` is optional, for split-origin deployments. Backend CORS is only
      needed then, and is added with an explicit allow-list in T037.
  - **Typed client:** `src/api/client.ts` validates every response at runtime with a type guard
    and reports three error kinds: `network`, `http` and `invalid-response`. A contract mismatch
    is shown as an error and is never rendered as data. Aborted requests are not errors.
  - **Response types:** written by hand for now, mirroring the Pydantic schemas, with the source
    file named in a comment.
- **Alternatives considered:**
  - Enabling CORS now, rejected because the browser does not need it and it widens the attack surface.
  - Generating types from OpenAPI (`openapi-typescript`), deferred to T024, when the API surface
    grows beyond one endpoint.
  - A data-fetching library (e.g. TanStack Query), deferred to T029, when caching and refetch
    needs are real.

## D010 — Backend dependency locking with uv
- **Date:** 2026-10-23 · **Task:** T004 · **Status:** Accepted
- **Decision:**
  - Lock backend dependencies across platforms in `backend/uv.lock` using `uv`.
  - Declare development-only dependencies via PEP 735 `[dependency-groups]` (`dev = [...]`) in
    `backend/pyproject.toml` instead of `[project.optional-dependencies]`.
  - Pin the compatible `uv` version range in `backend/pyproject.toml`
    (`[tool.uv] required-version = ">=0.12.24,<0.13"`), keeping local `uv` and CI on the same
    lockfile format.
  - Record the target Python version in `backend/.python-version` (`3.13`).
  - Local development and CI both create `backend/.venv` with `uv sync --locked` and run tools
    with `uv run --locked`. Docker will do the same (T036). The former `pip install -e ".[dev]"`
    path no longer exists, because the `dev` extra became a dependency group.
  - uv is pinned to **0.12.24**, the newest release at least two weeks old when this decision was
    made. All 0.13.x releases were under two weeks old, and new releases are avoided briefly as a
    supply-chain precaution. CI also verifies the uv download against a SHA-256 checksum pinned
    in the workflow (D011).
  - The **build backend** is pinned too. `uv.lock` does not cover the environment that builds
    this package (hatchling and its dependencies), so `[tool.uv] build-constraint-dependencies`
    pins all six packages, with hatchling at 1.32.4. Verified with a cold cache: uv selected
    exactly `hatchling==1.32.4`. These pins have no hashes, unlike the main lock.
  - Scope of the two-week rule: it covers the uv binary and CI actions. It does not cover locked
    Python or npm packages, which are locked at their current releases with hashes. Adding a
    cooldown for those (e.g. uv `exclude-newer`) is an option the owner may adopt later.
- **Why a universal lock matters here:** development happens on Windows and CI runs on Linux.
  `uvicorn[standard]` pulls in platform-specific packages, e.g. `uvloop` on Linux only. A
  `pip freeze` or `pip-compile` lock made on Windows would silently omit them. `uv.lock` resolves
  for all platforms at once; it contains `uvloop` with the marker `sys_platform != 'win32'`
  (verified).
- **Alternatives considered:**
  - `pip-tools` (`pip-compile`): locks are specific to the platform that made them, so this setup
    would need one lock per platform.
  - Poetry: heavier, and its lock is also universal, but it adds more than this project needs.
  - Unlocked installs: rejected, because upstream releases could change CI and Docker builds
    without any change in this repository.
- **Consequences:**
  - `backend/uv.lock` is committed. Change dependencies with `uv add` / `uv lock`, and commit
    `pyproject.toml` and `uv.lock` together.
  - In CI, `uv sync --locked` fails if the lock is stale.
  - Contributors need uv 0.12.24 or a later 0.12.x (`[tool.uv] required-version`). Other versions
    are rejected, including newer 0.13 releases, so installs must be version-pinned
    (see `backend/README.md`).

## D011 — CI workflow design and action pinning
- **Date:** 2026-10-23 · **Task:** T004 · **Status:** Accepted
- **Decision:**
  - Single CI workflow in `.github/workflows/ci.yml` running on pushes to `main`, all pull
    requests, and `workflow_dispatch`.
  - Supply-chain security: all third-party GitHub Actions are pinned to full 40-character commit
    SHAs with comment annotations naming the release tag (e.g. `actions/checkout@3d3c42e5... # v7.0.1`).
  - Least privilege: top-level `permissions: contents: read`.
  - Concurrency:
    - Pull-request runs share one group per PR, and a new push cancels the older run.
    - Every other run (pushes to `main`, manual runs) gets a unique group (`github.run_id`), so no
      run on `main` is ever cancelled.
    - The unique group matters because GitHub replaces a *pending* run whenever another run
      queues in the same group, even with `cancel-in-progress: false`. One shared `main` group
      would therefore lose results during quick bursts of pushes. This was found in the T004 review.
  - Parallel jobs for backend (`ubuntu-24.04`, Python 3.13 via `astral-sh/setup-uv`) and
    frontend (`ubuntu-24.04`, Node 24 via `actions/setup-node` reading `frontend/.nvmrc`).
  - Both jobs cache dependencies, keyed on their lockfiles:
    - `astral-sh/setup-uv` uses `cache-dependency-glob: uv.lock`. The glob is relative to the
      action's `working-directory: backend`, which the pinned action's own docs confirm.
      `backend/uv.lock` would have resolved to the non-existent `backend/backend/uv.lock`, and the
      cache would never have refreshed. This was found in the T004 review.
    - `actions/setup-node` uses `cache-dependency-path: frontend/package-lock.json`, which that
      action resolves from the repository root.
  - The uv download is verified against a SHA-256 checksum pinned in the workflow
    (`uv-x86_64-unknown-linux-gnu.tar.gz` for 0.12.24). It was cross-checked in the GitHub
    release API digest and in the release's `.sha256` asset. Pinning the action by SHA does not
    pin the binary it downloads.
  - Exact mirror of local checks: backend runs ruff (check and format), strict mypy and pytest;
    frontend runs Prettier, ESLint, tsc, Vitest and Vite production build.
  - Checkout uses `persist-credentials: false`, so later steps cannot reuse the job's Git token.
    Jobs have 15-minute timeouts.
  - Action releases are pinned only once they are at least two weeks old, which is why
    `setup-uv` is v10.2.0 rather than the newest v10.3.x. The workflow is linted with
    `actionlint` before pushing.
- **Alternatives considered:**
  - A single sequential job: rejected because parallel jobs finish faster and pinpoint failures immediately.
  - Floating action tags (`@v4`): rejected because tags are mutable and vulnerable to supply-chain tampering.
- **Consequences:**
  - CI **reports** the result of every push and pull request. It does **not block** anything:
    `main` has no branch protection, and work is pushed directly to it. Making CI a required
    status check is a separate decision for the owner.
  - Pushing workflow files requires a GitHub token with the `workflow` scope.
  - Pinned SHAs do not update themselves. Upgrades are deliberate edits, applying the same
    two-week rule. A uv upgrade changes three places together: `version` and `checksum` in
    `ci.yml`, and `required-version` in `backend/pyproject.toml`.

## D012 — Canonical data contract and validation design
- **Date:** 2026-10-23 · **Task:** T005 · **Status:** Accepted
- **Decision:** one canonical shape for readings, buildings and weather, version `1.0`. It is
  specified in [DATA_CONTRACT.md](DATA_CONTRACT.md) and implemented in `wattwise.data`.
  - **Structure vs quality:** the contract rejects only malformed or physically impossible data.
    Plausibility (gaps, negative use, flatlines, outliers) is T008's job and does not reject data.
  - **Time:** timestamps must carry an explicit offset and are stored as `datetime64[us, UTC]`.
    A reading's timestamp is the *start* of its interval. Timestamps without an offset are
    rejected. With `utc=True`, pandas silently treats them as UTC, so the validator checks for an
    offset before parsing (verified with pandas 3.0.6).
  - **Units:** each meter type has exactly one canonical unit: `kWh` for electricity and the
    other energy types, `m3` for water and irrigation. Adapters convert before loading; a
    non-canonical unit is an error, never a silent conversion. Only `electricity` is analysed in
    this version; other types pass with an `unsupported_meter_type` warning.
  - **Missing is not zero:** a missing `value` means not measured. In CSV only an empty cell
    means missing; text like `NaN` is rejected rather than guessed at.
  - **Reporting:** every problem is reported once, with a stable code (21 codes), severity,
    affected-row count, up to 5 row numbers, example values and a fix hint. The issue models are
    Pydantic, so the upload API (T026) can return them unchanged.
  - **One code path:** text frames (uploads) and typed frames (adapters) go through the same
    validator, which coerces, checks and produces the canonical frame in one pass. A test proves
    that a CSV round trip equals the in-memory canonical table.
  - **CSV parsing** uses the standard library `csv` module. pandas pads rows that have too few
    fields with `''`, which makes them indistinguishable from empty cells (verified).
  - **Performance:** identifiers and timestamps are checked once per *distinct* value and then
    mapped back to rows. Before this change, regex matching was 52% of the runtime. Measured on
    Windows: about 0.4 M rows/s for typed frames (1.05 M rows in 2.65 s) and 175,680 CSV rows in
    1.42 s.
  - **Dependencies:**
    - pandas is constrained to the 3.0 series (3.0.6), because `pandas-stubs` 3.0.5, needed for
      strict mypy, targets 3.0. pandas 3.1.0 was one day old.
    - `tzdata` is a direct dependency, so IANA time zone validation works on every platform,
      including slim containers without a system tz database.
- **Alternatives considered:**
  - **pandera:** a capable dataframe-schema library, but it adds a dependency and its error
    reports are not shaped for end users. The structured, actionable report needed by the upload
    API would have to be rebuilt on top of it anyway.
  - **Per-row Pydantic models:** clear, but far too slow for millions of rows.
  - **Accepting naive timestamps as UTC, or as building-local time:** rejected. It silently
    shifts data by hours and creates false anomalies.
- **Consequences:**
  - Adapters (T009) must map source columns and units to the contract and record what they
    excluded.
  - Contract changes follow `MAJOR.MINOR` versioning (see DATA_CONTRACT.md).
  - `tests/data/test_contract_docs.py` fails if the document and the code drift apart, including
    if its CSV examples stop behaving as described.

## D013 — Synthetic fixture design
- **Date:** 2026-10-23 · **Task:** T006 · **Status:** Accepted
- **Decision:** `wattwise.data.synthetic` generates a small, clearly synthetic dataset. It is
  committed under `data/sample/synthetic/` (about 564 KB).
  - **Fixed scenario, seeded noise.** The sites, buildings and injected anomalies are fixed and
    versioned (`GENERATOR_VERSION`). The seed changes only the random noise, so the labels are
    identical for every seed.
  - **Realistic enough to be useful:**
    - Hourly load comes from base load, occupancy and electric heating, plus AR(1) noise.
    - Occupancy schedules run in each building's **local** time, and the data is stored in UTC.
      Two time zones (London, New York) exercise the contract's time handling.
    - Weather has a trend, day-to-day variation and a daily cycle.
    - Verified: both offices peak at 10:00 local time. On daily averages, a fitted slope recovers
      each building's heating coefficient (e.g. −2.22 vs the model's 2.0 kWh/h per °C).
  - **Six injected anomalies, one per signature that T017 will detect:** spike, sustained
    excess, overnight base load, gradual drift, flatline and missing data. The labels give UTC
    windows (end exclusive), the effect and `label_source = synthetic_injection`.
  - **The data differs from its clean counterfactual only inside labelled windows.** The
    generator keeps the clean readings in memory as ground truth, and a test checks this
    property exactly.
  - **Synthetic by construction:**
    - All identifiers start with `syn-`.
    - Coordinates are left empty rather than invented.
    - The README and manifest carry a SYNTHETIC notice.
    - Results on this data are to be reported as synthetic benchmarks only.
  - **Generated, not hand-written.** The README (including its anomaly table) and a manifest of
    SHA-256 hashes and row counts are produced by the generator. Output formatting is fixed
    (decimals per column, ISO `Z` timestamps, LF line endings) and nothing time-dependent is
    written, so the files are byte-identical for a given seed.
- **Alternatives considered:**
  - Random anomaly placement per seed: rejected, because fixed, documented windows make labels
    and the README stable.
  - Storing the clean counterfactual readings in the repository: unnecessary, because they are
    regenerated deterministically.
  - Committing a real-data sample instead: licence questions (D005) and no ground truth for
    anomalies.
- **Consequences:**
  - Changing the model or scenario means bumping `GENERATOR_VERSION` and regenerating the
    folder. A test fails if the committed files differ from a fresh generation.
  - Byte-identity across operating systems depends on the locked NumPy and pandas versions. CI
    on Linux checks it against files generated on Windows.

## D014 — BDG2 acquisition: pin, integrity and licence handling
- **Date:** 2026-10-23 · **Task:** T007 · **Status:** Accepted
- **Decision:**
  - **Pin** BDG2 at commit `753598e0` (2020-06-24): the last commit that changed data. Its data
    is byte-identical to today's `master`. The `v1.0` tag (the Zenodo release) is **not** used,
    because it predates corrections to `weather.csv` and `electricity_cleaned.csv`. A
    CC-BY-labelled but known-erroneous file is worse than a corrected one.
  - **Fetch** from GitHub's LFS media endpoint. The repository's files are LFS pointers, and
    `raw.githubusercontent.com` serves the 131-byte pointer, not the data.
  - **Verify** every file against the size and SHA-256 recorded in its LFS pointer at the pin,
    so the expected values come from the source itself. Downloads stream to `.part` and are
    renamed atomically only after verification. Valid files are not downloaded again, and
    mismatching files are never overwritten without `--force`.
  - **Download** metadata, weather and **both** raw and cleaned electricity, about 369 MB in
    total. Cleaned data had anomaly-detected outliers and zero readings removed by BDG2. Raw keeps
    real (unlabelled) anomalies. Which to use for what is decided in T009/T012.
  - **Implementation:** the Python standard library (`urllib`, `hashlib`) with an injectable
    opener, so tests never use the network. The provenance manifest is **JSON**
    (`data/manifests/bdg2.json`) rather than the YAML the roadmap mentioned, to avoid adding a
    YAML dependency for one file.
  - **Licence:** four sources say three things (MIT, CC BY 4.0, CC BY-SA). WattWise follows the
    most restrictive reading: it attributes the source, never redistributes raw or derived BDG2
    data, and documents its transformations. Public display of BDG2-derived results is an owner
    decision at T038. The evidence is in [DATASETS.md](DATASETS.md#licence).
- **Alternatives considered:**
  - Download the Zenodo v1.0 zip (595 MB, CC BY 4.0): rejected, because it is larger, uncorrected
    and verified by MD5 only.
  - `requests` or `httpx` for downloads: unnecessary for streaming one file at a time.
  - Pin `master`: rejected, because a branch can move; a commit cannot.
- **Consequences:**
  - The real download took 25 s and was verified independently with `sha256sum`.
  - T009 inherits three verified facts, recorded in DATASETS.md:
    - BDG2 timestamps are local but **not** daylight-saving wall-clock time.
    - The interval convention (start or end) is not documented.
    - Electricity is wide-format kWh.

## D015 — Data-quality engine design
- **Date:** 2026-10-23 · **Task:** T008 · **Status:** Accepted
- **Decision:** `wattwise.data.quality` assesses canonical readings *after* the contract, and
  reports without rejecting anything ([DATA_QUALITY.md](DATA_QUALITY.md)).
  - **Contract first.** Structural problems, including duplicate timestamps, stop the
    assessment and appear as contract issues. The quality checks never re-implement contract
    rules.
  - **Nine checks:** gaps, irregular intervals, missing values, low coverage, negative values,
    zero runs, flatlines, extreme values and implausible intensity (the unit and scaling check).
    Each meter is assessed on its own inferred interval.
  - **Two severities:** `info` for facts, `warning` where data is likely unreliable. Messages
    phrase causes as hypotheses.
  - **Quality is not anomaly detection.** On the synthetic sample, the checks must find exactly
    the injected data faults (missing data, flatline) and none of the behaviour anomalies; a test
    enforces this.
  - **Extreme values use a ratio to the meter's 99th percentile (default 5×), not a robust
    z-score.** This is evidence-based. The z-score version flagged the injected 2.2× behaviour
    spike at 11.3 robust SDs, because bimodal office load (occupied around 110 kWh, unoccupied
    around 45 kWh) makes the MAD small. The ratio targets order-of-magnitude errors (Wh/kWh slips,
    counter resets).
  - **Defaults with rationale:** coverage 95%, flatline 6 intervals, zero runs 24 intervals
    (BDG2's own cleaning rule), extremes 5× the 99th percentile, intensity 2–2000 kWh/m²/year.
    All are configurable and validated (`QualityThresholds`).
  - **Deterministic JSON and Markdown reports**, with no generation time. A committed example
    for the synthetic sample (`docs/reports/`) is kept up to date by a test.
- **Alternatives considered:**
  - Robust z-score for extremes: rejected (above).
  - IQR fences: these flag the same bimodal peaks.
  - Failing the pipeline on quality warnings: rejected, because quality findings inform
    modelling and evaluation choices and do not invalidate data. Rejection belongs to the
    contract.
  - Assessing weather in the same engine: deferred to T009, where weather is joined to readings.
- **Consequences:**
  - Measured speed: 1.75 M readings for 100 meters take 5.3 s, of which the contract check is
    4.9 s. That extrapolates to about 84 s for all BDG2 electricity.
  - Partial-period scaling errors can slip through; this is documented as a limitation, and
    level shifts belong to anomaly detection (T016/T017).

## D016 — BDG2 timestamps: per-site clock, decided by evidence
- **Date:** 2026-10-24 · **Task:** T009a · **Status:** Accepted. Amended by
  [D020](#d020--bdg2-metadata-corrections-with-a-falsifiable-zone-check): Fox's time zone is
  corrected, so Fox is now standard (fixed UTC−7) and 4 sites (385 buildings) stay undetermined.
- **Context:**
  - BDG2's "local" timestamps form a regular 17,544-hour grid, although every site is in a
    daylight-saving zone (T007).
  - The hypothesis that all sites use local standard time was tested before any conversion code
    was written. It was **refuted**: at the clock changes, weekday load profiles of most sites do
    **not** move (wall-clock behaviour), while three sites move exactly as standard time
    predicts.
  - The transition hours confirm the mix. Several sites leave the spring non-existent hour
    systematically empty; at some, the autumn hour holds about twice a normal reading (two real
    hours summed).
- **Decision:** classify each site separately, with `wattwise.data.time_convention` and
  `wattwise.data.bdg2_audit`, and pin the verdicts.
  - **Electricity (human signal):** compare weekday profiles 3 weeks before and after each of
    the 8 transitions (2016–2017) at lags of −1, 0 and +1 h.
    - A verdict needs at least 2 usable transitions and at least 75% agreement, and it must hold
      at every identifiability margin (0.0025, 0.005, 0.01).
    - A "standard" verdict is overruled to undetermined if every spring non-existent hour is
      systematically empty, because that is the wall-clock-on-a-grid signature.
  - **Weather (solar signal):** "standard" requires structural evidence: a real reading at every
    spring non-existent hour, no repeated timestamps, and no wall-clock majority among the
    transitions. The seasonal phase shift (−1.44 to +0.28 h, never about +1 h) is recorded as
    supporting evidence.
  - **Verdicts:**
    - Electricity: 11 sites wall-clock, 3 standard, **5 undetermined**.
      - Fox and Robin depend on the margin.
      - Rat has conflicting evidence.
      - Shrew and Swan have insufficient or mixed evidence.
    - Weather: standard at all 19 sites.
  - **Conversion (`to_utc`):**
    - Standard sites: add the fixed **January** offset. This handles `Europe/Dublin`, whose
      database "standard" is +1.
    - Wall-clock sites: localise in the zone. Non-existent and repeated hours become NaT and
      are dropped and counted.
    - Undetermined sites: cannot be converted, and are excluded.
  - **Interval convention:** interval-start is an explicit assumption, because the data cannot
    distinguish start from end (at most a 1-hour labelling uncertainty).
- **Alternatives considered:**
  - **One convention for all sites:** refuted by the evidence. Applying standard time
    everywhere would shift 11 sites by an hour for half of every year, planting false anomalies
    at each clock change.
  - **Guessing undetermined sites (e.g. a majority vote at one margin):** rejected, because a
    wrong guess is invisible downstream.
  - **Per-building classification for mixed sites such as Rat:** possible later, if Rat's 305
    buildings are needed.
- **Consequences:**
  - **522 of 1,578 electricity buildings are excluded.** T009b samples only from sites with a
    determined clock.
  - The pinned table makes preprocessing deterministic, and the audit CLI re-checks it against
    the data (23 s).

---

## D017 — BDG2 preprocessing pipeline design
- **Date:** 2026-10-24 · **Task:** T009b · **Status:** Accepted. Pipeline version 2 applies the
  D020 metadata corrections, so the first-run counts below are superseded (current run in
  DATASETS.md).
- **Decision:** `wattwise.data.bdg2_prepare` converts the pinned BDG2 files into canonical
  tables. Every step is deterministic, and every dropped meter or hour is counted.
  - **Variant: cleaned by default, raw optional (`--variant raw`).**
    - Cleaned data is used for training baselines and synthetic-injection benchmarks, where
      unlabelled real anomalies would blur the score.
    - Raw data is used for exploration and for showing the detector on real data. Its
      anomalies are not ground truth.
    - The manifest records the variant and the reason for it. Each variant writes to its own
      output folder.
  - **Eligibility, checked in this order:**
    1. An electricity column with a metadata row.
    2. A determined site clock (D016).
    3. At least 50% of the convertible hours have a reading (`--min-coverage`).
    Every other meter is logged with one reason: `not_electricity`, `no_metadata`,
    `undetermined_clock`, `insufficient_data` or `not_sampled`.
  - **Sample:** a simple random sample of eligible meters (`--sample-meters`, default 20), drawn
    with `numpy.random.default_rng(seed)` from the sorted list (default seed 2016). `0` means
    every eligible meter.
    - The sample is not stratified by site or use, so it does not represent the population.
      Later evaluations report which sites they cover.
  - **UTC conversion:** `to_utc` is applied with the pinned clock, once per site.
    - Non-existent and repeated wall-clock hours are dropped and counted per site: 4 hours over
      2016–2017.
    - In UTC, an autumn drop leaves a 2-hour gap, which the quality report shows as a gap.
  - **Weather:** a separate canonical table for the sampled sites, converted with its own
    clock (standard time, D016). It is not merged into readings: buildings carry `site_id`, and
    the contract keeps the tables separate.
    - The manifest records, per site, the share of reading hours that have a weather row
      (join coverage).
  - **Outputs:** Parquet via pyarrow 26 (readings, buildings, weather), an exclusion log in CSV,
    a T008 quality report and `manifest.json`. The manifest records the pinned commit, input
    SHA-256s, whether inputs were verified, the options, assumptions, statistics, output
    SHA-256s and the licence note (D014).
    - Inputs are verified against the pinned checksums before reading, unless
      `--skip-input-verification` is given, which is also recorded.
    - Output files are byte-identical for identical inputs and options; this is tested.
- **Alternatives considered:**
  - **Merging weather into readings:** rejected. It duplicates weather per meter, and it hides
    missing weather as missing columns instead of reporting it.
  - **Stratified sampling by site:** deferred. It is not needed for a first baseline, and the
    plain seeded sample is easy to reproduce and explain.
  - **Imputing the dropped DST hours:** rejected. Imputing would invent readings; dropping keeps
    the data honest, and only 4 hours per meter are affected.
  - **CSV outputs:** rejected for the processed tables. Parquet keeps the dtypes (UTC timestamps)
    and is much smaller. On the first run, readings were 1.8 MB as Parquet vs 37 MB as CSV, and
    weather 0.9 MB vs 7.3 MB.
- **Consequences:**
  - **First real run** (2026-10-24, cleaned, seed 2016):
    - 1,013 of 1,578 electricity meters are eligible (522 undetermined clock, 43 insufficient
      data), and 20 are sampled from 9 sites.
    - 350,804 readings, 93.02% coverage.
    - These are observed counts from one seeded sample, not population statistics.
  - **The cleaned data still has quality warnings.** 12 of 20 sampled meters have flatlines
    (BDG2's cleaning removes zero runs, not constant non-zero runs). 10 have low coverage.
    Baselines (T012) must cope with gaps.

---

## D018 — Leakage-safe split design
- **Date:** 2026-10-24 · **Task:** T010 · **Status:** Accepted
- **Decision:** `wattwise.ml.splits` defines every split by **explicit UTC time windows**
  ([EVALUATION.md](EVALUATION.md#splits-t010)).
  - **Configs are frozen pydantic models** that reject unknown fields, naive datetimes, negative
    gaps and empty or overlapping windows. They serialise to JSON with UTC timestamps and ISO
    8601 durations, and their SHA-256 identifies the split.
  - **Windows are half-open, and the whole interval must fit.** A reading is in a window only if
    `[timestamp, timestamp + interval)` lies inside it. The interval uses the quality engine's
    rule, now public as `infer_interval`. Readings that cross a boundary are not used, and are
    counted.
  - **The gap is carved from the end of the preceding window.** The test window is then exactly
    the configured one, which is what reports cite.
  - **Rolling origin uses expanding windows of fixed durations.** It does not use calendar
    months; multiples of 7 days keep the weekday mix equal.
  - **Holdout:**
    - By building or by whole site, a seeded draw over sorted IDs, at least one and never all.
    - Held-out buildings are tested **only in the test window** (`test_unseen`), so an
      unseen-building result is also a future-period result. Their earlier readings are not used.
  - **Self-verification:**
    - `make_split` re-checks every fold on its rows and raises `LeakageError`. The checks:
      disjoint roles, rows inside their windows, earlier roles end first, and holdout isolation.
    - A role with no readings is an error.
  - **Memory:** folds hold row positions into the source table, not copies.
- **Alternatives considered:**
  - **Boundaries as fractions of the data:** rejected. Meters cover different periods, so a
    fraction is ambiguous and changes when the data changes. Explicit dates are reproducible and
    citable.
  - **scikit-learn `TimeSeriesSplit`:** rejected. It splits by row position, which is wrong for
    stacked multi-meter tables. It also has no notion of intervals, buildings or sites.
  - **Testing held-out buildings over the whole period:** rejected. It shares time, weather and
    campus events with training, which gives optimistic results.
  - **Sliding windows and calendar-month steps:** deferred until a model needs them.
- **Consequences:**
  - T011 saves the manifest with every result.
  - T014 chooses models on validation or rolling folds only. The test window is used once per
    reported result.
  - **Feature leakage is out of scope here** (T013). Splits cannot stop a feature from looking
    ahead.
  - **Performance:** checked on 13 rolling folds plus a holdout:
    - the BDG2 sample (350,804 rows): 0.8 s
    - a synthetic 5.3 M-row table: 21 s

---

## D019 — Supplementary data sources per gap
- **Date:** 2026-10-24 · **Task:** T007b · **Status:** Accepted. Three items await the owner
  (see Open decisions).
- **Context:** BDG2 has no anomaly labels, prices, carbon factors or solar radiation, and thin
  metadata. Its "US/..." time zones hide two Canadian sites and an Arizona site.
- **Decision:** one recommended source per gap, each chosen on evidence: primary-source licence,
  coverage of the BDG2 sites and years, and independence. The full evidence is in
  [DATASETS.md](DATASETS.md#supplementary-data-evaluation-t007b).
  - **Labels: LEAD 1.0.**
    - The only real, human-labelled whole-building hourly dataset found. It is BDG2's own meters
      in 2016.
    - It joins to BDG2 at zero time shift (97.6% of sampled readings identical).
    - Only its labels are used, never its readings.
  - **Carbon factors:** eGRID2016 (US, also used for 2017, as EPA advises), DESNZ 2016/2017 (UK),
    SEAI (Ireland) and the ECCC National Inventory Report (Ontario). All are annual averages for
    the data year, with source and unit recorded.
  - **Prices:** EIA-861 state commercial averages (US), DESNZ Quarterly Energy Prices (UK) and
    CSO TMEGB04 (Ireland), labelled as averages and estimates. **Ontario gets no price**,
    because no open retail commercial source was verified.
  - **Weather:** ERA5 radiation (modelled) for the 15 located sites; humidity derived from BDG2.
    Holidays from `holidays` (MIT), and sun position from pvlib (BSD-3-Clause).
  - **Other buildings:** LBNL Building 59 (CC0) for detector checks against end uses, HVAC and
    occupancy. HKUST (CC0) for generalisation. Both are reported separately from BDG2.
  - **Not filled:** building metadata, academic calendars, and every location-based input for
    the 4 sites without coordinates. They stay missing; nothing is inferred.
- **Alternatives considered:**
  - **EnerNOC** (CC BY-NC) and the **Open-Meteo free tier** (non-commercial): usable only if
    WattWise is non-commercial.
  - **NREL ComStock:** rejected until its conflicting licence statements are clarified.
  - **Building Data Genome 1:** rejected for independence; most of its buildings match BDG2.
  - **The UK Carbon Intensity API:** rejected, as it starts in September 2017.
- **Consequences:**
  - New tasks: T007c (labels), T007d (weather), T009c (metadata corrections, which may recover
    Fox's 137 buildings), T021a (reference tables), T040 (Building 59) and T041 (HKUST).
  - Nothing is acquired until its task runs; no supplementary data is committed.

---

## D020 — BDG2 metadata corrections with a falsifiable zone check
- **Date:** 2026-10-24 · **Task:** T009c · **Status:** Accepted
- **Context:** T007b found two metadata errors:
  - **Fox:** its coordinates are in Arizona, which has no daylight saving time, but it was
    published as `US/Mountain`.
  - **Wolf:** its longitude sign is flipped, which puts it in the Netherlands instead of Dublin.

  Excluding Fox would waste 137 buildings. Correcting the metadata on coordinates alone would
  trust one field to fix another.
- **Decision:**
  - **Pinned corrections.** `wattwise.data.bdg2_sites.CORRECTIONS` records each correction with
    the published value, the corrected value and the evidence.
    - They are applied before the audit and the preparation, and recorded in every manifest
      (pipeline version 2).
    - A correction **refuses to run** if the data holds a different published value.
  - **A time-zone correction must pass a zone check against the readings**, made under the
    published zone. Otherwise the site stays undetermined. The check:
    - Allows no occupant shift at any usable clock change.
    - Allows no daylight-saving fingerprint at any clock-change hour: an empty hour, an empty
      neighbouring hour, copied or interpolated readings, or merged hours. Each hour is compared
      with the same hour 1–3 weeks before and after.
    - Only corrections to zones without clock changes are supported. Their time is a fixed
      offset, so the standard and wall clocks coincide.
  - **Site regions** (ISO 3166 country and subdivision) are pinned from the corrected
    coordinates, and are `None` where coordinates are missing.
- **Evidence:**
  - **Fox passes.** Its lags are 0, 0, +1 and 0, and its four clock-change hours show no
    fingerprint.
  - **The check rejects all 18 other sites** when each is wrongly "corrected" to a zone without
    daylight saving: 11 wall-clock sites by fingerprint, 3 standard-time sites by shift, and the 4
    undetermined sites.
  - The first rule, "no majority of shifts", accepted Robin (London). It was tightened to "no
    shift at all", which Fox still passes.
- **Alternatives considered:**
  - **Correcting from coordinates alone:** rejected. A wrong coordinate (Wolf's) would then
    silently change a clock.
  - **Leaving Fox excluded:** rejected, because the evidence is strong and testable.
  - **A per-building zone check:** not needed. All 137 Fox buildings share one zone and
    coordinate.
- **Consequences:**
  - 1,148 eligible meters instead of 1,013.
  - 4 undetermined sites (385 buildings) instead of 5 (522).
  - Usable LEAD buildings rise from 152 to 173.
  - The seeded sample changed, so every BDG2-derived count is restated for version 2.
  - Passing the zone check does not prove a zone; the coordinates do. The check is there to
    catch a wrong correction.

---

## D021 — Evaluation metrics and report design
- **Date:** 2026-10-24 · **Task:** T011 · **Status:** Accepted
- **Decision:** `wattwise.ml.evaluation` is the one way to score a forecaster
  ([EVALUATION.md](EVALUATION.md#metrics-and-reports-t011)).
  - **Honest scoring rules:**
    - Only evaluation roles are scored, never `train`.
    - Predictions must cover exactly the role's rows. Missing predictions are explicit NaN and
      counted; missing actual values are counted, never scored.
    - One unit per scored set, and seen and unseen buildings are reported separately.
  - **Metrics:**
    - The error is predicted − actual.
    - MAE, RMSE, bias (mean error), and WAPE = Σ|error| / Σ|actual|.
    - WAPE is reported only when Σ|actual| ≥ `wape_min_total` (default 1 kWh, configurable),
      otherwise the reason is given.
  - **Levels:**
    - Per meter, per building (pooled) and overall (pooled).
    - Macro: the unweighted mean over meters; macro WAPE covers only meters with a reported WAPE.
    - For multi-fold splits, a summary across folds.
  - **Provenance:**
    - The report embeds the split manifest.
    - It embeds a content fingerprint of the readings: sorted by meter and time, little-endian
      bytes, one NaN pattern and +0.0 for −0.0, so it ignores row order and index.
    - It embeds the package version, the git commit and a dirty flag.
  - **Reproducibility:** no wall-clock time, metrics rounded to 6 decimals, LF line endings.
- **Alternatives considered:**
  - **MAPE:** rejected. It is undefined at zero readings and explodes near zero, which is common
    at night or with meter faults.
  - **CV(RMSE) (ASHRAE Guideline 14):** deferred. It is useful for comparing buildings, and can
    be added from the same errors if needed.
  - **Hashing the data with pandas' object hashing:** rejected. Its stability across pandas
    versions is not guaranteed.
  - **A timestamp in the report:** rejected. It breaks byte reproducibility; the git commit and
    the data fingerprint identify a run.
- **Consequences:**
  - T012 baselines are scored by this harness only, and every reported number comes with its
    report.
  - Bias is visible before any excess-energy estimate (T021) relies on a baseline.

---

## Open decisions (tracked in tasks)

| Topic | Decide in | Notes |
|---|---|---|
| Test database strategy | T023 | PostgreSQL 18 locally (D007), plus a service container in CI |
| API type generation | T024 | Hand-written types and guards (D009) vs OpenAPI codegen |
| Server-state library | T029 | Plain hooks (D009) vs TanStack Query |
| Feedback label set | T025 | See D001 |
| Chart library | T030 | See D001; needs interval bands, synchronised zoom and accessibility |
| Browser E2E tooling | T035 | Only if justified |
| LEAD 1.0 use under an unclear licence | T007c | Recommended: local evaluation only, never redistributed, cited (D019) |
| Is WattWise non-commercial? | T007d, T041 | Decides the Open-Meteo free tier and EnerNOC; otherwise use the Copernicus CDS |
| US carbon rate type and UK factor-year convention | T021a | Recommended: average (total output) factors; the publisher's reporting-year convention |

