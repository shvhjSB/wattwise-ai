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
  | Feedback labels | confirmed waste / expected behaviour / sensor or data fault / needs investigation | useful / incorrect / needs investigation | The spec's four, mapped onto the three (D047, T025) |
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

## D022 — Owner decisions on LEAD and usage, and the LEAD label join
- **Date:** 2026-10-24 · **Task:** T007c · **Status:** Accepted (owner decisions of 2026-10-24)
- **Owner decisions:**
  1. **LEAD 1.0 is used locally for evaluation only.** It is never committed or redistributed,
     and the paper is always cited. Its repository has no licence and the Kaggle rules forbid
     redistribution (D019).
  2. **WattWise is non-commercial**, a personal portfolio and research project.
     - So the Open-Meteo free API may be used for ERA5 weather (T007d).
     - EnerNOC's CC BY-NC data is also usable (T041).
     - This must be revisited if the project is ever used commercially.
- **Decision (join design):** `wattwise.data.lead`.
  - **Pinned download:** commit `80e13682` and SHA-256, also matched against GitHub's git hash.
    Provenance only is committed, in `data/manifests/lead.json`.
  - **Join:** labels join by `building_id_kaggle` and local time, and are converted to UTC with
    each site's audited clock.
  - **Exclusions,** each with one reason: no BDG2 building, undetermined clock, not annotated
    (LEAD blanked the reading), or an unconvertible daylight-saving hour.
  - **Labels only:** LEAD's readings are never used. A per-row flag records whether LEAD's
    reading equals BDG2's raw reading, within 1e-3.
- **Evidence (full file):**
  - 1,438,672 usable rows on 173 buildings, with 31,166 anomalies.
  - LEAD's readings equal BDG2's at 98.41% of rows but only 54.06% of anomalies.
  - 22.85% of the anomalies have no cleaned BDG2 reading.
- **Consequences:**
  - T018 scores detectors against LEAD on the raw variant, on rows where the readings match.
    Mismatched labels are reported separately.
  - Two bugs were found by the tests and fixed before any result was kept:
    - **Clock identity:** pandas `Series.map` turns the `Clock` StrEnum into plain strings, so
      `to_utc`'s identity check treated standard-time sites as wall-clock. Clocks are now looked
      up in a plain dict. It is the only such use in the code base.
    - **Assignment:** a mask assignment into a pandas Series was replaced by positional numpy
      assignment.

---

## D023 — Weather enrichment: ERA5 via Open-Meteo, derived humidity, checked alignment
- **Date:** 2026-10-24 · **Task:** T007d · **Status:** Accepted
- **Decision:** `wattwise.data.era5` builds a separate weather-enrichment table, keyed by
  (site, UTC hour).
  - **Kept apart from observed data.** It is never merged into the canonical *observed* weather
    table: the contract defines that table as observations, and ERA5 is modelled.
  - **Source:** the Open-Meteo historical archive. The free tier is allowed because WattWise is
    non-commercial (D022).
    - The model is pinned to `models=era5`. The default blend adds a model from 2017 onwards.
    - Output is in UTC, with a day of margin around the BDG2 years.
  - **Provenance in the column names:** `_era5` marks modelled grid-cell values; `_derived`
    marks humidity computed from BDG2's observations. Nothing is gap-filled across sources.
  - **Time convention:**
    - Radiation is the mean over the hour that ends at its label, so it is relabelled to the
      start of that hour, as readings are (D012).
    - Instantaneous values (cloud cover) keep their time.
  - **Falsifiable alignment checks:** `prepare` writes nothing unless every site passes, over
    the whole period and in every calendar quarter with enough data:
    - **Solar noon:** the median radiation-weighted centre of the solar days is within
      **30 minutes** of solar noon (NOAA equation of time; days grouped in local mean solar
      time). 30 minutes is half of the one-hour error being caught.
    - **Temperature phase:** the phase of ERA5 temperature against BDG2's observed temperature
      is interpolated to fractions of an hour (a parabola through the correlation peak). Each
      quarter must lie within **0.5 h** of the site's median, and the median within **0.75 h**
      of zero. 0.75 h is halfway between the largest natural phase seen (0.5 h) and a one-hour
      error at a site whose natural phase is 0. It was tightened from 1 h, at which such an error
      sat exactly on the limit (review finding).
    - **Why it changed after review:** the first version used one whole-period median, a 15-minute
      tolerance and a whole-hour lag that had to be 0. The review reproduced a one-hour mislabel
      over a third of the period that still passed. Quarterly checks then showed two things:
      convective summers bias quarterly medians by up to 16 minutes, and some stations sit half
      an hour from the ERA5 cell, where whole-hour lags tie.
  - **Humidity:**
    - The Magnus formula over water, with the Alduchov & Eskridge (1996) coefficients 17.625
      and 243.04 °C.
    - A dew point ≤ 0.5 °C above the temperature is treated as rounding and capped at 100%; a
      larger excess is left missing as a data error.
  - **Reproducibility:**
    - Each response is saved with its file SHA-256 and a content hash. The content hash
      excludes the server's `generationtime_ms`, so re-fetches can be compared.
    - A second `fetch` only verifies; `--force` re-fetches and reports "changed" (keeping the
      previous hash) if the same request returns different content.
    - The manifest is saved after every site, so a failure part-way loses nothing.
    - A response recorded for a different request is refused.
  - **The manifest stays git-ignored** with the responses (`data/raw/era5/manifest.json`),
    because its URLs contain BDG2 site coordinates (D014).
- **Evidence (2026-10-24, 15 sites, 8 quarters each, none failed):**
  - Solar-noon per-site medians were −8.6 to +2.0 minutes, against +51 to +62 if the labels
    were taken as interval starts.
  - Temperature phase site medians were −0.50 to +0.30 h, with quarters within 0.33 h of their
    site's median. This also independently confirms the D016 weather clocks.
  - A forced re-fetch returned identical content for all 15 sites.
- **Alternatives considered:**
  - **The Copernicus CDS directly:** not needed for non-commercial use. It remains the fallback
    if the project becomes commercial.
  - **NASA POWER:** too coarse for radiation (1°).
  - **ERA5-Land:** returned no radiation.
  - **Filling BDG2's missing weather from ERA5:** rejected, because it would mix observed and
    modelled values in one column.
  - **Computing humidity in feature engineering (T013):** rejected. Deriving it once, with its
    rules recorded, keeps T013 simple and the provenance explicit.
- **Consequences:**
  - T013 can join radiation, cloud cover and humidity by (site, hour) for 15 sites, and humidity
    for all 19.
  - The 4 sites without coordinates have no radiation, and models must handle that explicitly.
  - **Known limit:** at a site whose natural phase is near ±0.5 h, a whole-period one-hour error
    in BDG2's weather clock would pass the temperature rule. The D016 audit covers that case.

---

## D024 — Baselines: seasonal-naive and local hour-of-week profile
- **Date:** 2026-10-24 · **Task:** T012 · **Status:** Accepted
- **Decision:** `wattwise.ml.baselines`.
  - **`seasonal-naive-1w`:** the reading 168 h earlier, a one-week-ahead forecast. It may use
    validation- or test-window readings that are a full week in the past, which is legitimate
    at a one-week horizon, and never the hour itself or later.
  - **`hour-of-week-median`:**
    - The median per meter and hour of the week, from **training rows only**.
    - Hours of the week are in the building's **local wall time**, because occupancy schedules
      follow the wall clock. A UTC profile is an hour off for half the year (tested).
    - The fallback is the meter's training median.
  - **Protocol:** `fit(train)` then `predict(rows, history)`. The target rows reach `predict`
    without their values.
  - **Evaluation:** with the T011 harness on validation and test. Results are also given on
    the **common rows** both baselines predict, so a coverage difference cannot decide the
    comparison.
  - **Default split:** chronological; train 2016-01-01 to 2017-07-01, validation to
    2017-10-01, test to 2018-01-02. No holdout: per-meter baselines cannot forecast unseen
    buildings.
- **Result (BDG2 sample):** test MAE 8.763 kWh, WAPE 8.6% (seasonal), against 10.888 kWh and
  10.7% (profile). **The seasonal-naive baseline is the bar to beat.**
- **Alternatives considered:**
  - **A UTC hour-of-week profile:** rejected; it shifts by an hour across daylight saving.
  - **A mean instead of a median:** rejected; the median resists outliers, and spikes remain
    in "cleaned" data.
  - **Fitting on train plus validation before testing:** deferred to model selection (T014),
    so that baselines and models are compared under the same rule.
- **Consequences:**
  - T014 must beat seasonal-naive on the same split and rows to be adopted.
  - The evaluation dirty flag now also counts new, uncommitted files, so a run with new code is
    not reported as clean. Before this, only changes to tracked files counted.

## D025 — Feature set 1: leakage rules, explicit missing values, computed sun position
- **Date:** 2026-10-24 · **Task:** T013 · **Status:** Accepted
- **Decision:** `wattwise.ml.features` builds 32 versioned features in five groups (calendar,
  holiday, weather, sun, history). The full list is in [FEATURES.md](FEATURES.md).
  - **Conditions** may describe the target interval or earlier, never a later one. Observed
    weather at the target hour is allowed, because WattWise models expected consumption under
    the conditions that occurred. Results with weather features are therefore
    expected-consumption accuracy, not forecast accuracy.
  - **History** uses only readings that started at least H hours (1–168, default 168) before
    the target. Lags and the four-week mean are fixed at one week or more; rolling windows end
    H before the target.
  - **Nothing is fitted.** Missing values stay NaN, and flags record availability. Imputation
    and scaling are fitted on training rows by the model (T014). That makes it safe to compute
    features once on the whole table and then select split rows.
  - **Holidays** come only from a known region: `holidays` 0.106, observed days included.
    Unknown regions give NaN.
  - **Sun position** uses NOAA's equations in `wattwise.data.solar` (moved there from the ERA5
    module). They were cross-checked against pvlib 0.16.1: within 0.53° of elevation and
    5.2 min of day length over 2016–2017 at six points.
  - **Version:** `FEATURE_SET_VERSION = "1"`. Changing a feature's meaning, or adding or
    removing one, needs a new version. A test keeps FEATURES.md in sync with the code.
