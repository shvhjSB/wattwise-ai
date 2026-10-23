# Work log

Concise, chronological record of completed task checkpoints. A commit cannot contain its own
hash, so each entry's commit hash is recorded in the *next* checkpoint's entry (and always in
the end-of-task report).

---

## 2026-10-23 — T001 Repository audit, project records and hygiene

**Audit findings**
- **Commits:** the repository had one commit (`7711d9d`, "Initial commit") containing only `LICENSE` (MIT).
- **Untracked files:** two untracked user files, `CLAUDE_CODE_PROMPT.md` and `DATASET_CATALOG.md`,
  with no secrets. With the owner's approval they were moved unchanged to `docs/specs/` and committed.
- **Missing basics:** no `.gitignore`, README, code, tests or tooling.
- **Remote:** `origin` is `https://github.com/shvhjSB/wattwise-ai` (public). `main` is not protected.
  Git authenticates through `gh auth git-credential`, i.e. as the active `gh` account.
- **Toolchain:**
  - Available: Python 3.13, Node 24, npm 11, GitHub CLI.
  - Not installed: Docker, PostgreSQL, uv.

**Done**
- Added `.gitignore`, `.gitattributes`, `.editorconfig`, README, `CLAUDE.md` and CHANGELOG.
- Added the roadmap, status, decisions (D001–D005) and this work log.

**Validation:** `git check-ignore -v` confirmed that secrets, datasets, artifacts, local DBs,
virtualenvs and `node_modules` are ignored, and that `.env.example` and `data/sample/` are not.

**Push attempt:** `git push origin main` for commit `034c2f9` failed with HTTP 403:
"Permission to shvhjSB/wattwise-ai.git denied to aman-agntworksai". The active `gh` account has
only READ access. The commit was preserved locally. The audit note claiming that pushes would
use Git Credential Manager as `shvhjSB` was wrong and has been corrected in a follow-up commit.

**Commits:**
- `034c2f9` docs(project): add audit, roadmap, decisions and repo hygiene
- `9cc423a` docs(project): correct push-credential finding in audit records

`034c2f9` reached `origin/main` through a push from this clone at 13:04:32 that was not made by
Claude, because Claude's own attempt had failed. `9cc423a` was pushed by Claude after the
identity fix below.

---

## 2026-10-23 — T002 Backend foundation

**Done**
- `backend/` Python project `wattwise` (src layout, hatchling, Python >=3.12):
  - `wattwise.core.config.Settings`: environment-based settings (`WATTWISE_` prefix), frozen and validated.
  - `wattwise.api.main.create_app()`: an app factory with no import-time side effects.
  - `GET /api/v1/health`: liveness only. `/ready` is deferred to T023 (D004).
- Tooling: ruff (lint and format), mypy `--strict` with the pydantic plugin, and pytest with
  warnings treated as errors.
- Root `.env.example` and `backend/README.md`.
- **Scope note:** the planned `log_level` setting was left out because nothing uses it yet.
  Logging configuration belongs to T037.
- **Fix found by the checks:** Starlette 1.9 deprecates `httpx` for `TestClient`, so the dev
  extra now depends on `httpx2` (D003 note).

