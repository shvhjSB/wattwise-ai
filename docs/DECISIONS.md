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
    supply-chain precaution.
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
  - Contributors need uv 0.12.x installed (`[tool.uv] required-version`).

## D011 — CI workflow design and action pinning
- **Date:** 2026-10-23 · **Task:** T004 · **Status:** Accepted
- **Decision:**
  - Single CI workflow in `.github/workflows/ci.yml` running on pushes to `main`, all pull
    requests, and `workflow_dispatch`.
  - Supply-chain security: all third-party GitHub Actions are pinned to full 40-character commit
    SHAs with comment annotations naming the release tag (e.g. `actions/checkout@3d3c42e5... # v7.0.1`).
  - Least privilege: top-level `permissions: contents: read`.
  - Concurrency control: `cancel-in-progress` enabled for pull requests, disabled on `main` to
    preserve main-branch audit history.
  - Parallel jobs for backend (`ubuntu-24.04`, Python 3.13 via `astral-sh/setup-uv`) and
    frontend (`ubuntu-24.04`, Node 24 via `actions/setup-node` reading `frontend/.nvmrc`).
  - Both jobs cache dependencies: `astral-sh/setup-uv` caches on `backend/uv.lock`, and
    `actions/setup-node` caches on `frontend/package-lock.json`.
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
    two-week rule.

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