- **Alternatives considered:**
  - **pvlib for sun position (planned in T007b):** rejected for now. It would add pvlib, scipy
    and h5py to the runtime for an accuracy hourly features do not need. It remains the
    reference for checks, and clear-sky radiation can justify it later.
  - **Imputing missing weather here:** rejected. An imputer must be fitted on training data, so
    it belongs to the model, which knows the split.
  - **Lagged-only weather, a true forecast setting:** rejected for the expected-consumption
    baseline. It would hide the conditions the baseline must account for. A forecasting product
    would need forecast weather instead.
  - **A balance point fitted per building:** deferred. 18 °C is a stated convention, and tree
    models do not need one.
- **Consequences:**
  - T014 trains on these features and must report which groups it used.
  - Feature set 1 supports hourly data only; other intervals are refused.
  - The `holidays` dependency needs `python-dateutil<3`. The lock moved python-dateutil from
    3.0.0 (released 2026-10-21, under the two-week rule) back to 2.9.0.post0.
  - Unseen-building evaluation: a held-out building's history features use its own readings
    from before the test window. That is legitimate at forecast time. A strict cold-start claim
    must drop the `history` group.

## D026 — Adopt LightGBM (full features) for seen buildings; seasonal-naive stays elsewhere
- **Date:** 2026-10-24 · **Task:** T014 · **Status:** Accepted
- **Decision:** `wattwise.ml.models` (results in [EVALUATION.md](EVALUATION.md#models-t014)).
  - **Model for seen buildings:** LightGBM, full features, 200 trees, learning rate 0.05, 31
    leaves, at least 50 rows per leaf, seed 0, deterministic single-threaded training. The
    target is the reading divided by the meter's mean over the week ending 168 h before.
  - **Evidence:** it was the validation winner among 16 trials (3 families × 2 variants × small
    grids). On the test quarter it reduces MAE by 14.6% against seasonal-naive on the 43,000
    rows both predict (7.486 against 8.764 kWh), and it is better on 17 of 20 meters.
  - **Unseen buildings:** seasonal-naive stays the default. The best full model ties it on a
    building holdout (+0.1%) and loses on a site holdout (−14.4%).
  - **Rule applied:** settings and the winner are chosen on validation only; test is scored
    once for the chosen settings; adoption needs a lower MAE on common rows.
  - **Libraries:** scikit-learn 1.9.1 (BSD-3-Clause) and LightGBM 4.7.0 (MIT), both at least
    two weeks old. scikit-learn ships no type information, so mypy treats it as untyped.
- **Alternatives considered:**
  - **No-history ("conditions") models,** which cannot absorb a sustained anomaly: rejected for
    now. They were 15–37% worse than seasonal-naive on test.
  - **Meter identity as a feature:** rejected. It cannot serve unseen buildings, and the full
    model's scaling already carries each meter's level.
  - **Refitting on train plus validation before testing:** not done, so models and baselines
    follow the same rule (D024). The production fit is T015's decision.
  - **Larger grids or early stopping:** deferred. The small grids were flat (ridge: identical
    to 3 decimals; boosting: 200 vs 500 trees within 0.5%), and more searching on one
    validation quarter risks overfitting it.
- **Consequences:**
  - T015 packages this model with its feature set version, scale rule and settings.
  - T016 must account for history absorbing sustained anomalies after a week (D025).
  - Results are expected-consumption accuracy with observed weather, not forecast accuracy.

## D027 — Model artifacts: no pickle, hash-verified, atomic promotion
- **Date:** 2026-10-25 · **Task:** T015 · **Status:** Accepted
- **Decision:** `wattwise.ml.registry` ([MODELS.md](MODELS.md)).
  - **Format:** LightGBM's text model, a JSON state file and JSON metadata. Nothing is pickled,
    so loading an artifact cannot run code from it.
  - **Checks on load:** SHA-256 of every file, strict metadata, artifact and feature-set
    versions, the feature table's columns, and the version name.
  - **Versions:** `<created_at UTC>-<model hash>`, never overwritten. `CURRENT` names the
    promoted one, replaced by an atomic rename after verification. Older versions stay for
    rollback.
  - **What is saved:** exactly the evaluated model (fitted on the split's training rows), so
    the recorded metrics are out-of-sample, and `evaluate` must reproduce them exactly.
  - **No model:** `NoModelError`, for the API to report "no model available".
- **Alternatives considered:**
  - **joblib or pickle:** rejected; loading would execute code from the file, and an API should
    not trust the artifact folder that much.
  - **skops (safer scikit-learn persistence):** not needed; the adopted model is LightGBM. It
    can be revisited if a scikit-learn model is ever adopted.
  - **Refitting on all data before saving:** rejected for now. The refit would have no
    out-of-sample metrics. A production refit can be added later with its own evaluation
    window.
  - **A symlink for the current version:** rejected; symlinks need privileges on Windows. A
    pointer file replaced atomically works everywhere.
- **Consequences:**
  - The API (T024) loads with `load(features)`, and must handle `NoModelError`.
  - A feature-set change needs new artifacts: old ones are refused, not misread.
  - `baselines.utc_argument` is public, so the registry command shares its date parsing.

## D028 — Residual detector: robust out-of-sample scores, hysteresis, pre-event reference
- **Date:** 2026-10-25 · **Task:** T016 · **Status:** Accepted
- **Decision:** `wattwise.ml.detection` ([DETECTION.md](DETECTION.md)).
  - **Score:** the residual minus the meter's median, over 1.4826 × MAD. Both come from a
    window the model did not train on (its validation quarter), with a floor of 1% of the
    mean absolute reading. Detection runs only after that window.
  - **Events:** high and low separately. Open at z ≥ 4, continue at z ≥ 2, bridge gaps of up
    to 2 hours, keep with 3 or more flagged hours or one z ≥ 8. These are provisional, untuned
    defaults.
  - **Long events:** after 168 hours, score against the meter's reading from the last week
    before the event, with its own calibration. The model's history features would otherwise
    absorb the anomaly (D025, D026).
  - **Language:** events are anomalies to investigate; residual sums are not verified excess.
- **Alternatives considered:**
  - **Standard deviation instead of MAD:** rejected; anomalies in the calibration window would
    inflate it.
  - **Calibrating on training residuals:** rejected; they are in-sample and too small.
  - **Masking event hours and rebuilding history features:** rejected. The model needs a usable
    weekly scale (D026): 84 readings in the week ending 168 hours earlier. So with the event
    masked, predictions stop about 251 hours (10 days) into it, and the lags are blank from
    168 hours on.
  - **Switching to a no-history model during events:** rejected; those models lose clearly to
    seasonal-naive (D026).
  - **Tuning thresholds on the BDG2 test quarter:** rejected; that would fit the detector to
    its own evaluation. T018 tunes them on injected anomalies.
- **Result:** 355 events (11.9% of scored hours) on 20 meters in Oct–Dec 2017. 3.0% of
  calibration hours and 7.2% of detection hours have |z| ≥ 4: heavy tails plus seasonal drift.
  The event list is a review list, not an operator feed, until T018 and T019.
- **Consequences:**
  - T017 classifies these events into signatures, including data faults.
  - T018 must tune thresholds and measure false alarms. For LEAD labels (2016) it needs a model
    trained outside 2016.
  - T019 should consider seasonal or rolling calibration.

## D029 — Signature rules: meter problems first, evidence with every label
- **Date:** 2026-10-25 · **Task:** T017 · **Status:** Accepted
- **Decision:** `wattwise.ml.signatures`, run by the detection command
  ([DETECTION.md](DETECTION.md#signatures-t017)).
  - **Rules:** six transparent rules on each event's hours exactly as the detector saw them
    (reading, baseline used, score): `data_fault`, `flatline`, `spike`, `overnight_excess`,
    `drift` and `sustained`. Anything else is `unclassified`.
  - **Primary signature:** the first match in that order, so a meter problem is never
    presented as consumption. All matches and every rule's measurements are kept as JSON
    evidence.
  - **Shared thresholds:** flatline and zero-run lengths come from the data-quality engine
    (T008). Night hours are local wall-clock 22:00–05:59 in the building's zone.
  - **Wording:** descriptions name patterns, not causes, and a test checks them for causal
    words.
- **Alternatives considered:**
  - **A learned classifier:** rejected. There are no pattern labels to train on, and rules can
    be checked by hand.
  - **One label per event without evidence:** rejected; an operator could not see why.
  - **Adding patterns until nothing is unclassified:** rejected. 65% of real events are
    unclassified, mostly 4–23 hours long; forcing them into a pattern would invent structure.
- **Result (BDG2 sample, test quarter):**
  - 16 of 355 events (854 hours) are meter problems: 4 `data_fault`, 12 `flatline`.
  - Gator's whole-day "lows" are days where the raw source holds one value for every hour
    (80 or 200 kWh divided by 24). That was first read as possible holidays in T016, and is
    corrected here.
- **Consequences:**
  - T018 measures recall per signature with injected patterns.
  - Flatline days in BDG2 suggest masking such days from training and calibration later.
  - T020 builds explanations on the evidence.

## D030 — Injected-anomaly benchmark: the rolling same-hour z-score is the default alert source
- **Date:** 2026-10-25 · **Task:** T018 · **Status:** Accepted; the default switch awaits the
  owner's confirmation
- **Decision:** `wattwise.ml.benchmark` (results in
  [EVALUATION.md](EVALUATION.md#detector-benchmark-t018)).
  - **Benchmark:** seven anomaly patterns are injected into real BDG2 readings, one per meter per
    replicate. The features are rebuilt, so the model's history sees each injection. It is
    labelled a **synthetic benchmark**, and alerts outside injections are an upper bound on
    false alerts.
  - **Windows:** calibration on the model's validation quarter; tuning on October 2017
    (240 injections); evaluation once on Nov–Dec 2017 (240 fresh injections).
  - **Baseline detector:** the rolling same-hour z-score (14 previous days), with the same
    event rules and signatures as the model detector.
  - **Result:**
    - The model detector found more of every pattern: 81% mean recall against 72%. But its
      alert rate doubled out of sample: 0.50 in tuning, 0.97 in evaluation, against a budget of
      0.5. The rolling score stayed at 0.18 and 0.39.
    - At alert rates both detectors reach in tuning, the rolling score had the higher recall
      (75% against 52% at up to 0.3).
  - **Applied:** the detection command's default becomes `rolling-z` (open 4, continue 2,
    3 hours). `--detector model` uses the tuned thresholds (open 4, continue 3, 6 hours). The
    model still provides expected consumption for impact estimates (T021).
- **The decision rule was corrected after the evaluation run, and is now stricter.**
  - **As first written:** higher evaluation recall, and within the budget in tuning. Under that
    rule the model detector would have been kept.
  - **The flaw:** that rule accepted a detector whose alert rate doubles out of sample, and it
    compared recall at unequal alert rates.
  - **Corrected rule:** the budget must also hold in evaluation. Both results are in the report.
- **Alternatives considered:**
  - **Keep the model detector, since its recall is higher:** rejected under the agreed acceptance
    rule ("kept only where it beats the simple baseline"). Its recall advantage costs 2.5 times
    the alerts.
  - **Tune the model detector further on the evaluation months:** rejected; that would fit the
    detector to its own evaluation.
  - **Isolation Forest:** optional in the roadmap and not done; the rolling score already sets
    a clear bar.
- **Limits and consequences:**
  - **The default does not know the weather.** On a strongly weather-driven synthetic load it
    misses a +60% two-day surge that the model detector finds exactly (tested). Buildings with
    strong weather dependence may need `--detector model`.
  - **T019 should test** the model's residuals with a rolling, season-adaptive scale, and
    re-run this benchmark. That could combine weather-awareness with a stable alert rate.
  - **Weak patterns for both detectors:** flatlines (about 40% recall), drift labelling (0–3%)
    and overnight coverage (about 27%).
  - **Detection output on the BDG2 test quarter:** 100 events (2.1% of scored hours), against
    355 in T016.
  - **Human labels:** LEAD scoring moved to T018b.
  - **Owner decision:** the alert budget (0.5 per meter-week) is an assumption, and the owner
    can change it.

## D031 — LEAD human-label check: a chronological model, trusted labels only, reported apart
- **Date:** 2026-10-25 · **Task:** T018b · **Status:** Accepted
- **Decision:** `wattwise.ml.lead_check` (results in
  [EVALUATION.md](EVALUATION.md#detector-check-against-lead-labels-t018b)).
  - **Readings:** BDG2's raw variant for LEAD's 173 meters. LEAD labelled raw readings, and
    cleaned readings may have removed what was labelled.
  - **A separate model:** trained January–May 2016, calibrated in June, detecting
    July–December. Testing the adopted model on 2016 would test it on its own training data.
  - **Trusted labels only:** those whose LEAD reading matches BDG2's raw reading (D022).
    Events touching only untrusted or unlabelled hours are unjudged, not counted as false.
  - **No tuning:** the detectors run with their T018 settings.
  - **Reported apart**, as "real data, human labels without measured agreement".
- **Alternatives considered:**
  - **Scoring the adopted model on 2016:** rejected; it is in-sample and would flatter it.
  - **Training on 2017 and detecting 2016:** rejected; the test window would be earlier than
    training, against the chronological rule.
  - **Tuning thresholds on LEAD:** rejected. Labels with unmeasured agreement should check a
    detector, not shape it. Tuning would also leave no independent check.
  - **Using the cleaned variant:** rejected, as above.
- **Result:**
  - **Rolling z-score:** hour precision 11.5% against a 1.5% chance rate; 18.9% of labelled
    segments found; event precision 22.7%.
  - **Model detector:** 4.5%, 21.2% and 7.1%. But this check's model forecasts worse than
    seasonal-naive (MAE 22.08 against 19.57), so it does not represent the adopted model.
  - 70% of labelled segments last 1–2 hours, which the persistence rules mostly ignore.
- **Consequences:**
  - The low agreement is a finding to keep in view, not a tuning target. Whether operators
    want 1–2-hour alerts is a product question.
  - It supports the T018 default (D030): the rolling score is the more precise detector here
    too.
  - The raw BDG2 variant (1,171 eligible meters, 20.5 million readings) is prepared locally
    and git-ignored.

## D032 — Prediction intervals: rolling relative conformal, reported with measured coverage
- **Date:** 2026-10-25 · **Task:** T019 · **Status:** Accepted
- **Decision:** `wattwise.ml.intervals` ([EVALUATION.md](EVALUATION.md#prediction-intervals-t019)).
  - **Default method: rolling.** The interval is predicted ± q × s, where:
    - s is the meter's mean over the week ending a week earlier (past-only)
    - q is the per-meter conformal quantile of |residual| / s, recomputed daily from the 28
      days ending 7 days before
  - **Wording:** intervals are presented with their **nominal level and measured coverage**,
    for example "nominal 90%, measured 86.7% on the BDG2 test quarter". They are never called
    calibrated, because no method met the ±2-point rule.
  - **Scores** come only from windows the model did not train on.
- **Evidence:**
  - **Coverage at nominal 90%:** 86.7% for rolling, against 85.8% (relative) and 83.3%
    (absolute).
  - **Width and score:** the narrowest intervals (33.0 kWh) and the best interval score.
  - **Per-meter evenness:** the worst meter covers 76% for rolling, against 45–56% for the
    others.
- **Alternatives considered:**
  - **Fixed per-meter intervals from the summer calibration quarter:** rejected. They
    under-cover in winter, unevenly across meters.
  - **A shorter lag or window:** not tried, so as not to tune on the test months. A shorter lag
    would react faster, but would let an anomaly widen its own interval sooner.
  - **Quantile regression or a second model for the scale:** deferred; this is the simplest
    method that adapts.
  - **Pooled quantiles across meters (for unseen buildings):** deferred. The model is not
    adopted for unseen buildings (D026).
- **Consequences:**
  - T021 uses rolling intervals for "potential excess above the upper bound". Every figure
    carries the nominal level and the measured coverage.
  - T019b scores the model detector with the same season-adaptive scale.
  - Intervals are about a third of the mean reading wide, so small excesses cannot be claimed.

## D033 — A season-adaptive model detector does not pass the benchmark; rolling-z stays
- **Date:** 2026-10-25 · **Task:** T019b · **Status:** Accepted
- **Decision:** add `model-adaptive` (`detection.adaptive_scores`) as an option, and keep the
  rolling z-score as the default alert source (results in
  [EVALUATION.md](EVALUATION.md#season-adaptive-model-detector-t019b)).
  - **Score:** the relative residual (actual − expected) / recent level, centred and scaled by
    its median and MAD over the meter's 28 days ending 7 days before each day. Only
    out-of-sample residuals are used.
  - **Benchmark:** the T018 procedure unchanged, with the D030 rule fixed before the run.
- **Result:**
  - **model-adaptive (open 5, continue 3, 3 h):** recall 69% at 0.71 alerts per meter-week in
    evaluation, against a budget of 0.5. It met the budget in tuning (0.49).
  - **Comparison:** rolling-z 72% at 0.39; static model 81% at 0.97.
  - **So:** the adaptive scale reduces the out-of-season alert growth (×1.45 against ×1.9), but
    not enough, and it costs recall.
- **Alternatives considered:**
  - **A shorter lag or window for the scale:** not tried. Choosing them on these results would
    tune on the evaluation months. A shorter lag also lets anomalies inflate the scale sooner.
  - **Combining detectors (alert when both agree, or the model ranks rolling-z alerts):**
    deferred. It is a new detector, and would need its own pre-stated rule.
  - **Dropping the model detectors:** rejected. They stay as options for strongly
    weather-driven buildings (D030) and for investigation.
- **Consequences:**
  - Alerts come from the rolling z-score. The model provides expected consumption, intervals
    (T019) and impact estimates (T021).
  - The shared helper `intervals.daily_window_statistics` serves both the rolling intervals and
    the adaptive scores.
  - Two pending owner decisions stay open: the default alert source, and the alert budget.

## D034 — Alert explanations: evidence bundles, LightGBM TreeSHAP, a wording guard
- **Date:** 2026-10-25 · **Task:** T020 · **Status:** Accepted
- **Decision:** `wattwise.ml.explanations` ([DETECTION.md](DETECTION.md#explanations-t020)).
  - **Bundle:** every event gets one, covering:
    - the detector's comparison
    - the model's expectation and rolling 90% interval, with that interval's measured coverage
      in the same window
    - whether the model agrees
    - persistence and the signature evidence
    - the top 5 influences
    - a check to make
  - **Influences:** `FeatureModel.contributions`, LightGBM's exact TreeSHAP (`pred_contrib`)
    scaled to kWh. They add up to the expected value before clipping (tested), and are
    labelled associations within the model, not causes.
  - **Wording guard:** a forbidden-phrase list covering causes, certainty and "waste". It is
    enforced by tests and by the command itself.
- **Alternatives considered:**
  - **The `shap` package:** not added. For LightGBM it computes the same TreeSHAP values, and
    it would pull in a large dependency tree (numba, llvmlite) for no gain. If a scikit-learn
    model is ever adopted, `shap` or permutation importance can be reconsidered.
  - **Explaining the anomaly by comparing conditions with a reference week:** deferred. It is
    useful, but it is a separate analysis with its own pitfalls (confounded conditions).
  - **Free-text generation:** rejected. Fixed templates can be checked; generated prose cannot.
- **Consequences:**
  - The API (T025) can serve the bundle as is.
  - The 20 events where the model disagrees with the rolling-z detector are flagged for
    operators, which partly offsets the default detector's weather blindness (D030).

## D035 — Full scale: a batched float32 store, a 24-hour flatline mask, category identifiers
- **Date:** 2026-10-25 · **Task:** T042 · **Status:** Accepted
- **Decision:** `wattwise.ml.scale` ([EVALUATION.md](EVALUATION.md#full-scale-t042)).
  - **Data:** all 1,148 eligible cleaned meters in `data/processed/bdg2/cleaned-all` (local,
    git-ignored), next to the 20-meter sample, which earlier results depend on.
  - **Feature store:** features built per 100 meters, stored as float32 parquet parts with
    SHA-256 checks and a feature-set version. The store holds features only.
  - **Quality mask (policy, computed when needed):** negative readings, zero runs of 24 hours
    or more, and identical non-zero runs of 24 hours or more. It applies to training targets
    and calibration only.
  - **Category identifiers** for full-scale runs.
- **Evidence:**
  - The store matches the in-memory features exactly on all 350,816 sample rows.
  - The mask drops 9.5% of readings. 91% of the identical-run readings were in runs of a day
    or more.
  - Category identifiers reproduced the 5.1-hour baseline run exactly, in 10 minutes.
- **Alternatives considered:**
  - **Masking from 6 hours (T008's flatline length):** rejected for training. On BDG2 many
    6–23-hour runs are steady loads on coarse meters, and the T017 signature still flags them
    as events.
  - **Storing the mask in the feature store:** rejected. A policy change would force a
    10-minute rebuild.
  - **float64 in memory:** rejected; about 5 GB for the features alone on a 15 GB machine.
  - **A larger machine or a cloud run:** not needed now. The full scale fits with batching and
    categories.
- **Consequences:**
  - T043 trains from the store, with the mask on training targets. The bar is seasonal-naive
    at full scale: test MAE 15.72 kWh, WAPE 10.8%.
  - Full-scale runs use about 5.5–6.1 GB at peak, so they should run one at a time on this
    machine.

## D036 — Best model at full scale: LightGBM, L1 loss, adopted and promoted

- **Date:** 2026-10-27 · **Task:** T043 · **Status:** Accepted
- **Decision:** `wattwise.ml.fullscale` ([EVALUATION.md](EVALUATION.md#best-model-at-full-scale-t043-d036)).
  - **Search grid:** LightGBM, L2, L1 and Huber losses, 63 and 255 leaves, early stopping on a
    validation fold, trained from a seeded 25% sample of quality-checked training hours (every
    row is used for validation and test). **L1 loss at 63 leaves is dropped from the grid**: a
    separate run showed it needing 46,970 s against 255 leaves' 3,477 s for a near-identical
    validation MAE (15.283 vs 15.306).
  - **Chosen: L1 loss, 255 leaves, 1,779 trees** (validation MAE 15.267, beating seasonal-naive
    by 19.0% on the rows both predict). The no-history variant scores 41.2% worse than
    seasonal-naive: history remains essential at scale.
  - **Adopted and promoted.** Test MAE 13.700 vs seasonal-naive 16.705 (+18.0%, 2,261,050 rows,
    scored once). The production refit (trained on train+validation, same tree count) scores
    13.660 (+18.2%) and is the saved, promoted artifact.
  - **Training runs sequentially, not concurrently.** Two attempts to train multiple models at
    once (2-4 threads each) were tried and reverted: on this machine's 15.3 GB RAM, each
    concurrent fit's own copy of the float32 input matrix caused memory thrashing, not CPU
    parallelism — one run had to be killed before it finished, and the other ran slower than
    sequential training at full thread count would have.
  - **LightGBM's inputs are float32, not float64.** The feature store is already float32;
    converting it to float64 before fitting (the previous behaviour) doubled memory with no
    accuracy benefit to a tree model.
- **Evidence:**
  - **The old D026 sample-trained model (20 meters) loses to seasonal-naive at full scale**
    (17.434 vs 16.705, −4.4%): it did not generalise beyond its training sample, which is
    exactly the problem this task exists to fix.
  - **13 of 15 sites improve by 13–28%**; the remaining two (Crow, Lamb) are a small sample or
    an effective tie, not a regression.
  - **Unseen buildings and sites beat seasonal-naive too**, reversing T014's sample-scale
    finding (a tie on a building holdout, a loss on a site holdout, D026): at full scale, seen
    +17.6–18.9%, unseen buildings +15.7%, unseen sites +8.5%.
  - Re-evaluating the promoted artifact from disk reproduces its recorded test metrics exactly
    (MAE 13.676, WAPE 8.8%, 2,283,087 scored rows), on the T011 report's own row accounting
    (every row the model scored, a different denominator from the seasonal-naive comparison
    above, which counts only rows both predicted).
- **Alternatives considered:**
  - **Training 2 models concurrently in threads** (both at 4 and at 2 workers): rejected after
    measurement — memory thrashing, not a speed-up, and a crash at the first attempt.
  - **A faster learning rate for L1 loss** to force convergence in fewer trees: tried first,
    reverted before adoption — it was an untested guess at the model's actual training
    behaviour, and the evidence-backed fix (drop the 63-leaf L1 point) was both simpler and
    already measured to work.
  - **Letting the machine sleep overnight uninterrupted:** the process survived it (resumed
    exactly where it left off, no data lost), but it added about 17 hours to the slowest
    trial's reported duration for no benefit; a future bounded run should keep the machine
    awake.
- **Consequences:**
  - The promoted model (`20261027T103133Z-ea3909799a6b`) replaces the D026 sample-trained
    model as the registry's current artifact.
  - T044 re-runs intervals, the detector benchmark, the LEAD check and explanations against
    this model at full scale.

## D037 — Reference tables: average US factors, the publisher's UK convention, Ontario left open

- **Date:** 2026-10-26 · **Task:** T021a · **Status:** Accepted
- **Decision:** `wattwise.data.reference` ([DATASETS.md](DATASETS.md#reference-tables-t021a)),
  backed by committed tables at `data/reference/carbon_factors.csv` and
  `data/reference/electricity_prices.csv`. Every row carries its source name, URL, retrieval
  date, licence and the SHA-256 of the file it was read from.
  - **US carbon factors are average (total output), not non-baseload.** eGRID publishes both;
    "total output" matches what a building's own consumption actually draws from, while
    "non-baseload" estimates the marginal effect of a small load change — a different question
    (resolves the open item from D035).
  - **UK factors use the publisher's own reporting-year convention**: DESNZ's "2016" factors
    are used for 2016, "2017" factors for 2017 — no year-shifting.
  - **Geography codes:** an eGRID subregion (`US-<CODE>`) for the US, found by point-in-polygon
    on the published eGRID subregion boundaries (ray casting against the KML polygons; verified
    against a hand-built square before trusting the result on real coordinates). ISO 3166-1
    alpha-2 for the UK and Ireland (`GB`, `IE`). The mapping from each BDG2 site to its
    geography lives in `wattwise.data.bdg2_sites.EGRID_SUBREGION`, alongside the existing
    `SITE_REGIONS`.
  - **Ontario carbon is deferred, not committed, for 2016/2017.** T007b cited a value (40 g
    CO2e/kWh for 2016, 20 "preliminary" for 2017) from "ECCC National Inventory Report
    1990–2017, Table A13-7" (docs/DATASETS.md). The only edition this task could independently
    download (the current 1990–2024 edition, "Annex 7") publishes Ontario's table with columns
    1990, 2005, 2010, 2015, 2019, 2020, ... — it skips 2016 and 2017 outright, so it cannot
    confirm T007b's figure. The older 1990–2017 edition was not found at a stable public URL
    this session (the official Open Government Portal record exposes only the current edition;
    older ECCC Data Mart folders render client-side and could not be listed). Rather than commit
    T007b's number without a checksum of its own source file, or interpolate between 2015 and
    2019 (not a sourced factor either), Ontario stays out of the committed table until the
    1990–2017 edition is located and hashed. T021a's scope already specifies no Ontario price
    source, so pricing is unaffected.
  - **A source with no edition for the requested year gets its nearest earlier vintage, labelled
    as such.** eGRID is published roughly every two years (there is no eGRID2017); `carbon_factor`
    returns the 2016 edition for a 2017 request with `vintage_year=2016` explicit in the result,
    rather than silently treating it as a fresh 2017 measurement.
- **Evidence:**
  - All 9 carbon-factor geographies and 10 price geographies load from the committed tables
    with 64-character lowercase-hex checksums recorded for every source file.
  - The 7 locatable US BDG2 sites (Bear, Bull, Cockatoo, Fox, Hog, Panther, Peacock) each land
    in exactly one eGRID subregion polygon; the lookup script is reproducible from the recorded
    source checksums.
- **Alternatives considered:**
  - **Non-baseload US factors:** rejected (see above).
  - **Interpolating Ontario's gap:** rejected; not a sourced number (CLAUDE.md's honesty rules).
  - **Point-in-polygon with a GIS library (shapely/geopandas):** rejected for a one-off, 7-point
    lookup; a plain ray-casting function against the already-downloaded KML avoided a new
    dependency.
- **Consequences:**
  - T021 (excess energy, cost and carbon estimates) can show kWh-only for Ontario sites and a
    priced/carbon estimate for the other 9 geographies, each traceable to its source.
  - Formalising an automated fetch-and-rebuild script (the tables were built once, by hand, from
    pinned source files in an isolated environment) is deferred; `openpyxl`/`xlrd` are not yet
    project dependencies.

## D038 — Excess, cost and carbon impact: priced per site, never mixed, always "potential"

- **Date:** 2026-10-27 · **Task:** T021 · **Status:** Accepted
- **Decision:** `wattwise.ml.impact` ([EVALUATION.md](EVALUATION.md#excess-energy-cost-and-carbon-impact-t021)).
  - **`potential_excess_kwh`:** kWh strictly above a T019 interval's upper bound, per row. A
    negative residual (at or below the bound) never counts; an unknown actual or bound gives
    `NaN`, not 0 — a missing bound is not zero excess.
  - **Always `ImpactStatus.POTENTIAL`.** `VERIFIED` exists in the enum for a future
    human-confirmed figure (T025's feedback loop); this module never sets it itself.
  - **`TariffConfig` is explicit and optional.** Without one, `estimate_impact` reports kWh
    only; a configured one must carry an ISO 4217 letter code and a positive rate.
  - **Carbon uses an already-resolved `CarbonFactor`**, not a geography/year pair, so the maths
    is testable without the committed reference tables; the caller resolves it via
    `wattwise.data.reference`.
  - **The command line prices every T020-detected event by its own BDG2 site**, not one factor
    for the whole run: a US and a UK site in the same run each get their own carbon factor.
    **Cost is only computed for one named `--geography` at a time** — summing cost across
    geographies would mix currencies into a meaningless total; carbon sums safely across
    geographies instead, since kg CO2e is a single, currency-free unit.
  - **Wired into T020's evidence bundles:** every bundle gets an `"impact"` section
    (`potential_excess_kwh`, hours, and cost/carbon if a tariff or factor is threaded through),
    and the rendered explanation names the figure when it is positive, worded as "potential
    excess ... not a verified figure" — never "waste", which stays in explanations.py's
    forbidden-word list.
- **Evidence (superseded by D040: these figures counted meter problems):** on the BDG2 test
  quarter (rolling z-score, 100 events): 5,766.7 kWh total
  potential excess, 2,459.2 kg CO2e across 7 configured geographies; 25 events at Eagle and
  Gator (no coordinates) correctly show "not configured" carbon, not zero or a guess.
- **Alternatives considered:**
  - **Summing cost across all geographies into one total:** rejected; mixes USD, GBP and EUR
    into a meaningless number.
  - **Resolving geography/year inside `estimate_impact` itself:** rejected; it would force
    every unit test of the maths to depend on the committed CSV tables.
  - **A `verified` status set automatically** (e.g. when a detector and the model agree):
    rejected — agreement is not human confirmation, and the project's own rule is that an
    anomaly is not confirmed waste regardless of how many signals agree.
- **Consequences:** T022 (alert prioritisation) and T032 (the frontend's cost-impact view) can
  read a `potential_excess_kwh`/`cost`/`carbon_kg` straight from each event's evidence bundle,
  already labelled "potential" and already resolved to the event's own site.

## D039 — The evaluation model: downstream tools calibrate on a model that did not train on the window

- **Date:** 2026-10-28 · **Task:** T044a · **Status:** Accepted
- **Decision:** the registry's promoted model is now the T043 chosen model **trained on the
  training window only** (`20261027T121334Z-eeec81e9592c`), not the production refit
  (`20261027T103133Z-ea3909799a6b`, kept in the registry).
  - **Why:** intervals and the model detector calibrate on the model's validation window. The
    refit has trained on it, so its residuals there are in-sample and would make every interval
    too tight. With the refit promoted, every downstream command failed with "no validation
    window" (a correct refusal).
  - **How:** `python -m wattwise.ml.fullscale --evaluation-model --promote` rebuilds the model
    with the study's settings, sample and tree count, and **promotes it only if it reproduces
    the study's recorded validation MAE exactly. It did: 15.267402**, with identical RMSE, bias,
    WAPE and row counts. Its training data ends 2017-06-30 23:00, before the validation window.
  - **Cost in accuracy:** test MAE 13.720 against the refit's 13.676 on the harness's rows
    (0.3%).
- **Also made possible at full scale:**
  - The downstream commands (`intervals`, `detection`, `explanations`, `impact`) read inputs
    from the T042 store with `--store`: readings, buildings and features for the model's windows
    (from 28 days before validation to the end of test). Features are the store's, computed on
    each meter's whole series, so nothing is recomputed from a window. A test checks this equals
    the in-memory path exactly.
  - The interval code was quadratic (meters x days x rows) and took hours at full scale; it is
    linear and **equals the original on test data** (checked against a kept copy of the old
    loop).
  - `explanations --no-influences` skips TreeSHAP (about 42 ms per event hour, hours at full
    scale), and `impact` uses it, since pricing needs the bounds, not the influences.
- **Open (for T024/T026/T027):** one `CURRENT` pointer cannot say both "the best predictor" (the
  refit) and "the model the calibrated tools use" (the evaluation model). Until the API tasks
  decide, `CURRENT` is the evaluation model, and the refit is addressed by its version.
- **Alternatives considered:**
  - **Calibrate on the refit's in-sample residuals:** rejected; intervals would be
    over-confident, in a way nothing in the report would show.
  - **Hold out a slice of the training window for calibration instead:** rejected for this task;
    it would change the model T043 evaluated.
  - **Keep the refit promoted and leave downstream tools broken:** rejected.

## D040 — Meter problems are not potential excess: a correction to T021 (D038)

- **Date:** 2026-10-27 · **Task:** T044a · **Status:** Accepted
- **Decision:** events whose primary signature is `data_fault` or `flatline`
  (`signatures.METER_PROBLEMS`) are **never counted** in potential excess, cost or carbon. Their
  kWh above the interval's upper bound is kept, apart, as `kwh_above_bound_not_counted`, and
  reported on its own line in the impact summary, so nothing is hidden and nothing is presented
  as consumption.
  - **Bundles:** `impact.potential_excess_kwh` is `None` (not 0) for such events, with
    `meter_problem: true`; the rendered explanation does not state a potential excess for them.
  - **`price_bundles`** reads the signature itself, so explanations written before this
    decision are priced the same way.
- **Why:** D029 says "a meter problem is never presented as consumption", and T021 (D038)
  broke it. On the 20-meter sample the effect was hidden by the small number of such events. At
  full scale, **462 of 5,546 events (8.3%) are meter problems, and in the first run they held
  425,193 kWh (42.4%) of the first total of 1,002,572 kWh.** Two single hours alone
  (Bull_education_Dottie and Bull_education_Delia, both `data_fault`) were about 54,000 kWh
  each. The effect differs by geography: 92% of GB's first figure was meter faults (121,227 kWh
  before, 9,293 after).
- **Corrected full-scale figures** (rolling z-score, BDG2 test quarter, 5,084 counted events,
  after this decision and D041): **558,722 kWh potential excess and 220,140 kg CO2e** (from
  1,002,572 kWh and 390,369 kg). Cost at the EIA Minnesota 2016 commercial rate for US-MROW:
  11,860.84 USD over 652 events. The 462 meter-problem events sit 308,410 kWh above their
  bounds, reported apart and not counted.
- **What this does not claim:** the remaining 577,379 kWh is still *potential*, not verified.
  The total is concentrated: the 10 largest counted events hold 17.5% of it, the largest 50
  hold 40.5% and the largest 200 hold 68.5%. Only 2,286 of the 5,084 counted events have any
  hour above the upper bound at all. A person should check the largest first (T022).
- **The sample-scale T021 figures (5,766.7 kWh, 2,459.2 kg CO2e) are superseded.** They counted
  meter problems, and used the D026 model. They are not re-derived; the full-scale run replaces
  them.
- **Alternatives considered:**
  - **Counting them and labelling them:** rejected. A total that includes meter faults is the
    number people read.
  - **Setting their excess to 0:** rejected. Zero reads as "nothing found"; `None` says "not
    applicable", and the real figure stays visible in its own field.
  - **Re-running the 4.5-hour full-scale explanations to regenerate the bundles:** rejected as
    unnecessary. The numbers are deterministic, and the signature is in every bundle.

## D041 — Intervals need a usable scale: a level that collapsed after an outage is not one

- **Date:** 2026-10-28 · **Task:** T044a · **Status:** Accepted
- **Decision:** in `wattwise.ml.intervals.usable_level`, a row's recent level is a usable scale
  only if it is at least **1% of the meter's own median level** in the calibration window
  (`SCALE_FLOOR_FRACTION`, the detectors' `scale_floor_fraction` from T016). Otherwise the level
  is NaN: the row gets **no interval, and no calibration score** ("unknown", never zero). The
  interval report and the explanations use the same rule, and both calibrate on quality rows
  only (D035, which T044a also made true for intervals and the model detector for the first
  time).
- **The defect (found at full scale; the sample never showed it):**
  - The level is the mean of the week ending a week earlier (past-only). After a week or more of
    zero readings (an outage), it is about 0 a week later, while consumption is back to
    normal: **a week of "echo" rows, with relative scores in the thousands.** The quality mask
    drops the zero readings but not the echo, because those readings are valid.
  - The echo rows were about a quarter of the next 28-day calibration windows, so the
    90th-percentile score q, and every interval around a normal 50 kWh/h meter, became
    plus or minus thousands of kWh for about five weeks. 31 of 1,017 meters had intervals wider
    than 500% of their mean reading, and 4 wider than 100,000%. The mean width of rolling 90%
    intervals was 819 kWh against a median of 32.
  - The echo rows themselves got collapsed intervals (q times a level of 0.02), so all their
    normal consumption would count as "above the upper bound".
- **Measured on the two clearest real meters before changing anything** (Bear_education_Wade,
  Lamb_office_Bertha): mean width 109,459 and 123,430 kWh before; 82 and 108 after; medians
  unchanged (41 to 40 and 38 to 30). Only about 3.7% of their rows sit on the ramp between the
  floor and normal, too few to inflate a 90th percentile, so no second parameter was needed.
- **Full-scale effect** (rolling, nominal 90%): mean width 819.5 to **76.4 kWh**, interval score
  867 to **122.8**, coverage 87.1% to **87.2%**. 148,892 rows in the window have no usable scale
  and now get no interval; 3,222 more test rows are without an interval than before (0.15%).
  Impact: the potential-excess total falls a further 3% (577,379 to 558,722 kWh) because the
  collapsed intervals no longer count normal consumption.
- **How the 1% was chosen:** it is the project's existing scale-floor constant, justified by the
  diagnosis (echo levels were 0.02-0.07 kWh against medians of 30-60, three orders of magnitude
  below), not by any coverage result. The meter's median is taken from the calibration window,
  so no test information is used.
- **D032 re-checked under the same criteria at full scale: rolling stays the default.**

  | At nominal 90% | Rolling | Relative | Absolute |
  |---|---|---|---|
  | Coverage (test) | **87.2%** | 87.0% | 86.0% |
  | Median width (kWh) | **31.8** | 32.8 | 32.4 |
  | Interval score (mean) | **122.8** | 2,829.7 | 123.1 |
  | Worst meter's coverage | **58.2%** | 28.2% | 25.5% |
  | Meters within 2 points of nominal | **367 of 1,017** | 240 of 991 | 209 of 991 |

  Still **not calibrated** (November, the first winter month, covers 84.5%), as in T019.
- **Remaining, stated plainly:** a few meters still have very wide intervals (the worst is 468
  times its mean reading, from a cause other than an echo week that this task did not find),
  so a mean width is not a typical one; the report now shows the median and the spread.
- **Not changed:** the model itself predicts about 0 kWh in an echo week, because its own level
  feature has collapsed. That is a model limitation (its `MIN_SCALE` is 0.01 kWh). It is in the
  test metrics already, and is a candidate for a later model task.
- **Alternatives considered:**
  - **No floor, dropping the nadir by hand:** rejected, not principled.
  - **A level that ignores masked hours:** it would change a model feature, which means a
    retrain. Rejected for this task.
  - **A higher floor (10%, 50%):** unnecessary on the measured meters, and a larger parameter
    to defend.

## D042 — The benchmark at full scale: the rule is unchanged, so is its answer

- **Date:** 2026-10-28 · **Task:** T044b · **Status:** Accepted
- **Decision:** the T018 injected-anomaly benchmark runs at full scale under **the same
  pre-stated rule** (D030, the tightened version): keep a model-based detector only if, with both
  tuned to the same alert budget, its mean recall on the evaluation window is higher than the
  rolling z-score's, and it stays within the budget in tuning and in evaluation. **Neither model
  detector passes, so the rolling z-score stays the default alert source** (and D033 stands).
- **How it runs at full scale (the procedure is unchanged; these are equivalences):**
  - **Injection** indexes each meter's rows once, instead of comparing every row to every
    injection (about 6 billion string comparisons at this size). Equal to the original on all
    seven patterns (a test keeps the original as a reference).
  - **Features** are rebuilt each replicate only for the rows the detectors use plus 10 weeks of
    history (features look back at most 4 weeks), not for 20 million rows. Equal to the features
    on the whole series (tested), and the model's history still sees the injection.
  - **Inputs** come from the T042 store (`--store`), as for the other downstream commands.
  - **One replicate per phase** (`--replicates 1`): each replicate injects one anomaly per meter,
    so it already gives 1,133 injections to tune on and 1,133 to evaluate on, 4.7 times the
    sample's 240 each (12 replicates of 20 meters). With about 1,100 injections the standard error
    of a mean recall is about 1.4 points.
- **Evidence:** rolling z-score 70.0% recall at 0.341 alerts per meter-week; model 62.1% at 0.827;
  season-adaptive model 70.0% at 0.735; budget 0.5. The season-adaptive model would have passed
  the first rule (budget in tuning only), which is why D030 tightened it.
- **A sample-scale finding reverses:** the model detector's recall advantage (81% against 72%) is
  gone (62% against 70% at the same budget). The reason was not investigated.
- **Alternatives considered:**
  - **More replicates:** 12 replicates would take hours at full scale for a precision the
    decision does not need: the gap between the model and the rolling z-score is about 7.9
    points, several standard errors.
  - **Changing the rule or the budget after seeing the results:** rejected; the rule was fixed
    before the run, and the budget is a product assumption the owner can change.
- **Consequences:** nothing changes for users. The model keeps its other jobs: expected
  consumption, intervals, impact and explanations.

## D043 — The LEAD check at full scale: a better model detector, the same conclusion
- **Date:** 2026-10-28 · **Task:** T044c · **Status:** Accepted
- **Decision:** `lead_check --scale-from fullscale.json` trains the check's model at full scale:
  the T043 chosen settings, a seeded 25% sample of the quality-checked January-May 2016 readings
  of every raw meter, early stopping on June, then scores it on the labelled meters. The
  procedure otherwise follows D031 (raw readings, trusted labels only, no tuning, reported
  apart). The default run (labelled meters, small model) is kept for comparison.
- **Evidence:** the full-scale model forecasts better than seasonal-naive on the labelled meters
  (MAE 17.35 against 19.72; the labelled-meters model was worse, 21.20). As a detector it
  finds more labelled segments than the rolling z-score (29.6% against 18.9%) and is less
  precise (event precision 9.3% against 22.7%, 3.4 times the events). It improves on the
  labelled-meters model on every precision and recall measure.
- **No default changes.** The rolling z-score stays the alert source (D030, D033). D030's
  rule is the injected-anomaly benchmark; a check against one annotator's labels is not a
  tuning target (D031).
- **Alternatives considered:**
  - **Choosing the detector by this check:** rejected; with one annotator, agreement
    unmeasured and partial labels, it should check a detector, not select it.
  - **Training only on the 173 labelled meters:** kept as a comparison only; the full-scale
    model is the one that matches the adopted one's recipe.
- **Caveats:** the model-based numbers differ from D031 (3.8% against 4.5% hour precision for
  the same labelled-meters setup); the cause was not isolated (pipeline changes since T018b are
  the hypothesis). Early stopping picked 76 trees on one month.
- **Consequences:** M5b's T044 is complete; the full-scale results replace the sample-scale
  ones wherever they are quoted. Whether to offer the model detector as a more sensitive,
  noisier second alert source is a product question for the owner.

## D044 — Alert prioritisation: a transparent weighted score, impact first, no cost in the score
- **Date:** 2026-10-28 · **Task:** T022 · **Status:** Accepted
- **Decision:** `wattwise.ml.prioritisation` ([EVALUATION.md](EVALUATION.md#alert-prioritisation-t022-d044)).
  Score = 100 x (0.4 impact + 0.2 persistence + 0.2 severity + 0.2 confidence), components in
  [0, 1] on a logarithmic scale up to a cap, with deterministic tie-breaking (rounded score,
  potential excess, flagged hours, start, meter id, end).
  - **Impact comes first** (the largest weight): the task is to rank by likely business impact, not
    by anomaly score alone. It is the *potential* excess of T021 (D038), never verified.
  - **Meter problems and below-expected alerts have no impact component** (D029, D040): they are
    not excess consumption. They are marked by `kind` and still rank on the other components.
  - **Cost and carbon are not in the score:** a tariff is optional and per geography.
  - **Weights and caps are product assumptions**, set from the range of real alerts (impact cap
    just above the largest seen; persistence and severity caps at the 99th and 98th
    percentiles), not
    fitted to labels or tuned to an outcome. They are a configuration (`PriorityConfig`).
- **Alternatives considered:**
  - **Ranking by potential excess alone:** simple, but a large excess from a short, uncorroborated
    event would outrank a long, sharp one. The score gives up about seven points of the excess held
    by the top 200 (68.5% to 61.2%) for that.
  - **A learned ranking:** rejected; there are no outcome labels until T025, and a learned score
    would be harder to explain.
  - **A linear scale:** rejected; real peak scores reach 15 million.
  - **Batch-relative scores (ranks or percentiles):** rejected; a score that changes when other
    alerts arrive is hard to show or store.
- **Consequences:** T025 can store the score with each alert; T031 can sort the queue by it. The
  weights can be revisited once reviewers' feedback exists; until then the score makes no claim
  about which alerts are real.

## D045 — Database foundation: SQLAlchemy 2 and Alembic on PostgreSQL 18, readiness that checks the schema
- **Date:** 2026-10-28 · **Task:** T023 · **Status:** Accepted
- **Decision:** ([DATABASE.md](DATABASE.md))
  - **Stack:** SQLAlchemy 2.0 (typed models), Alembic, psycopg 3. Locked releases are at least two
    weeks old: SQLAlchemy 2.0.54 and Alembic 1.20.0 (newer releases existed but were younger),
    psycopg 3.3.6.
  - **Scope of the baseline:** `buildings` and `meters` only, the contract's entities, with the
    contract's rules as constraints (positive area, coordinate ranges, the meter-type vocabulary,
    one canonical unit per type). Readings stay in Parquet (revised by D046: the API now
    stores the readings it serves). Alert, feedback and run tables arrive
    with T025 and T027, so no table exists before its use is known.
  - **Migrations live inside the package** (`wattwise/db/migrations`), so a built image carries
    them and the API can compare the database with the head revision. Written by hand; a test
    fails if the models and the migrated schema differ.
  - **Configuration:** `WATTWISE_DATABASE_URL` is a `SecretStr`, accepted only for
    `postgresql+psycopg://`, and never echoed in errors, `repr`, responses or logs. There is no URL in
    `alembic.ini`.
  - **Readiness** (`GET /api/v1/ready`) is 200 only if the database is configured, reachable
    **and** at the head revision; otherwise 503 with one of `not_configured`, `unreachable` or
    `schema_outdated`. A database that answers but was never migrated is not ready.
  - **Test strategy** (the open decision): a real PostgreSQL, a fresh schema per test inside
    `WATTWISE_TEST_DATABASE_URL`'s database, dropped afterwards. Locally the tests skip without
    the variable; in CI a missing variable fails. CI runs a `postgres:18` service container pinned by
    digest.
- **Alternatives considered:**
  - **SQLite for tests:** rejected; it does not enforce the same constraints or foreign keys by
    default, and the migrations are PostgreSQL.
  - **A database per test (or per session):** needs a `CREATEDB` right and is slower; a schema per
    test isolates just as well.
  - **Migrations outside the package (`backend/alembic/`):** simpler layout, but the image and the
    readiness check would need a second copy of the files.
  - **Readiness as "can connect":** reports ready for a database the API cannot use.
  - **Autogenerated baseline:** rejected; hand-written, then checked against the models.
- **Consequences:** T024 and T025 add tables as migrations. The local role and databases are
  created once with a superuser (one SQL snippet, DATABASE.md): the project does not hold the superuser
  credentials.

## D046 — Read APIs: readings in PostgreSQL, every dataset labelled, UTC, bounded pages
- **Date:** 2026-10-28 · **Task:** T024 · **Status:** Accepted
- **Decision:** ([DATABASE.md](DATABASE.md), backend README)
  - **Readings are stored in PostgreSQL** (`readings`, primary key (`meter_id`, `timestamp`)), loaded
    by `python -m wattwise.db.load` from contract-validated tables with `COPY`. This revises D045's
    "readings stay in Parquet" for what the API serves; the ML pipeline still reads Parquet.
  - **Every building belongs to a `dataset` whose `kind` is `synthetic` or `observed`**, and every
    building, meter, series and summary response carries it (`data_kind`). Synthetic data can never
    be served unlabelled.
  - **Time is UTC end to end:** sessions run in UTC, and the response schemas convert every
    timestamp to UTC. Timestamps in requests must carry an offset (422 otherwise).
  - **Endpoints:** `GET /buildings`, `/buildings/{id}`, `/meters`, `/meters/{id}`,
    `/meters/{id}/series`, `/dashboard/summary`. Lists are pages (`items`, `total`, `limit`,
    `offset`; limit 1-200, default 50) ordered by identifier. A series is the readings in
    [`start`, `end`), at most `limit` points (default 10,000, at most 50,000), with `truncated` when
    more exist. Missing readings are `null`.
  - **Errors:** 404 for an unknown building or meter; 422 for bad pagination, an unknown meter type,
    a timestamp without an offset or `start` not before `end`; 503 `not_configured` without a
    database and 503 `unreachable` if it is lost, never with connection details.
  - **The summary reports only what is stored:** counts per dataset and overall, meters by type,
    missing values and the time range. No alerts, savings or costs.
- **Alternatives considered:**
  - **Serving series from Parquet files:** no new table, but a second data path beside the
    database, file paths in the API, and no transactions; rejected.
  - **A `data_kind` column on buildings instead of a datasets table:** loses the dataset's name and
    provenance, and a reload could not replace a dataset as a whole.
  - **Cursor pagination:** better for very deep pages; offsets are enough for buildings and
    meters, and series are bounded by time instead.
  - **Silently capping a series:** rejected; `truncated` says when there is more.
- **Found by running it:** the local server's session time zone is Asia/Kolkata, and the first
  version returned `+05:30` timestamps; CI's container is UTC, so the tests had not seen it. Both
  fixes above came from that, and the tests now use a non-UTC session.
- **Consequences:** T025 adds alerts as another table under a dataset. The frontend (T029, T030)
  can show the synthetic/observed label from every response.

## D047 — Alerts and feedback: the spec's four labels, an append-only history, nothing retrained
- **Date:** 2026-10-29 · **Task:** T025 · **Status:** Accepted
- **Decision:** ([DATABASE.md](DATABASE.md), backend README)
  - **The feedback label set (open since D001):** the product spec's four labels,
    `confirmed_waste`, `expected_behaviour`, `sensor_or_data_fault` and `needs_investigation`. They
    refine the master instructions' three without losing anything:

    | Master instructions | Spec labels |
    |---|---|
    | useful | `confirmed_waste`, `sensor_or_data_fault` (the alert found something real) |
    | incorrect | `expected_behaviour` |
    | needs investigation | `needs_investigation` |

    A `confirmed_waste` label is **a reviewer's judgement, recorded as given**. The system never
    sets it, never shows an unreviewed alert as waste, and never turns a label into a verified
    saving; every alert detail repeats those caveats.
  - **Feedback is an append-only history** (`alert_feedback`): a new verdict is a new row; the
    alert's `review_status` is the latest label and `reviewed_at` its time. Notes are at most 2,000
    characters and reviewers 100; control characters (other than tab and line breaks) and unknown
    fields are rejected (422). Text is stored as text, with bound parameters only.
  - **No retraining from feedback.** Nothing reads the labels into a model; every alert detail says
    `retrained_from_feedback: false`. A later retraining workflow would need vetted labels and its
    own decision (CLAUDE.md).
  - **Severity** is a band of the T022 priority score: `high` from 60, `medium` from 40, `low`
    below (4.2%, 28.6% and 67.2% of the full-scale alerts). A product assumption, for filtering.
  - **Alerts list highest priority first** (then by id), with filters for building, meter,
    dataset, signature, severity, kind, review status and an overlap with [`start`, `end`).
  - **Reloads keep reviews:** alerts are matched on (meter, detector, start); an alert a new run no
    longer finds is deleted unless it was reviewed, and then kept as `superseded` (hidden unless
    `include_superseded=true`).
  - **Reloading a dataset keeps its alerts** (a change to T024's loader): buildings and meters are
    now updated in place instead of deleted and re-inserted, which the alerts' foreign keys would
    have refused; removing a meter that still has alerts is refused. Found while loading the
    full-scale data with its alerts, before any reload had failed.
- **Alternatives considered:**
  - **The master instructions' three labels:** simpler, but "useful" would merge real excess and
    meter faults, which the impact rules (D040) keep apart.
  - **Overwriting the latest verdict:** loses the history of how a decision was reached.
  - **Deleting all alerts on reload:** simple, but it would delete reviewers' work.
  - **Authentication for reviewers:** not in this task; `reviewer` is a free-text name until the
    security task (T037) decides how users are identified.
- **Consequences:** the alert queue (T031) can sort by priority and filter by severity and review
  status. A later evaluation can compare labels with the detectors, as the LEAD check does.

## D048 — Uploads are validated, not stored; analysis uses the evaluation model and the default detector
- **Date:** 2026-10-29 · **Task:** T026 · **Status:** Accepted
- **Decision:** (backend README)
  - **`POST /data/upload`** validates one CSV file against the contract (T005) and returns its
    report: 200 when valid, 422 with the same report when not. **Nothing is stored**: a stored
    upload would need a dataset, a provenance label and an owner, which no task has decided. The
    file is read in memory (at most `WATTWISE_MAX_UPLOAD_BYTES`, default 10 MB; 413 above it,
    checked both against the declared size and while reading). The client's file name is reduced
    to a safe display name (no directories, `[A-Za-z0-9._-]`, at most 100 characters) and never
    used to open or write a file.
  - **`POST /inference/analyze`** takes `readings` and `buildings` CSV files (and optionally
    `weather`), validates them, and returns each meter's observed readings with the model's
    expectation, and the alerts. At most 200,000 readings and 50 meters (413 above).
    - **Alerts** come from the default detector (D030), the rolling same-hour z-score, which needs
      only the readings. Events are classified into signatures as usual.
    - **Expected consumption** comes from the promoted model (`CURRENT`). **This settles the open
      question from D039 for now: the evaluation model serves**, so an analysis uses the same model
      the intervals, detector checks and benchmarks were measured with. The production refit stays
      in the registry, unused.
    - Uploaded data has no ERA5 enrichment and no holidays for unknown sites, and the model was
      trained on BDG2 buildings, so the expectation for an uploaded building is **an extrapolation
      that has not been validated**; the response says so. The lag features need history: on the
      synthetic sample, each meter's first 251 hours have no expectation.
    - **Without a model** the analysis still returns the alerts, with `model_version: null` and the
      reason (the spec's "handle a missing model gracefully").
    - Responses are labelled `data_label: "uploaded"`, `stored: false`, `retrained: false`.
- **Found while testing:** on the synthetic sample (six injected anomalies) the default detector
  finds **one**, the three-day sustained excess. It misses the 2-hour spike (shorter than its
  persistence rule), the overnight baseload, the drift and the flatline, and raises three other
  events on `syn-lab-c`, two of them just after its injected missing-data gap. This matches the
  benchmark (spike recall 58%, flatline 43%, D042); it is the detector's behaviour, not the
  endpoint's, and it is a reason not to present an empty alert list as "no problems".
- **Alternatives considered:**
  - **Storing uploads as datasets:** useful for the explorer, but it needs a provenance decision
    (an upload is neither known synthetic nor known observed) and an owner; left for later.
  - **The model detector for uploads:** it needs a calibration window and the model's
    out-of-sample residuals, which an arbitrary upload does not have.
  - **The production refit for predictions:** slightly better accuracy (test MAE 13.660 against 13.700 on common rows, T043),
    but nothing downstream was measured with it.
- **Consequences:** T027 records each analysis run (model version, timestamp, input range). The
  frontend (T031) must show the caveats with the alerts.

## D049 — Model information and run records: recorded values only, "unavailable" said explicitly
- **Date:** 2026-10-29 · **Task:** T027 · **Status:** Accepted
- **Decision:** (backend README, DATABASE.md)
  - **`GET /models/metadata`** returns the promoted model's verified metadata (name, settings,
    feature columns, training window and rows, data fingerprint, split, code and library
    versions) and what it serves (D048). **`GET /models/metrics`** returns the validation and test
    metrics **exactly as recorded at training time**, with their windows, definitions and the
    label "observed" (BDG2). A role that was not recorded is `null`; nothing is recomputed or
    estimated in the API.
  - **Unavailable is an answer, not an error:** with no promoted model, a model whose files do
    not match their hashes, or one made for another artifact or feature-set version, both
    endpoints answer 200 with `available: false` and a reason (`no_model_promoted`,
    `model_invalid`, `model_incompatible`) and a message without file paths. A tampered model is
    never described as if it were fine.
  - **Verification is cached per version** (versions are immutable folders): the 51 MB hash check
    runs once (0.21 s), then 0.01 s. Failures are not cached.
  - **`analysis_runs`** (migration `0004`) holds one record per `/inference/analyze` call: the
    time, model version (`null` without a model), detector, input range, meters, readings, missing
    values, predictions and alerts. **Metadata only**: the uploaded readings are still not stored.
    Listed by `GET /analysis-runs`, newest first, filterable by model version.
  - **Recording never fails an analysis:** without a database, or if the write fails, the
    analysis is returned with `recorded: false`.
- **Alternatives considered:**
  - **404 or 503 for a missing model:** the API itself is fine and the question has an answer;
    an explicit `available: false` is easier to show truthfully in the model lab (T033).
  - **Comparing with seasonal-naive in the API:** the comparison is in EVALUATION.md, but not
    in the model's metadata; putting a number in the API that the registry does not record
    would be a copy that can drift.
- **Consequences:** the model lab (T033) can show the served model and its recorded metrics, and
  monitoring can count runs per model version.

## D050 — Frontend design system: colour tokens, themes, a history-API router, provenance everywhere
- **Date:** 2026-10-29 · **Task:** T028 · **Status:** Accepted
- **Decision:** (frontend README)
  - **Every colour is a token** (`--color-surface`, `raised`, `sunken`, `line`, `edge`, `ink`, `muted`,
    `accent`, `success`, `danger`, and a soft/strong pair for each data provenance), declared in
    `index.css` with Tailwind's `@theme`, so components use `bg-surface`, `text-muted` and never raw
    palette colours. A theme is a set of token values.
  - **Light, dark and system:** light is the default; dark applies under `data-theme='dark'`, and
    follows the operating system's preference when no theme has been chosen. The choice (System,
    Light, Dark) is in the header and remembered in `localStorage`; unavailable storage is not an
    error. The dark values are written twice in CSS (chosen and system), and a test fails if the two
    copies differ.
  - **Contrast is tested, not asserted:** a test reads the stylesheet's source and computes WCAG
    contrast for every text/background pair the components use, in both themes: at least 4.5:1 for
    text and 3:1 for the borders of controls (WCAG 1.4.11). Decorative borders (`line`) are exempt
    and are not used for controls.
  - **Shell:** a skip link, a labelled main navigation with `aria-current` on the current page, the
    theme switch and a main landmark. Five pages in navigation order (Overview, Buildings & meters,
    Alerts, Cost impact, Model lab), each naming the roadmap task that builds it; until then it
    says "Not built yet" and shows no data. An unknown address shows "Page not found".
  - **A small history-API router** (`usePath`), not a router library: five fixed pages and no route
    parameters yet. Modified clicks (Ctrl, Shift, middle) keep the browser's behaviour; back and
    forward work. Revisit when T030/T031 need route parameters.
  - **Provenance is always visible:** `ProvenanceBadge` (Synthetic, Observed, Uploaded) is text, never
    colour alone. `DemoBanner` appears on every page when the stored data includes synthetic data
    (from `data_kinds` in the dashboard summary), with a stronger message when only synthetic data is
    stored and a pointer to the badges when it is mixed. If the summary is unavailable it shows
    nothing and no error (the health panel reports the API).
  - **Shared states:** `LoadingState` (polite status, motion-reduced), `EmptyState`, `ErrorState`
    (alert, optional retry) and `PageHeader`; the existing API panel uses them.
- **Alternatives considered:**
  - **A router library** (React Router, TanStack Router): more than five fixed pages need.
  - **Class-based dark mode only** (`dark:` variants everywhere): scatters colours through
    components; tokens keep a theme in one place and make contrast testable.
  - **A component library:** the product needs a specific provenance and caveat vocabulary; a few
    small components cover the shell.
- **Found while building:** the first border for the theme selector reused the decorative `line`
  colour (about 1.2:1 on white), too faint to identify a control; it now uses `edge`.
- **Consequences:** T029-T033 use these tokens, states and badges. The overview (T029) decides
  server-state handling (D009's open question).

## D051 — The overview: per-kind figures, stored totals, plain hooks with one shared summary
- **Date:** 2026-10-29 · **Task:** T029 · **Status:** Accepted
- **Decision:** (frontend README, DATABASE.md)
  - **Totals are stored when a dataset is loaded** (migration `0005`: reading and missing counts,
    first and last reading, and measured kWh on `datasets`; the migration fills them for datasets
    already loaded). `GET /dashboard/summary` read these instead of aggregating the readings
    table: **11.0 s -> 0.19 s** on the 20.1 million readings in the local database. It had been
    fast only on the 5,376-row sample, and the shell calls it on every page for the demo banner.
  - **Figures are per kind of data and never added across kinds:** `by_kind` lists observed, then
    synthetic. Adding synthetic kWh to measured kWh would be meaningless, so no total mixes them.
  - **The six figures** (each with a definition and a source in its tooltip):

    | Figure | What it is | What it is not |
    |---|---|---|
    | Measured energy | sum of recorded kWh over the period | missing readings are not zero |
    | Model-expected energy, **in alert windows** | the model's expectation over the hours of consumption alerts, next to the recorded energy for those hours | not a portfolio-wide figure: no expectation is stored outside alert windows; above- and below-expected alerts net out |
    | Potential excess energy (**Estimate**) | kWh above the model's upper bound in alert hours (558.7 MWh for the observed data, the T044a figure) | not a verified saving; meter problems are not counted |
    | Open alerts | unreviewed or needs investigation, excluding superseded; with the high-severity count | not a count of real problems |
    | Data quality | share of readings missing, and the number of meter-problem alerts | not a quality score |
    | Coverage | buildings, meters, readings, datasets and the period | |

  - **Dashes, not zeros**, where a figure needs alerts and there are none; an empty database says
    "No data loaded" and how to load some; a missing database explains the setting and offers a
    retry.
  - **Server state: plain hooks, with one shared summary** (D009's open question). A
    `SummaryProvider` loads the summary once for the demo banner and the overview (one request,
    tested). A library such as TanStack Query earns its place with several resources, caching and
    invalidation; the first such page is the alert queue (T031), so this is revisited there.
  - **Tooltips follow WCAG 1.4.13:** they open on hover or focus, close on Escape or when the
    pointer or focus leaves, and are always in the accessible description of their button.
- **Not done, on purpose:** the spec's `start`, `end` and `building_id` filters for the summary.
  The stored totals are whole-dataset; a filtered figure needs a per-day aggregate and belongs with
  the explorer (T030).
- **Alternatives considered:**
  - **Caching the summary in memory:** hides the 11 s cost on all but the first request, and the
    first request is the page load.
  - **A materialised view:** stays correct when data changes underneath, but needs a refresh
    policy; totals at load time are exact because a dataset is replaced as a whole.
  - **Estimating a portfolio-wide expected energy** from the alert windows: rejected as invented.
- **Consequences:** the explorer (T030) can add per-meter expectations; if portfolio-wide expected
  energy is wanted, the model's predictions would have to be stored for every reading (20 million
  rows), which is a separate decision.

---

## Open decisions (tracked in tasks)

| Topic | Decide in | Notes |
|---|---|---|
| API type generation | T024 | Hand-written types and guards (D009) vs OpenAPI codegen |
| Chart library | T030 | See D001; needs interval bands, synchronised zoom and accessibility |
| Browser E2E tooling | T035 | Only if justified |