**Project-scoped GitHub identity (D006, owner's instruction).** This was applied to this clone
only; the global `gh` account is unchanged:

```bash
git config --local user.name shvhjSB
git config --local user.email "<email linked to the shvhjSB GitHub account>"
git config --local credential.https://github.com.helper ""
git config --local --add credential.https://github.com.helper \
  '!f() { test "$1" = get || exit 0; echo username=shvhjSB; echo "password=$(gh auth token --hostname github.com --user shvhjSB)"; }; f'
```

Verified: `git credential fill` returns `username=shvhjSB`, and GitHub attributes commits
`7711d9d`, `034c2f9` and `9cc423a` to `shvhjSB` as both author and committer.

**Validation** (fresh venv, Python 3.13.14, Windows)
- Packages installed: fastapi 0.161.1, starlette 1.9.0, pydantic 2.14.1,
  pydantic-settings 2.16.1, uvicorn 0.54.0, pytest 9.1.1, ruff 0.17.2, mypy 2.4.0, httpx2 2.16.0.
- `pytest`: 10 passed.
- `ruff check .`: clean. `ruff format --check .`: 14 files already formatted.
- `mypy` (strict, 13 files): no issues.
- uvicorn smoke test: `/api/v1/health` returned 200
  `{"status":"ok","service":"wattwise-api","version":"0.1.0","environment":"development"}`.
  `/openapi.json` returned 200 and `/docs` returned 200.

**Commit:** `bdbdebc` feat(api): add FastAPI foundation with health check and tooling. Pushed and
attributed to `shvhjSB` on GitHub.

---

## 2026-10-23 — Environment setup: PostgreSQL 18 and Docker Desktop (owner's request)

This setup is not a roadmap task. It unblocks T023, T034 and T036.

**Commit policy:** from now on, commits carry no `Co-Authored-By` trailer (D006 addendum).

**PostgreSQL 18.6** (winget `PostgreSQL.PostgreSQL.18`, EDB installer, hash verified by winget)
- **First attempt failed** at database cluster initialisation. The random password contained a
  leading `-`, which PowerShell parsed as a parameter of `initcluster.ps1`. The partial install
  was uninstalled (the owner confirmed the uninstaller dialog), then reinstalled with a
  32-character alphanumeric password.
- **Components:** the server (service `postgresql-x64-18`, automatic start, port 5432), the
  command-line tools and pgAdmin 4. StackBuilder was skipped.
- **Credentials:** the superuser password is stored only in `%APPDATA%\postgresql\pgpass.conf`
  and was never printed. The temporary installer option file was deleted.
- **Command-line access:** `C:\Program Files\PostgreSQL\18\bin` was added to the user PATH.
- **Verified:**
  - Service: Running, Automatic.
  - `psql --version`: 18.6.
  - An authenticated `select version()` over `localhost` returned
    `PostgreSQL 18.6 on x86_64-windows`.
  - `pg_hba_file_rules` allows only `127.0.0.1` and `::1`, with scram-sha-256.

**WSL2:** `wsl --install --no-distribution` (elevated) installed WSL 3.0.3 with default version 2.
Windows reports a pending reboot.

**Docker Desktop 4.96.3** (winget `Docker.DockerDesktop`, hash verified)
- **Verified:**
  - Docker CLI 29.9.2 and Docker Compose v5.6.1 are on the machine PATH.
  - User `Admin` is in `docker-users`.
- **Not yet verified:** the engine does not respond yet (`docker info` cannot reach
  `npipe:////./pipe/docker_engine`), as expected before the reboot and Docker Desktop's first
  launch. The Docker Subscription Service Agreement was **not** accepted on the owner's behalf;
  Docker Desktop asks for it on first launch.

**Commit:** `ddf0226` docs(project): record local PostgreSQL 18 and Docker setup. This is the
first commit without a co-author trailer.

---

## 2026-10-23 — T003 Frontend foundation

**Environment check first.** After the owner restarted Windows (boot 14:24), Docker Desktop's
engine was verified:
- `docker info`: server 29.9.2.
- `docker run --rm hello-world`: success.
- `docker compose version`: v5.6.1.
- The test image was removed afterwards.

**Done**
- `frontend/`: React 19.3, Vite 8.3, Tailwind CSS 4.3 and TypeScript 6.0 (strict,
  `noUncheckedIndexedAccess`), with dependencies locked in `package-lock.json`.
- `src/api/client.ts`: typed `getJson()` that validates responses with type guards. It raises
  `ApiError` of kind `network`, `http` or `invalid-response`, and re-throws aborts unchanged.
- `src/api/health.ts`: `HealthResponse` (mirrors the backend schema), `isHealthResponse` and `fetchHealth`.
- `src/features/health/`: the `useApiHealth` hook (abort on unmount, manual retry) and
  `ApiHealthPanel` (a polite live region for loading and success, `role="alert"` for errors,
  and a Retry button).
- `App.tsx` shell with an honest note that no energy data is shown yet.
- The dev server proxies `/api` to the backend (D009). Both READMEs and the frontend
  `.env.example` were added.
- **Version constraints found during setup:**
  - TypeScript 7.0 is out, but typescript-eslint supports only TypeScript up to 6.0.
  - `eslint-plugin-jsx-a11y` supports only ESLint up to 9.
  - Both are recorded with upgrade triggers in D008.
- **Fixes found by the checks:**
  - ESLint flagged `||` in `vite.config.ts`. The empty-string fallback is now explicit.
  - Prettier re-wrapped three files (layout only).
  - The integration run showed that the dev proxy returns HTTP 502 when the backend is down.
    The error message now says "the API request failed with HTTP 502" instead of claiming the
    API itself responded.

**Validation** (Node 24.18, npm 11.16, Windows)
- `npm ci`: clean install from the lockfile, 0 vulnerabilities.
- `npm run typecheck`: pass.
- `npm run lint` (zero warnings allowed): pass.
- `npm run format:check`: pass.
- `npm test`: 4 files and 21 tests passed (client errors, guards, panel loading, online,
  error-with-retry and HTTP failure, app shell).
- `npm run build`: pass. JS 224 kB (70 kB gzip), CSS 11.7 kB.
- **Integration**, with uvicorn on :8000 and Vite on :5173:
  - `GET /` returned 200 (title "WattWise AI", `#root` present).
  - `GET /src/main.tsx` returned 200 (the module was transformed).
  - `GET /api/v1/health` through the proxy returned 200 with the real backend payload.
  - With the backend stopped, the proxy returned 502, which the UI reports as an error.
- **Not done:** no visual check in a real browser. No browser automation is installed; the
  component tests cover the rendered states.

**Commit:** `8212986` feat(web): add React frontend foundation with typed API client.

---

## 2026-10-23 — T004 CI baseline (done; see "Verified on GitHub" at the end of this entry)

> **Correction (17:10).** While Claude was paused, another session committed this entry locally
> in `f102edd` (16:45, not pushed). It marked T004 Done before CI had ever run. A follow-up
> commit corrected four things:
> - the T004 status, in this file, the roadmap and the project status
> - D010's statement that pip/`.[dev]` installs still work, and the broken `backend/README.md`
>   instructions
> - D011's claim that CI "guarantees" gates before merge (there is no branch protection)
> - D003, marked as partly superseded
>
> `f102edd` itself was kept, not rewritten.

**Work so far**
- `.github/workflows/ci.yml`:
  - Triggers on `push` to `main`, `pull_request`, and manual `workflow_dispatch`.
  - Least-privilege top-level `permissions: contents: read`.
  - Concurrency: one group per PR (new pushes cancel older runs); a unique group per run on `main`
    and for manual runs (see the review fixes below).
  - Two parallel jobs on `ubuntu-24.04`:
    - `backend`: installs `uv` 0.12.24 via `astral-sh/setup-uv`, syncs locked dependencies (`uv sync --locked`), runs ruff lint with GitHub annotations, ruff format check, strict mypy, and pytest.
    - `frontend`: sets up Node 24 via `actions/setup-node` reading `frontend/.nvmrc`, runs `npm ci`, Prettier check, ESLint, TypeScript check, Vitest suite, and production Vite build.
  - All third-party actions pinned to full 40-character commit SHAs with version comment annotations (D011).
  - Dependency caching for uv (keyed on `backend/uv.lock`, after the review fix below) and npm
    (keyed on `frontend/package-lock.json`). Whether the uv cache really hashes the lockfile is
    checked in the first GitHub run's log.
- Backend dependency locking (D010):
  - Migrated dev dependencies to PEP 735 `[dependency-groups]` (`dev`) in `backend/pyproject.toml`.
  - Pinned `[tool.uv] required-version = ">=0.12.24,<0.13"`.
  - Added `backend/.python-version` (`3.13`).
  - Added multi-platform `backend/uv.lock`.
- Frontend environment alignment:
  - Added `frontend/.nvmrc` (`24`).
- Documented decisions D010 (backend dependency locking with uv) and D011 (CI workflow design and action pinning) in `docs/DECISIONS.md`.

**Local validation** (Windows; the checks above, run through `uv run --locked`)
- Tool installed: uv 0.12.24 (winget), pinned as the newest release at least two weeks old (D010).
- `uv lock`: 38 packages resolved for all platforms, including `uvloop` with the marker
  `sys_platform != 'win32'`. `uv sync --locked`: pass.
- `actionlint` 1.7.12 (Docker image `rhysd/actionlint:1.7.12`): 0 errors in `.github/workflows/ci.yml`.
- Backend (Python 3.13, Windows):
  - `pytest`: 10 passed in 0.17s.
  - `ruff check .`: clean.
  - `ruff format --check .`: 14 files already formatted.
  - `mypy` (strict, 13 files): success, no issues found.
- Frontend (Node 24, npm 11, Windows):
  - `npm run lint`: pass (0 warnings).
  - `npm run typecheck`: pass.
  - `npm run format:check`: pass.
  - `npm test`: 4 files, 21 tests passed.
  - `npm run build`: pass (JS 224 kB / 70 kB gzip, CSS 11.7 kB).

**Linux replay of both CI jobs** (Docker, from `git archive HEAD` of `c90d1c2`: 61 files, no
venv, `node_modules` or `dist`)
- **First attempt invalid, discarded.** The image tag `uv:0.12.24-bookworm` did not exist.
  Windows PowerShell 5.1 also stripped the double quotes from the inline `sh -c` script, so the
  frontend container exited 0 *without running any step*. Both jobs were re-run from `.sh` script
  files instead.
- **Backend** (`ubuntu:24.04`, the official uv 0.12.24 Linux binary from `ghcr.io/astral-sh/uv:0.12.24`):
  - No system Python. uv downloaded CPython 3.13.16, as it will on the GitHub runner.
  - `uv sync --locked`: 36 packages installed, including `uvloop`.
  - ruff check, ruff format (14 files), strict mypy (13 files) and pytest (10 passed): all pass.
- **Frontend** (`node:24-bookworm`, Node 24.22.1, npm 11.19.1):
  - `npm ci`: 367 packages.
  - Prettier, ESLint, tsc, Vitest (21 passed) and the build: all pass.
- **Failure propagation:** a deliberately failing test (pytest) and a deliberate lint violation
  (ESLint) each exited **1**. A broken check therefore fails its CI step.

**Adversarial review.** A Workflow ran 3 reviewer lenses (GitHub CI correctness, security/supply
chain, reproducibility/docs) with 1 refuting skeptic per lens: 6 agents, about 11 minutes.
Reviewers also confirmed that each pinned SHA is the commit of its tag and that every release is
at least two weeks old.
- **Confirmed and fixed:**
  1. **(medium, found by all three lenses)** `cache-dependency-glob: backend/uv.lock` is resolved
     relative to `working-directory: backend`, so it pointed at `backend/backend/uv.lock`. The uv
     cache would never have refreshed, and every run would have printed a warning. Fixed to
     `uv.lock`; the pinned action's `action.yml` says the glob is "relative to the working
     directory".
  2. **(low)** A shared `main` concurrency group lets GitHub replace a *pending* run. Non-PR runs
     now use a unique group (`github.run_id`).
  3. **(low)** The uv download was checked only against an online manifest that can change. Its
     SHA-256 is now pinned in the workflow (`b4dfaef4…3da6`), matching both the release API
     digest and the release's `.sha256` asset.
  4. **(low)** The build backend floated. `[tool.uv] build-constraint-dependencies` now pins
     hatchling 1.32.4 and its five dependencies. With a cold cache, uv selected
     `hatchling==1.32.4`.
  5. **(low)** The docs said "uv 0.12.x", and the generic installer now installs 0.13, which
     `required-version` rejects. The docs now say "0.12.24 or a later 0.12.x" and give
     version-pinned installers.
  6. **(low)** The frontend Node minimum `>=22.12` was too low. Every locked package's `engines`
     range was checked against candidate versions: the real requirement is
     `^22.22.2 || ^24.15.0 || >=26.0.0` (jsdom). `package.json`, the lockfile's root entry (a
     one-line change) and the README were updated, and `npm ci` stays in sync.
- **Refuted by the skeptics:**
  - The records under-reported the replay. They were stale but not false; the replay is recorded here.
  - The `gh` scope-fix wording. The switch-back step is now spelled out in PROJECT_STATUS anyway.
  - The idea that locked Python packages need a two-week cooldown. That is a policy choice, now
    stated as out of scope in D010.

**Push and the `workflow` scope**
- The first push of `f102edd`, `c90d1c2` and `6948af4` was rejected by GitHub: "refusing to allow
  an OAuth App to create or update workflow `.github/workflows/ci.yml` without `workflow`
  scope". Nothing was lost.
- Two owner-run refresh attempts added the scope to `aman-agntworksai`, not `shvhjSB`. At the
  owner's explicit request, Claude then refreshed it for `shvhjSB` directly:
  1. `gh auth switch -u shvhjSB`
  2. `gh auth refresh -s workflow` (the owner approved the device code while signed in as `shvhjSB`)
  3. Verified that `gh api user` returns `shvhjSB` and that the scopes now include `workflow`
  4. `gh auth switch -u aman-agntworksai`, restoring the owner's previous active account
- The push then succeeded: `8212986..6948af4`, and `git ls-remote` matched the local hash.
- GitHub attributes all three commits to `shvhjSB` as author and committer, with no co-author trailer.

**Verified on GitHub:**
[run 39951620258](https://github.com/shvhjSB/wattwise-ai/actions/runs/39951620258) for `6948af4`
(push event). **Conclusion: success.** It took 28 s, and both jobs ran in parallel.
- **Backend (Python): success.** Every step passed.
  - setup-uv downloaded uv 0.12.24 with the pinned `checksum`. In setup-uv's code at the pinned
    SHA, a provided checksum takes priority and a mismatch throws, failing the step.
  - "**Found 1 files to hash.**" The cache key is derived from `uv.lock`. No "No file matched"
    warning appeared, which confirms the review fix.
  - First run: no cache yet. The cache was saved afterwards.
  - CPython 3.13.16, 36 packages including `uvloop`, ruff check and format (14 files), strict
    mypy (13 files), pytest **10 passed**.
- **Frontend (Node): success.** Every step passed.
  - Node from `.nvmrc`; `npm ci` added 367 packages.
  - Prettier, ESLint, tsc, Vitest (4 files, **21 passed**) and the build all passed.
  - The npm cache was saved under a key from `package-lock.json`.
- 0 annotations on either job.
- Acceptance: (1) green on GitHub for the pushed commit: **met**. (2) A failing check fails the
  job: **met**, by the Linux replay. A failing test and a lint violation each exited 1, and
  GitHub fails a step on a non-zero exit. No deliberately broken commit was pushed to the public
  repository to demonstrate it.

**Commits:** `f102edd`, `c90d1c2`, `6948af4` (this entry's final records update follows in the
next commit).

**Commit:** `d75b1cb` docs(project): mark T004 done after first green CI run. The second CI run
([39951971170](https://github.com/shvhjSB/wattwise-ai/actions/runs/39951971170)) was green and
reused both caches: uv got a cache hit on the `uv.lock`-derived key and "Prepared 1 package";
npm got a cache hit.

---

## 2026-10-23 — T005 Canonical data contracts and CSV upload format

**Done**
- **`wattwise.data.contracts`:** contract v1.0 with three tables.
  - `readings`: key (`meter_id`, `timestamp`).
  - `buildings`: key `building_id`; `timezone` required; optional area and location.
  - `weather`: key (`site_id`, `timestamp`).
  - The `MeterType` vocabulary (8 BDG2 meter types) and units `kWh` / `m3`, with exactly one
    canonical unit per meter type. Only electricity is analysed for now.
- **`wattwise.data.validation`:** a single path for text frames and typed frames.
  - It coerces each column to its canonical dtype (`datetime64[us, UTC]`, `float64`, `str`)
    while recording missing and invalid cells.
  - Table checks: primary key, canonical unit per meter type, one building, type and unit per
    meter, and an unsupported-meter-type warning.
  - 21 stable issue codes in a Pydantic report.
  - `validate`, `to_canonical` (raises `ContractViolationError`) and `check_table`.
- **`wattwise.data.csv_io.read_csv`:** reads paths and text or binary streams. It handles
  UTF-8 (with or without a BOM), exact field counts with line numbers, empty or duplicate header
  names and encoding errors. A caller's stream is left open.
- **`docs/DATA_CONTRACT.md`:** principles, tables, vocabularies, identifier rules, the CSV upload
  format, issue-code reference, code usage and versioning.
- **Decision:** D012.
- **Dependencies:** pandas 3.0.6 (3.0 series, matching `pandas-stubs` 3.0.5), numpy 2.5.4, tzdata
  2026.5, and `pandas-stubs` as a dev dependency. `tests/` folders became packages, because mypy
  needs unique module names for the two `conftest.py` files.

**Found and fixed during the task**
- **pandas behaviour, verified by probes:**
  - With `utc=True`, pandas silently treats timestamps without an offset as UTC. The validator
    therefore requires an explicit offset before parsing.
  - pandas pads short CSV rows with `''`. Uploads are therefore parsed with the stdlib `csv`
    module (the first approach missed short rows; a test caught it).
- **Suggestion text:** it showed enum reprs (`<Unit.KWH: 'kWh'>`). Vocabularies are now plain
  strings (a test caught it).
- **Grammar:** generating the documentation examples from a real run exposed broken singular
  messages, e.g. "1 value is no time zone". All row-level messages now agree in number.
- **Documentation example:** my first "valid" CSV example was actually invalid: `02:00+01:00` is
  01:00 UTC, which duplicated a key. The example was fixed, and the docs test now runs both CSV
  examples through the real reader.
- **Typing:** strict mypy found that a non-standard *text* stream would have been wrapped as
  binary. Streams are now told apart with `read(0)`.
- **Performance:** profiling showed the identifier regex took 52% of the time, matched per row
  instead of per distinct value. After the fix, 1.05 M typed rows take 2.65 s (was 3.62 s) and
  175,680 CSV rows take 1.42 s (was 2.16 s).

**Validation** (Windows, uv-managed venv)
- `uv lock --check`: pass. `ruff check .`: clean. `ruff format --check .`: 27 files formatted.
  `mypy` (strict): no issues in 26 files.
- `pytest`: **87 passed**, of which 77 are new in T005:
  - The five acceptance cases: missing columns, naive timestamps (typed and text), unknown units
    (with a suggestion), non-numeric values, duplicate keys.
  - Identifiers, meter types, non-canonical units, meter consistency, the unsupported-type
    warning, infinite values, missing required values, empty tables, dtype errors, unparseable
    timestamps, truncation of long issue lists, and building and weather rules.
  - CSV structure: BOM, encoding, extra and short rows, unnamed and duplicate headers, a CSV
    round trip equal to the in-memory table, and the caller's stream left open.
  - Documentation sync, including both CSV examples.
- The GitHub CI run for this commit is checked after the push (see the end-of-task report).
