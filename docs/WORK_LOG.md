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

**Commit:** `587a304` feat(data): add canonical data contracts, validation and CSV upload format.
CI run [39955368773](https://github.com/shvhjSB/wattwise-ai/actions/runs/39955368773) was green
on Linux (87 backend tests, 21 frontend tests).

---

## 2026-10-23 — T006 Deterministic synthetic fixture generator

**Done**
- **`wattwise.data.synthetic`:**
  - `generate(seed)` returns canonical `readings`, `clean_readings` (the counterfactual before
    injection, kept in memory only), `buildings`, `weather` and the anomaly `labels`.
  - `write(dataset, dir)` writes the CSVs, a generated README and `manifest.json` (SHA-256,
    bytes, rows).
  - CLI: `python -m wattwise.data.synthetic --output DIR [--seed N]`.
- **Scenario:**
  - 2 synthetic sites: `syn-site-uk` (Europe/London) and `syn-site-us` (America/New_York).
  - 4 buildings: two offices, a retail store and a laboratory.
  - 56 days of hourly data from 2016-01-04 (Monday).
  - 6 injected anomalies, one per type.
- **Committed fixture:** `data/sample/synthetic/`, seed 2016. 5,376 readings, 2,688 weather
  rows, 4 buildings and 6 labels; 564,166 bytes in total.
- **Decision:** D013.

**Verified before writing tests**
- **Local-time schedules:** both offices peak at 10:00 *local* time (London and New York), with
  weekend load clearly lower.
- **Heating, and a confound:** hourly load correlates *positively* with temperature for two
  buildings, because both peak in the afternoon. On daily averages, every building shows the
  heating effect: correlation −0.46 to −0.95, and the fitted slope recovers the model's heating
  coefficient (−2.22 vs 2.0, −1.16 vs 1.2, −2.40 vs 2.5, −1.41 vs 1.5). This is noted in the
  generated README for later modelling (T013).
- **Injected changes:** 833 of 5,376 rows changed, all inside labelled windows.
  - The overnight event changed exactly 70 of 168 window hours (10 night hours × 7).
  - The flatline changed 11 of 12 hours; the first hour is the held value.
- **In-process reproducibility:** two separate runs with seed 2016 produced identical file
  hashes.

**Validation** (Windows)
- `uv lock --check`: pass. ruff: clean. Format: 29 files. `mypy` (strict): no issues in 28 files.
- `pytest`: **104 passed**, 17 of them new:
  - The committed fixture equals a fresh generation byte for byte.
  - The same seed gives identical files; another seed changes the noise but not the scenario.
  - The manifest hashes match the files.
  - All three tables pass the contract with no warnings, and reading the files back gives the
    generated tables.
  - The fixture is under 1 MB.
  - Changes occur only inside labelled windows, and every label changes something.
  - The labels are marked synthetic and cover each type once; identifiers are `syn-` and there
    are no coordinates.
  - The offices follow local hours, and daily load falls as temperature rises.
  - Each anomaly has its documented effect, and the CLI writes every file.
- Cross-platform byte identity: checked in a Linux container and in GitHub CI (see the
  end-of-task report).

**Commit:** `6349c7a` feat(data): add deterministic synthetic fixture generator and sample. CI
run [39957140784](https://github.com/shvhjSB/wattwise-ai/actions/runs/39957140784) was green on
Linux (104 backend tests, 21 frontend tests). The Linux container replay before the push also
reproduced the Windows-made fixture byte for byte.

---

## 2026-10-23 — T007 BDG2 acquisition tooling and dataset documentation

**Research.** Everything below was verified, not assumed.
- **Repository** (`gh api`): `master` = `9b97ccb` (2023-10-14). All data files are Git LFS
  pointers; their `oid sha256` and `size` give the expected checksums.
- **Pin:** tag `v1.0` (`3d0cbaf`, 2020-06-04) differs from `master` for `weather.csv` and
  `electricity_cleaned.csv`. Three later data commits exist: cleaned electricity updated on
  06-15, `weather_UTC.csv` added on 06-23 and removed on 06-24, and `weather.csv` corrected on
  06-24. The pin is therefore `753598e0` (2020-06-24), the last data commit. Its four needed
  files match `master` exactly (pointer comparison).
- **Licence:**
  - `LICENSE` was MIT from 2020-05-03 (and at the pin), then changed to "Attribution-ShareAlike
    4.0 Unported" on 2023-10-14. That file's text follows the CC BY-SA 3.0 Unported legal-code
    wording.
  - Zenodo v1.0 deposit (API): CC BY 4.0.
  - ORNL portal record (Opendatasoft API, publisher NUS): CC BY 4.0.
  - Article (Europe PMC, Crossref): CC BY 4.0, with CC0 for the article's metadata files.
  - Recorded with conservative handling (D014).
- **The web-reading agent could not retrieve the facts:** the ORNL pages render client-side, and
  Nature is behind a cookie wall. It reported nothing rather than guessing. The facts came from
  the APIs and the open-access full text instead.
- **The paper (PMC7591488):**
  - Timestamps are in local time for meters and weather.
  - Readings are hourly sums in "kWh … for the energy-related meters and liters for the
    non-energy meters".
  - The cleaned data removed anomaly-detected outliers, zero runs over 24 h and electricity zero
    readings.
  - Whether a timestamp marks the start or end of its hour is not stated.
- **Download URLs** (HEAD requests only, before any download):
  `media.githubusercontent.com/media/<repo>/<commit>/<path>` returned 200, with Content-Length
  exactly equal to the pointer sizes. `raw.githubusercontent.com` returned the 131-byte pointer.

**Done**
- **`wattwise.data.acquisition`:** `RemoteFile` (validated: relative path, SHA-256 hex, positive
  size), `ensure`, `verify`, `open_url` (HTTPS only, identifying User-Agent).
  - Streams to `.part` with SHA-256 and a size limit, then renames atomically.
  - Valid files are not re-downloaded; mismatching files are never overwritten without `force`.
  - Specific messages for offline, HTTP 403/429 (LFS quota), 404, LFS pointers, truncation,
    oversize and checksum mismatch.
- **`wattwise.data.bdg2`:** the pinned source with four files, a JSON manifest writer (keeps
  `downloaded_at` and updates `last_verified_at`), and a `list | fetch | verify` CLI.
- **`docs/DATASETS.md`; decision D014;** the T009 roadmap scope now includes the findings.

**Real download** (approved by the owner: all 4 files)
- `fetch`: all four downloaded and verified in **25 s** (368.9 MB).
- Second `fetch`: all four "verified", nothing downloaded, **1.4 s**.
- `verify` (offline): all verified.
- Independent `sha256sum`: identical to the pinned hashes. No `.part` leftovers.
- `git status` shows only code and `data/manifests/bdg2.json`; `data/raw/bdg2/` is ignored.

**Facts checked on the downloaded files** (for T009, not processing)
- **Electricity:** wide format, 1,578 building columns × 17,544 hourly rows,
  `2016-01-01 00:00:00` → `2017-12-31 23:00:00`.
- **Weather:** long format, 19 sites, 331,166 rows (16,860–17,544 per site).
- **Metadata:** 1,636 buildings × 32 columns.
- **Daylight saving:** all 19 sites are in daylight-saving zones, yet the electricity timestamps
  are a regular grid (0 duplicates, every step 1 h). `2016-03-13 02:00` (non-existent on US
  clocks) appears once, and `2016-11-06 01:00` (repeated on US clocks) appears once. So the
  timestamps are **not** daylight-saving wall-clock time; T009 must test the
  local-standard-time hypothesis.

**Validation** (Windows)
- `pytest`: **135 passed**, of which 31 are new. ruff, format and strict mypy (32 files) are
  clean; `uv lock --check` passes. The new tests are:
  - acquisition: download, verified skip, no silent overwrite, force, checksum, truncation,
    oversize, interrupted stream leaves no `.part`, offline, 403 quota hint, LFS pointer,
    progress, offline verify, unsafe paths, HTTPS only
  - bdg2: exact pin, LFS endpoint, unique keys, docs in sync with the source definition,
    `data/raw` ignored, manifest provenance, a re-fetch keeps the download date, subsets, CLI
    `list`, `verify` and failure exit codes

**Commit:** `85d3530` feat(data): add verified BDG2 acquisition and dataset documentation. CI
run [39959311819](https://github.com/shvhjSB/wattwise-ai/actions/runs/39959311819) was green
(135 backend tests, 21 frontend tests).

---

## 2026-10-23 — T008 Data-quality engine and report

**Done**
- **`wattwise.data.quality`:** `assess(readings, buildings=None, thresholds=None)` produces a
  `QualityReport`.
  - The contract runs first; structural errors, including duplicate timestamps
    (`duplicate_key`), stop the assessment.
  - Each meter is then assessed on its own inferred interval, with nine checks: gaps, irregular
    intervals, missing values, low coverage, negative values, zero runs, flatlines, extreme
    values and implausible intensity.
  - Findings are `info` or `warning`, with a count and an example window, and phrase causes as
    hypotheses.
  - `QualityThresholds` are validated Pydantic settings.
  - JSON and Markdown rendering are deterministic. CLI: `python -m wattwise.data.quality`.
- **Docs and example:** `docs/DATA_QUALITY.md`, and a committed example report
  `docs/reports/synthetic-data-quality.{json,md}`.
- **Decision:** D015.

**Found and fixed during the task**
- **Extreme values:** the first version used a robust z-score (threshold 10). Run on the
  synthetic sample, it flagged the injected 2.2× **behaviour** spike in `syn-office-a` (260.6 kWh,
  11.3 robust SDs), because bimodal office load makes the MAD small. That breaks the rule that
  quality checks must not flag behaviour. The check was replaced by a ratio to the meter's 99th
  percentile (default 5×): the spike is about 2.1× the 99th percentile (128.8), while a ×1000 slip
  is flagged. Recorded in D015 and DATA_QUALITY.md.

**Validation** (Windows)
- `uv lock --check`: pass. ruff: clean. Format: 35 files. `mypy` (strict): no issues in 34 files.
- `pytest`: **164 passed**, of which 29 are new:
  - A clean meter has no findings.
  - Duplicates and naive timestamps are reported as contract issues.
  - Gaps report their longest window.
  - Low coverage is flagged below the threshold but not exactly at it.
  - Irregular steps are flagged, and missing values report their longest run.
  - Negatives are flagged, but not on solar meters.
  - Zero runs are flagged at 24 intervals but not 23; flatlines at 6 but not 5. Zeros are not
    flatlines, a gap breaks a run, and the tolerance is configurable.
  - A ×1000 slip is extreme; a 2.5× spike and short series are not.
  - Intensity is flagged with a tiny floor area, not with a plausible one or an unknown area,
    and only for electricity.
  - Threshold validation, the summary counts and determinism hold.
  - **On the synthetic fixture, exactly the injected data faults are found**, with windows equal
    to the labels.
  - The committed report is up to date, the CLI fails on invalid input, and the doc lists every
    check and threshold.
- **Performance:** 1.75 M readings (100 meters × 2 years hourly) take 5.3 s, of which the
  contract check is 4.9 s; about 84 s extrapolated for BDG2 electricity.

**Commit:** `08ecd16` feat(data): add data-quality engine with deterministic reports. CI run
[39960884037](https://github.com/shvhjSB/wattwise-ai/actions/runs/39960884037) was green
(164 backend tests, 21 frontend tests).

---

## 2026-10-24 — T009a BDG2 timestamp-convention audit (T009 split)

**Why T009 was split.** The first experiment on the real data refuted T007's working hypothesis
("BDG2 uses local standard time"). Determining each site's clock became a research task of its
own, so under the roadmap rule T009 was split into T009a (this audit) and T009b (the pipeline)
before any pipeline code was written.

**Evidence gathered**, using throwaway scripts first, then the committed audit:
1. **Load-profile shifts** at the 8 clock changes of 2016–2017 (weekdays, 3 weeks before vs
   after; the best lag in −3..3).
   - Spring: 21 of 36 site-transitions showed lag 0 (wall clock) and 11 showed −1 (standard).
   - Autumn: 26 of 37 showed 0 and 8 showed +1.
   - The sites are internally consistent: Eagle, Moose and Wolf show −1/+1 at all four
     transitions; Bear, Bobcat, Bull, Hog and Peacock show 0 at all four.
2. **Transition hours.**
   - The spring non-existent hour is empty for **100%** of live meters at Bear, Bobcat,
     Cockatoo, Gator, Peacock and Rat (neighbouring hours mostly filled).
   - The autumn repeated hour is about **2×** normal at Crow, Mouse and Wolf (two hours summed).
3. **Margin sensitivity.** Verdicts are identical at margins 0.0025 and 0.005. At 0.01, Fox and
   Robin flip to undetermined, so the classifier now requires stability across all three.
4. **Weather.**
   - Every site has a real reading at each spring non-existent hour and 24 rows on autumn change
     days (Cockatoo has one ordinary missing hour).
   - No transition shows the wall-clock pattern.
   - The summer-minus-winter phase of the temperature cycle is −1.44 to +0.28 h, never +1 h.
   - So weather is a fixed offset: standard time at all sites.
   - Several sites share identical weather (shared stations).

**Done**
- **`wattwise.data.time_convention`:** `transitions`, `winter_offset` (January total offset;
  Europe/Dublin = 0), `nonexistent_hours`, `profile_shift`, the margin-stable `classify`
  (human and solar rules), and `to_utc`. For wall-clock data, `to_utc` turns non-existent and
  repeated hours into NaT; undetermined clocks raise.
- **`wattwise.data.bdg2_audit`:**
  - per-site electricity evidence (profile shifts plus spring-gap signatures) and weather
    evidence (structural checks, shifts, phase)
  - verdict rules: a "standard" verdict is overruled when the spring hours are systematically
    empty
  - pinned `ELECTRICITY_CLOCKS` and `WEATHER_CLOCKS`, and `mismatches()`
  - a CLI that writes evidence to git-ignored `data/processed/bdg2/time_convention.{json,md}`
    and exits non-zero on any mismatch with the pins
- **Mini BDG2-format fixture builder** (`tests/data/conftest.py`): the same files, columns and
  timestamp format as BDG2, with standard, wall-clock (empty non-existent hour, summed repeated
  hour) or flat sites. It is reused by T009b.
- **Docs and roadmap:** DATASETS.md "Data conventions" was rewritten with the per-site table and
  the conversion consequences. The interval-start assumption is now explicit (D016). The roadmap
  split T009 into T009a and T009b and updated the dependencies (T012 and T013 now depend on
  T009b).

**Real-data result** (`python -m wattwise.data.bdg2_audit`, 23 s, exit 0, all pins matched)
- Electricity, wall-clock (11 sites): Bear, Bobcat, Bull, Cockatoo, Crow, Gator, Hog, Lamb,
  Mouse, Panther, Peacock.
- Electricity, standard (3 sites): Eagle, Moose, Wolf.
- Electricity, undetermined (5 sites, 522 buildings): Fox and Robin (margin-sensitive), Rat
  (conflicting), Shrew and Swan (insufficient or mixed).
- Weather: standard at all 19 sites.

**Validation** (Windows)
- `uv lock --check`: pass. ruff: clean. Format: 39 files. `mypy` (strict): no issues in 38 files.
- `pytest`: **197 passed**, of which 33 are new:
  - time-zone facts (transition dates, winter offsets including the Dublin trap, non-existent
    hours)
  - `to_utc` (standard vs wall-clock, nothing guessed, undetermined and timezone-aware input
    rejected)
  - classification recovers standard and wall-clock in two time zones and for solar signals; a
    flat load is undetermined
  - margin sensitivity, too few transitions and mixed evidence all give undetermined
  - verdict rules (conflict overrule, weather structural evidence)
  - the audit on mini BDG2-format files recovers the known conventions
  - pin mismatches are reported, and the CLI handles a missing download
  - the pins cover all 19 sites and are documented row by row

**Commit:** `52ac2c5` feat(data): audit BDG2 timestamp conventions per site. CI run
[40070985539](https://github.com/shvhjSB/wattwise-ai/actions/runs/40070985539) was green.

---

## 2026-10-24 — T009b BDG2 preprocessing pipeline

**Done**
- **`wattwise.data.bdg2_prepare`** (module CLI). It does the following:
  - reads the metadata and the chosen electricity variant (cleaned by default, raw on request,
    with the reason recorded)
  - logs every non-electric meter flagged in the metadata
  - converts each site to UTC once with its pinned T009a clock, counting dropped hours
  - excludes meters with no metadata, an undetermined clock or less than 50% coverage
  - draws a seeded sample, then reshapes wide to long through `to_canonical`
- **Tables:** buildings come from the metadata (`sqm` → `floor_area_m2`, `primaryspaceusage` →
  `primary_use`, latitude, longitude, time zone). Weather for the sampled sites is converted
  with its own clock, and per-site join coverage is recorded.
- **Outputs:**
  - Parquet tables: readings, buildings, weather.
  - `exclusions.csv`.
  - The T008 quality report (JSON and Markdown).
  - `manifest.json`: pinned commit, input and output SHA-256s, options, assumptions,
    statistics, licence note.
- **Input checks:** inputs are verified against the pinned checksums first;
  `--skip-input-verification` is explicit and recorded.
- **Dependency:** `pyarrow>=26,<27` (26.0.0) for Parquet; `uv.lock` updated.
- **Docs:** DATASETS.md has a new section, "Preparing BDG2 for analysis", with the first-run
  results. The resolved notes on raw vs cleaned data and weather alignment were updated. D017
  records the design.

**Real-data result** (`python -W error -m wattwise.data.bdg2_prepare`, defaults, exit 0, about 12 s)
- 1,578 electricity meters:
  - 522 excluded for an undetermined clock and 43 for insufficient data, leaving 1,013 eligible.
  - The 20 sampled come from 9 sites: 8 wall-clock and Eagle standard.
  - 1,475 non-electric meters were logged.
- 350,804 readings, which reconciles with 20 × 17,544 minus 19 wall-clock meters × 4 dropped
  hours. There are 24,415 missing values, and the period is 2016-01-01T00:00Z to
  2018-01-01T05:00Z.
- Weather: 156,569 rows, with 96.1–99.98% join coverage per site.
- Every Parquet table re-validates against the contract without warnings.
- Quality:
  - Coverage is 93.02%, and 18 of 20 meters have warnings: gaps 19, missing values 18,
    flatlines 12, low coverage 10.
  - The autumn drop shows as a 2-hour UTC gap.
  - The flatlines show that BDG2's cleaning removes zero runs but not constant non-zero runs.
- **Determinism:** a second run to another folder gave identical SHA-256s for all 7 files.
- **Size:** readings are 1.8 MB as Parquet vs 37 MB as CSV.

**Validation** (Windows)
- ruff: clean. Format: 41 files. `mypy` (strict): no issues in 40 files.
- `pytest -W error`: **212 passed**, of which 15 are new. They run on the mini BDG2-format
  fixture:
  - standard sites use the fixed winter offset in January and July
  - wall-clock sites follow daylight saving
  - 4 unconvertible hours are dropped and counted
  - weather uses its own clock
  - every exclusion reason is produced and counted: not electricity, no metadata, undetermined
    clock, insufficient data, not sampled
  - the seeded sample is reproducible, and the seed matters
  - no eligible meters raises an error
  - byte-identical outputs across runs
  - the Parquet output satisfies the contracts and reads back unchanged
  - the manifest content, and the raw variant
  - the CLI rejects unverified inputs and runs with real site names

**Commit:** `9c534f2` feat(data): add deterministic BDG2 preprocessing pipeline. CI run
[40072783539](https://github.com/shvhjSB/wattwise-ai/actions/runs/40072783539) was green
(212 backend tests, 21 frontend tests).

---

## 2026-10-24 — T010 Leakage-safe split utilities

**Done**
- **`wattwise.ml.splits`** (the first `wattwise.ml` module). Its configs are frozen pydantic
  models that reject unknown fields, naive datetimes, negative gaps and empty or overlapping
  windows:
  - `Chronological`: train / optional validation / test, with an optional gap.
  - `RollingOrigin`: expanding folds with horizon, step, number of folds and gap.
  - `Holdout`: a fraction, a seed, and grouping by building or site.
  - `SplitConfig` combines a time config with an optional holdout and has a SHA-256.
- **`make_split(readings, config, buildings)`** does the following:
  - assigns every reading a role (`train`, `validation`, `test`, `test_unseen`) or one unused
    reason
  - counts a reading only if its whole interval fits its window
  - re-checks each fold on the rows with `verify`, raising `LeakageError`
  - raises an error for any role with no readings
  - stores folds as row positions into the source table, not copies
- **Manifest:** `write_manifest` writes deterministic JSON (config, SHA-256, holdout IDs, and per
  fold the windows, role statistics and unused counts). `read_config` re-creates the config and
  rejects an edited manifest.
- **`infer_interval`** in the quality engine is now public, so both modules share one interval
  rule.
- **Docs:** a new `docs/EVALUATION.md` (method only, no metrics) and D018. A test keeps its role
  and reason tables in sync with the code.

**Performance fix found by profiling.** The first version took 12.1 s for 13 rolling folds on
the BDG2 sample. 8 s of that was iterating Arrow-backed strings in Python, to collect the
buildings per role. Building sets now come from `pd.factorize` codes, and the duplicate check uses
`np.bincount` instead of a sort. Results:
- the BDG2 sample: 0.8 s
- a synthetic 5.3 M-row table, 13 folds plus a holdout: 21 s, down from 137 s

**Observed on the BDG2 sample** (`data/processed/bdg2/cleaned`, 20 meters). These are split sizes
only, not model results.
- **Chronological split:** train 2016-01-01 to 2017-07-01, validation to 2017-10-01, test to
  2018-01-02, site holdout 0.2 with seed 2016.
  - The holdout drew Cockatoo and Peacock: 5 meters.
  - Train 196,825 rows, validation 33,120, test 33,159, test_unseen 11,055.
  - 76,645 held-out readings before the test window are unused; there are no other unused rows.
- **Rolling origin:** from 2017-01-02, 28-day horizon and step, 13 folds.
  - Training grows from 176,030 to 337,272 rows; each test window has 13,440.
  - The last window ends 2018-01-01T00:00Z, so 92 late-UTC rows are outside the windows.
- **The documented example** in EVALUATION.md was executed verbatim on this sample and gave the
  same 196,825 training rows.

**Validation** (Windows)
- `uv lock --check`: pass. ruff: clean. Format: 45 files. `mypy` (strict): no issues in 44 files.
- `pytest -W error`: **260 passed**, of which 48 are new. They cover:
  - role counts for chronological splits with and without validation, the gap and rows outside
    the windows
  - invalid configs, with seven cases
  - UTC normalisation
  - the interval rule: a daily reading across a boundary, 15-minute meters, a single-reading
    meter
  - rolling folds expanding, and a 9-case sweep that tests strictly after training, honours
    the gap and isolates the holdout
  - holdout size limits, the site holdout and its input errors, and the seed (row order
    doesn't matter)
  - determinism: identical manifests from a JSON round-trip of the config, unchanged results
    for shuffled rows, re-creating a split from a saved manifest, and rejecting edited or
    foreign manifests
  - manifest content
  - `verify` catching four kinds of tampering: test rows in training, a row with two roles, a
    held-out building in training, and training after testing in a stretched fold
  - empty roles and non-canonical input
  - the documentation sync test
  - the synthetic fixture with a site holdout

**Commit:** `b088f74` feat(ml): add leakage-safe evaluation splits. CI run
[40075177047](https://github.com/shvhjSB/wattwise-ai/actions/runs/40075177047) was green
(260 backend tests, 21 frontend tests). The local Linux replay also passed (260 tests), after
two attempts that failed on PyPI network timeouts.

---

## 2026-10-24 — T007b Supplementary dataset evaluation

**Why.** The owner asked how complete the data is, then asked for an evaluation of other
datasets to fill BDG2's gaps with the best available data. The task was added to the roadmap
as T007b before any work started.

**Method**
1. **Site geography, from the BDG2 metadata.**
   - 1,449 buildings carry `building_id_kaggle`.
   - The 15 sites with coordinates were reverse-geocoded with OpenStreetMap Nominatim, at one
     request per second with an identifying User-Agent.
2. **Research.** Four parallel research passes (labels; carbon and prices; weather and
   calendar; sub-metered and independent buildings). Each had to cite the primary source for
   every fact and mark anything unverified.
3. **Independent double-checks**, before anything was written down:
   - Repository APIs for licences and sizes: Dryad (Building 59, HKUST), figshare (CU-BEMS),
     PyPI (`holidays`, pvlib) and GitHub (LEAD: no licence, file size, open issues).
   - Open-Meteo's terms and licence pages.
   - The EIA API for AZ, NY and TX commercial prices.
   - Parsing the original files: eGRID2016 Table 1, the DESNZ 2016 flat file, SEAI Energy in
     Ireland 2018, and NIR Table A13-7 for Ontario.
   - Re-running the LEAD-to-BDG2 join check.
   - One correction to a research pass: figshare lists CU-BEMS as 16 files and 742 MB, not
     about 1.48 GB.

**Findings**
- **Metadata problems:**
  - Crow and Moose ("US/Eastern") are in Ontario, Canada.
  - Wolf's longitude sign is flipped. As published it geocodes to the Netherlands; corrected,
    it gives Dublin.
  - Fox's coordinates are in Arizona, which has no daylight saving time. Its audit evidence
    (no profile shift, and real readings at the spring "non-existent" hour) fits `America/Phoenix`
    and explains its "undetermined" verdict.
- **LEAD 1.0:**
  - All 200 public buildings map to BDG2.
  - On a 117-hour sample, 97.6% of 21,804 readings equal BDG2 raw at zero shift; at every other
    shift, at most 14% do.
  - It has 152 usable buildings at sites with a determined clock, and 2016 only.
  - It has no licence on GitHub, and the Kaggle rules forbid redistribution.
- **Carbon and prices:**
  - Annual factors exist for every located region for 2016 and 2017 (eGRID has no 2017
    edition, and EPA says to use 2016).
  - Prices exist for the US, the UK and Ireland. For Ontario, no adequate open retail price
    was found.
- **Weather:**
  - Humidity can be derived from BDG2 itself.
  - Radiation must come from ERA5 reanalysis. The Copernicus CDS needs an account; the
    Open-Meteo free tier is non-commercial only.
- **Sub-metered and independent buildings:** Building 59 (CC0) is the only candidate with end
  uses, HVAC points and measured occupancy. HKUST (CC0) is the best independent set.
- **Cannot be filled:** missing building metadata, academic calendars, and anything
  location-based for the 4 sites without coordinates.

**Records**
- **DATASETS.md:** a new section, "Supplementary data", with the site geography, a
  recommendation per gap and the evidence tables.
- **DECISIONS.md:** D019, plus three open decisions for the owner.
- **Roadmap:**
  - T007b, plus follow-ups T007c, T007d, T009c, T021a, T040 and T041.
  - T013, T018 and T021 now reference the new sources.

**Not done.** Nothing was acquired into the repository or into `data/raw`. The research passes
kept their downloads in the session scratchpad, outside the repository:
- the LEAD sample
- the source files and documentation for the carbon factors and prices
- metadata files for the candidate datasets

**Commit:** `6f0e8b6` docs(data): evaluate supplementary datasets for BDG2 gaps. CI run
[40084149157](https://github.com/shvhjSB/wattwise-ai/actions/runs/40084149157) was green.

---

## 2026-10-24 — T009c BDG2 site metadata corrections

**Exploration first.** Before writing code, I measured daylight-saving fingerprints at every
site's clock-change hours, under its published zone, against the same hour on control days.
- **Wall-clock sites:**
  - Most show at least one fingerprint:
    - empty spring hours: Bear, Bobcat, Cockatoo, Gator, Peacock, Panther in 2017
    - an empty *neighbouring* hour: Bull (03:00 is 100% empty)
    - filled spring hours: Hog (100% copied, against 14% on control days)
    - merged autumn hours: Crow 1.99×, Mouse 1.96×
  - Lamb shows no clean fingerprint, so a missing fingerprint cannot prove anything on its own.
- **Standard-time sites** (Eagle, Moose, Wolf) have no fingerprints either. They are separated
  by occupant behaviour: their schedules shift with the clock changes.
- **Fox** shows neither a fingerprint nor a shift.

**Done**
- **`wattwise.data.bdg2_sites`:**
  - `CORRECTIONS`: Fox `timezone` US/Mountain → America/Phoenix, and Wolf `lng` 6.2603 →
    −6.2603, each with its evidence.
  - `apply_corrections`: refuses data whose published value differs, skips absent sites and
    fields, and never mutates its input.
  - `SITE_REGIONS`: ISO 3166 codes, None for the 4 sites without coordinates.
- **Audit (`bdg2_audit`):**
  - It audits the corrected metadata.
  - A time-zone correction gets a `ZoneCheck` under the published zone:
    - shift evidence, plus per-hour `HourEvidence` with a `fingerprint` property (empty hour,
      empty neighbour, copied or interpolated readings at least 0.2 above the control days, or
      a ratio change of at least 0.25)
    - "no usable shift at all" plus "no fingerprint at all"
  - Zones without transitions get a fixed-offset verdict, or undetermined if the correction is
    rejected.
  - The Fox pin is now `standard`.
- **Helper:** `time_convention.repeated_hours`.
- **Pipeline (`bdg2_prepare`):** version 2. It applies the corrections and records them in the
  manifest.
- **Test fixture:** the builder takes `published_timezones` and `coordinates` overrides,
  through a typed `BDG2Builder` protocol.

**Falsification test.** The zone check was run on the 18 other sites, as if each had been
"corrected" to America/Phoenix.
- The first rule ("no majority of standard-time shifts") wrongly accepted **Robin** (London, one
  shift in four).
- Tightened to "no shift at all", the check rejects all 18:
  - 11 wall-clock sites, by fingerprint
  - 3 standard-time sites, by shift
  - Rat, Robin, Shrew and Swan
- Fox still passes, with lags 0, 0, +1 and 0.

**Real-data results**
- **Audit:** exit 0, all pins match, about 13 s.
  - Fox's clock-change hours, from the audit output: spring 0% and 0.7% empty; copied readings
    2.9% and 2.2%, against 4.4% and 3.5% on control days; autumn ratio 1.00 against 1.00.
- **Pipeline:**
  - Eligible meters: 1,148 (was 1,013). Excluded: 385 undetermined (was 522) and 45
    insufficient data (was 43; 2 of Fox's).
  - The new seeded sample: 20 meters from 9 sites, including Fox 1.
  - 350,816 readings (20 × 17,544 − 16 wall-clock meters × 4).
  - 95.65% coverage. Weather join coverage is 96.75–99.99% per site.
  - A second run gave byte-identical files for all 7 outputs.
- **Splits on the new sample:** train 196,820, validation 33,120, test 33,176, test_unseen 11,055
  (Cockatoo and Peacock held out again). The EVALUATION.md example still runs.
- **Restated docs:** DATASETS.md, EVALUATION.md and PROJECT_STATUS.md now give the version-2
  numbers. D016 and D017 point to D020.
- **LEAD:** usable buildings rise from 152 to 173.

**Validation** (Windows)
- ruff: clean. Format: clean. `mypy` (strict): no issues in 46 files.
- `pytest -W error`: **284 passed**, of which 24 are new:
  - corrections: apply, refuse, skip, input unchanged
  - the target zone has no transitions
  - region coverage, and the geography table in sync
  - `repeated_hours`, and Arizona against US/Mountain facts
  - the zone check:
    - a mislabelled Arizona-like site is corrected and accepted
    - without the correction it is misread as wall-clock
    - corrections are rejected for wall-clock data (fingerprint) and for standard data (shift)
    - only zones without daylight saving can be checked
    - eight fingerprint cases
  - the pipeline:
    - corrections applied before conversion (summer noon becomes 19:00 UTC, no dropped hours)
    - corrections recorded in the manifest
    - mismatched corrections stop the pipeline

**Commit:** `a61da1d` feat(data): correct BDG2 site metadata with a falsifiable zone check. CI
run [40086528467](https://github.com/shvhjSB/wattwise-ai/actions/runs/40086528467) was green
(284 backend tests). The local Linux replay also passed (284 tests), after the replay's uv binary
was re-downloaded and checked against the workflow's pinned SHA-256.

---

## 2026-10-24 — T011 Evaluation harness and metrics

**Done**
- **`wattwise.ml.evaluation`:**
  - `compute_metrics`: MAE, RMSE, bias and guarded WAPE, plus counts of scored rows and of
    missing actual values and predictions.
  - `macro_average`.
  - `evaluate(split, predictions, forecaster)`. It scores each (fold, role) per meter, per
    building, overall and as a macro average, and summarises across folds. It refuses:
    - `train` rows
    - predictions that do not cover exactly the role's rows (missing or extra)
    - unknown folds or roles
    - mixed units
    - a non-unique readings index
  - `fingerprint`: the readings' content, independent of order and index.
  - `code_version`: the package version, plus git commit and dirty flag when run from a checkout.
  - `to_json`, `to_markdown`, `write_report`.
- **Tests:** the readings helpers moved to `tests/ml/conftest.py`, shared by the split and
  evaluation tests.
- **Docs:** EVALUATION.md has a new section, "Metrics and reports"; D021 records the design.

**Smoke run on the BDG2 sample:**
- **Setup:** 13 rolling folds with a site holdout.
- **Speed:** 26 role scores in 2.3 s. The fingerprint of a synthetic 5.3 M-row table took 1.9 s.
- **Determinism:** reports were byte-identical across two runs.
- **Missing predictions:** the placeholder predictor (each meter's training mean) cannot
  predict unseen buildings, and all 3,288 of those rows were reported as missing predictions.
- **Not a result:** the placeholder's metrics are not reported, because it is not a baseline;
  T012 delivers the first real baselines.

**Validation** (Windows)
- ruff: clean. Format: clean. `mypy` (strict): no issues in 49 files.
- `pytest -W error`: **314 passed**, of which 30 are new:
  - **Hand-computed metrics:** errors +1, 0, −2, 0 give MAE 0.75, RMSE √1.25, bias −0.25 and
    WAPE 0.3.
  - **Missing values:** counted, not scored.
  - **WAPE guard:** zero totals, a total below the threshold, a total exactly at the threshold,
    and a custom threshold; negative actual values in the denominator.
  - **Edge cases:** no scored rows; a shape mismatch.
  - **Macro vs pooled:** macro MAE 2.0 against pooled 1.33.
  - **Scoring:** per meter, per building and per role; missing predictions per meter; seen and
    unseen buildings scored separately; the rolling-fold summary.
  - **Refusals:** six dishonest-evaluation cases, mixed units and a non-unique index.
  - **Reports:** provenance fields, byte-identical reports, JSON round-trip, Markdown
    conventions.
  - **Fingerprint:** ignores order and index, changes with any value, timestamp or label, and
    treats signed zeros and NaN consistently.
  - **Code version:** in and outside a checkout.

**Commit:** `0989016` feat(ml): add evaluation harness with reproducible reports. CI run
[40091123402](https://github.com/shvhjSB/wattwise-ai/actions/runs/40091123402) was green
(314 backend tests). The local Docker replay was skipped for speed; GitHub CI is the Linux check.

---

## 2026-10-24 — T007c LEAD 1.0 anomaly labels

**Owner decisions (asked at the end of T011):**
- LEAD may be used locally for evaluation only.
- WattWise is non-commercial.
- M2 is finished before the baselines.

All three are recorded in D022.

**Done**
- **`wattwise.data.lead`:**
  - **The pinned file:** commit `80e13682`, the only commit that touched the data file.
    - The first download matched GitHub's git object id `867c4af6…`, a check independent of
      the SHA-256 then pinned.
  - **`fetch` and `verify`,** reusing `acquisition.ensure`. The manifest
    `data/manifests/lead.json` holds provenance only.
  - **`read_lead`:** checks the columns, 0/1 labels and no duplicate hours.
  - **`prepare_labels`:**
    - joins by `building_id_kaggle` and local time
    - converts to UTC with the audited site clocks
    - gives each excluded row one reason
    - flags whether LEAD's reading agrees with BDG2's raw reading
    - measures the share of anomalies that BDG2's cleaning removed
  - **`write`:** a label table, an exclusion log, a report and a manifest.
  - **CLI:** `prepare` verifies all inputs against the pinned checksums.
- **Test fixture:** BDG2 fixture metadata now has `building_id_kaggle`.

**Two bugs caught by the new tests before any result was kept:**
1. **Clocks became plain strings.** Mapping clocks through a pandas Series turned the `Clock`
   StrEnum into plain strings, and `to_utc` compares by identity, so standard-time sites (Eagle,
   Fox, Moose, Wolf) were silently converted as wall-clock.
   - The first real run showed it: 278 unconvertible hours, more than the 206 possible.
   - Clocks are now looked up in a plain dict; no other code uses this pattern.
2. **A mask assignment** into a pandas Series was replaced by positional numpy assignment.

**Real-data result** (full file, 19 s, byte-identical on a second run):
- **LEAD:** 1,749,494 rows, 200 buildings, 37,296 anomalies.
- **Usable:** 1,438,672 rows, 173 buildings and 31,166 anomalies (2.17%), at 12 sites.
- **Excluded rows:**
  - 236,714 at undetermined-clock sites (Robin and Rat)
  - 73,925 not annotated
  - 183 unconvertible daylight-saving hours
  - 0 unmatched
- **Agreement with BDG2 raw:** 98.41% of rows match, but only 54.06% of anomalies (16,848). At
  differing anomalies, LEAD often holds 1.0, or BDG2 holds 0.
- **Cleaning:** 22.85% of anomalies have no cleaned BDG2 reading.
- **Rules for T018:** use the raw variant, and trust only labels whose readings match.

**Validation** (Windows)
- ruff: clean. Format: clean. `mypy` (strict): no issues in 51 files.
- `pytest -W error`: **328 passed**, of which 14 are new:
  - the join in UTC for a standard-time and a wall-clock site
  - one reason per excluded row, for all four reasons
  - labels only, with disagreeing readings flagged
  - the share of anomalies removed by cleaning
  - the exclusion log
  - malformed files rejected (3 cases), and the file read back
  - byte-identical outputs, with the licence recorded in the manifest
  - the pinned URL
  - CLI `prepare` on BDG2-format files, and missing downloads
  - outputs only in git-ignored folders

**Commit:** `4aadf9b` feat(data): add LEAD 1.0 anomaly labels joined to BDG2 meters. CI run
[40092331016](https://github.com/shvhjSB/wattwise-ai/actions/runs/40092331016) was green
(328 backend tests).

---

## 2026-10-24 — T007d Weather enrichment (ERA5 radiation, derived humidity)

**Approach.** Ultracode was on, so two workflows ran alongside the implementation:
- **Research:** three topics (per-variable time semantics, terms and attribution, formulas),
  each fact re-checked by a skeptic.
- **Code review:** four lenses (time maths, provenance, physics and merge, test adequacy), each
  finding re-checked by a skeptic.

A live probe came first. Open-Meteo returned the ERA5 grid cell, and radiation began in the
hour labelled just after sunrise, which fits "mean of the preceding hour".

**Done**
- **`wattwise.data.era5`:**
  - **Requests:** pinned to `models=era5`, `timezone=GMT`, 2015-12-31 to 2018-01-01, one per
    located site, using corrected coordinates (Wolf).
  - **`fetch` / `verify`:**
    - atomic writes
    - the manifest records the file SHA-256, a content hash that ignores `generationtime_ms`,
      and the grid cell and its distance
    - re-runs only verify; `--force` reports "changed" content; unrecorded files are never
      overwritten
  - **`parse_response`:** checks UTC, units and a regular hourly axis.
  - **`era5_table`:** relabels radiation to interval starts; instants are kept.
  - **`relative_humidity`:** Magnus over water, capped within 0.5 °C, otherwise missing.
  - **Alignment checks:**
    - `equation_of_time_min` (NOAA) and `solar_noon_offsets`, with days grouped in local mean
      solar time
    - `best_lag` for ERA5 temperature against observed temperature
  - **`enrich` / `write`:** a table with provenance in its column names, a report, and a
    manifest with attribution, terms and per-column provenance. `prepare` exits 1 if alignment
    fails.
- **`bdg2_prepare.site_weather`:** made public and reused.

**Research results (verified):**
- Magnus AEKR coefficients 17.625, 243.04 °C and 6.1094 hPa, over water, −40 to 50 °C.
- The NOAA equation of time and solar noon = 720 − 4·lon − EoT, the sign convention
  implemented.
- Attribution: Open-Meteo's credit and link plus a note of changes; the Copernicus
  acknowledgement with its disclaimer; the ERA5 DOI 10.24381/cds.adbb2d47; Open-Meteo DOI
  10.5281/zenodo.7970649. The attribution text was updated to include all of these.
- Call weighting: more than 10 variables or 14 days counts as several calls, about 785 for the
  15 requests.

**Real-data result** (15 sites, 41 s fetch, 6 s prepare):
- Both checks passed everywhere.
  - Solar-noon offset −8.6 to +2.0 minutes; labels taken as interval starts would give +51 to
    +62.
  - ERA5 temperature best lag 0 h at every site, r = 0.954–0.997. This also confirms the D016
    weather clocks independently.
- 334,020 rows. The ERA5 columns are missing only for the 4 sites without coordinates and each
  site's last hour.
- Humidity: 0 set missing, 0 capped.
- Byte-identical on a re-run; the re-fetch only verified.

**Validation** (Windows)
- ruff: clean. Format: clean. `mypy` (strict): no issues in 53 files.
- `pytest -W error`: **356 passed**, of which 28 are new, on synthetic Open-Meteo responses
  from a symmetric clear-sky model:
  - the request is pinned; coordinates are corrected; malformed responses are rejected; the
    content hash ignores the timing field
  - relabelling
  - the equation of time against four known values
  - the solar-noon check: about 0 when right, −60 min when mislabelled
  - `best_lag` sign
  - reference humidity values, and the cap and missing rules
  - aligned and misaligned enrichments
  - deterministic outputs with provenance
  - `fetch`: download, verify, changed, never overwrite, rate limit
  - the CLI `prepare` on BDG2-format files, a missing response, and verification of the BDG2
    inputs

**First commit:** `a624b5d`. Pushed for speed while the review was still running.

**Adversarial review (workflow, four lenses plus skeptics) and fixes:**
- **Acquisition and provenance:**
  - The manifest is now saved after each site; one failure part-way had orphaned the files
    already fetched.
  - A failed alignment no longer overwrites outputs.
  - A response recorded for another request is refused.
  - "changed" is reported only for the same request, keeping the previous hash.
  - HTTP errors carry Open-Meteo's reason; truncated and invalid bodies give clear errors.
  - `grid_elevation_m` was renamed `dem_elevation_m`.
- **The committed manifest held BDG2 site coordinates** (in its fields and URLs), against
  D014. It now stays git-ignored in `data/raw/era5/`, and the committed copy was removed. Commit
  `a624b5d` still contains it; published history is not rewritten, and the values are public
  BDG2 metadata.
- **Physics and table:**
  - Missing-value statistics are now counted only where a source is meant to have values.
  - With no located sites, the run no longer crashes and no longer counts as "aligned".
  - `best_lag` no longer invents a lag without overlap, and NaN is refused in JSON.
- **Time maths:** the gate used one two-year median, and the reviewer reproduced a one-hour
  mislabel over a third of the period that still passed.
  - Both checks now also run per calendar quarter.
  - The first quarterly run failed Panther 2017Q3 (−15.6 min, convective afternoon clouds) and
    Crow/Moose in 4 quarters (whole-hour lag −1 against 0).
  - Measurement showed those lags were ties (correlation margins of 0.0001–0.0007). The true
    phase there is about −0.5 h, where a whole-hour test cannot resolve a one-hour error.
  - **The redesign:**
    - The solar tolerance became 30 min, half the one-hour error being caught.
    - The temperature check uses a fractional phase (a parabola through the correlation peak).
      Each quarter must lie within 0.5 h of the site's median, which must lie within 1 h of
      zero.
    - Measured natural spread: 0.33 h at most.
  - The known limit (a whole-period error at a site with phase near ±0.5 h) is documented;
    D016 covers it.
- **Real data after the fixes:**
  - The forced re-fetch returned identical content for all 15 sites.
  - All 15 sites passed with 8 quarters each.
  - ERA5 has zero real gaps (only the 15 final hours, by design).
  - Humidity: 328 observations lack inputs.
  - Byte-identical on a re-run.
- `pytest -W error`: **369 passed.** The new tests cover:
  - a partial-period mislabel caught per quarter
  - a one-hour temperature shift in one quarter
  - half-hour phase resolution
  - no invented lag
  - no located sites
  - per-site manifest progress
  - "changed" only for the same request
  - HTTP error reasons
  - broken responses
  - the manifest kept out of git
  - failed alignment writing nothing
  - a stale request refused

**Fix commit:** `121f106` fix(data): harden ERA5 alignment checks and keep its manifest local.
CI run [40115382404](https://github.com/shvhjSB/wattwise-ai/actions/runs/40115382404) was green
(369 backend tests). The research workflow later confirmed the per-variable semantics
implemented: radiation is a preceding-hour mean; cloud cover and temperature are instants; all
times are UTC. Two of its skeptic checks failed on a session usage limit.

---

## 2026-10-24 — T012 Seasonal and historical baselines

**Done**
- **`wattwise.ml.baselines`:**
  - **`SeasonalNaive`:** the reading 168 h earlier. A lag of 0 or less is refused.
  - **`HourOfWeekProfile`:** a median from training rows only, in local wall time, with a
    meter-median fallback. Meters without training data get no forecast.
  - **`run`:** fits on each fold's training rows, predicts without the target values, and
    scores with the T011 harness.
  - **`common_rows_comparison`:** compares the baselines on the rows they all predict.
  - **CLI:** split dates can be overridden, and must carry a time zone. It writes per-baseline
    JSON/Markdown reports and `common_rows.json`.
- **Fix:** `code_version`'s dirty flag missed new, untracked files. The first baseline report
  claimed "clean" while the module was uncommitted. It now uses `git status --porcelain`; data
  stays git-ignored.

**Result (BDG2 sample, 20 meters, cleaned; data fingerprint `e2fc43c651eb2a03`; split
`dbcada8c8242`)**
- **Test (Oct–Dec 2017):**
  - Seasonal-naive: MAE 8.763, RMSE 17.987, bias +0.833, WAPE 8.6%, with 466 rows without a
    prediction.
  - Profile: MAE 10.888, RMSE 18.961, bias +1.385, WAPE 10.7%.
- **On the 43,247 common test rows:** 8.763 against 10.918.
- **Validation:** seasonal 8.886 against profile 12.792. The profile over-predicts (bias
  +3.078), since it averages winter and summer weeks.
- **Determinism and speed:** byte-identical on a re-run; about 5 s.

**Validation** (Windows)
- ruff: clean. Format: clean. `mypy` (strict): no issues in 55 files.
- `pytest -W error`: **383 passed**, of which 14 are new:
  - seasonal-naive repeats last week; it is unchanged when the present and future change; there
    is no forecast without last week
  - the profile uses only training rows (tampered test values change nothing)
  - local time across daylight saving: a UTC profile is wrong after the change
  - fallback, and no forecast for unknown meters
  - perfect scores on a purely weekly load
  - the common-rows comparison
  - the synthetic fixture end to end
  - CLI reports, missing data, and dates without a time zone
  - the default split order

**Commit:** `c856177` feat(ml): add seasonal-naive and hour-of-week baselines with first
results. CI run [40116527334](https://github.com/shvhjSB/wattwise-ai/actions/runs/40116527334)
was green (383 backend tests). A re-run at the commit reproduced every number, and the report
was stamped clean at `c856177`.

---

## 2026-10-24 — T007d follow-up: the rest of the code review

The T007d review workflow finished after T012. Its provenance skeptic confirmed the findings
already fixed in `121f106`. Its tests lens confirmed five more against the original code; four
were still open:
1. **A uniform one-hour weather-clock error could pass.** At a site with natural phase 0 it sat
   exactly on the 1 h limit. The site limit is now 0.75 h: halfway between the largest natural
   phase (0.5 h) and that error. The real data still passes (largest |phase| 0.50 h). A new test
   shows the error is caught.
2. **The "instants keep their time" check was vacuous**, because synthetic cloud cover was
   constant. It now varies by hour, and the test checks the exact hour.
3. **The ERA5 integrity check and the verify success path were untested.** The integrity check
   was also skipped together with BDG2 verification. The ERA5 checksum is now always checked, and
   `verify` takes `--skip-input-verification` for BDG2 only. A new test passes `verify`, then
   alters the file and sees `verify` and `prepare` refuse it.
4. **The "different request" test returned identical content**, so it passed without the guard.
   It now uses different content. The "changed" test now checks that the previous content hash is
   kept.

The fifth (the "only" in the content-hash test name) was judged not real. Real data after the
fix: `prepare` passed (alignment passed), and `verify` passed (15 responses).
`pytest -W error`: **385 passed**.

---

## 2026-10-24 — T013 Leakage-safe feature engineering

**Done**
- **`wattwise.ml.features`:** feature set 1, 32 float features in five groups (D025,
  [FEATURES.md](FEATURES.md)).
  - **Calendar:** local wall time per building (hour, day of week, weekend, month, day of year,
    cyclic encodings).
  - **Holidays:** `holidays` 0.106 with the T009c regions; NaN where the region is unknown.
  - **Weather:** observed BDG2 values at the interval start, a 24-hour temperature mean
    (needs 12 observations), 18 °C degree hours, and T007d humidity and ERA5 irradiance and
    cloud cover. Flags: `weather_observed`, `era5_available`.
  - **Sun:** elevation at mid-interval, daylight, day length on the local date.
  - **History:** lags of 1 and 2 weeks, the same-hour mean of 4 weeks, rolling mean, standard
    deviation and minimum over windows ending H hours before the target (H 1–168, default 168).
  - **CLI:** writes `features.parquet` and a manifest (version, rules, provenance, hashes,
    missing shares) to git-ignored `data/processed/features/`.
- **`wattwise.data.solar`:** NOAA sun position. The equation of time moved here from the ERA5
  module unchanged; declination, elevation and day length are new.
- **Dependency:** `uv add "holidays>=0.106,<0.107"`. 0.106 was released 2026-10-06, 18 days
  ago; 0.107 is too new. It needs `python-dateutil<3`, so dateutil went from 3.0.0 (released
  2026-10-21, which had not met the two-week rule) to 2.9.0.post0. pandas needs only >=2.8.2.
- **pvlib not added.** A one-off check in a throwaway environment (`uv run --no-project
  --isolated --exclude-newer 2026-10-10 --with pvlib`, giving pvlib 0.16.1) compared our
  equations with pvlib's NREL SPA, hourly over 2016–2017, at six generic points (40N 75W,
  51.5N 0.1W, 33.4N 111.9W, 33.9S 151.2E, 0N 0E, 65N 25E). Elevation: max |diff| 0.52°, mean
  0.12–0.28°. Day length: max 5.2 min (latitudes up to 51.5°).

**Real data (BDG2 sample, pipeline version 2, ERA5 enrichment)**
- **Size and speed:** 350,816 rows × 32 features; 6.6 s in Python, 9.7 s for the CLI.
- **Determinism:** byte-identical on a re-run (`features.parquet` sha256 `cf2f88e1…`), and
  identical after shuffling the rows.
- **Leakage check:** every reading from 2017-07-01 was rewritten. For horizons 1, 24 and
  168 h, the first changed row was exactly the cutoff plus the horizon, and nothing changed
  earlier.
- **Missing:** 25.00% for sun, holiday and ERA5 features, all from Eagle (15% of rows) and
  Gator (10%), which have no coordinates and no region. Observed weather 0.55–0.76%; humidity
  0.61%; 24-hour mean 0.10%; history 4.98–6.26%.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 59
  files.
- `pytest -W error`: **439 passed**. 54 are new (the 4 equation-of-time cases moved to
  `test_solar.py`):
  - **Leakage:**
    - rewritten readings change nothing before cutoff + H, at H = 1, 24 and 168 h, with the
      first change exactly at cutoff + H
    - a reading never changes its own row
    - later weather changes nothing earlier
    - conditions do not depend on consumption
  - **Definitions:** lags, the four-week mean and rolling statistics match a hand calculation;
    gaps, short windows and the first week give NaN.
  - **Missing:** missing weather is NaN with flags; ERA5 per site; no tables means all missing;
    the 24-hour mean needs 12 of 24.
  - **Calendar and holidays:** local time across the New York spring change and in Phoenix;
    holidays by local date (US-CA, GB-ENG, IE, CA-ON, US-DC); unknown region NaN; an unknown
    country is an error.
  - **Sun:** noon elevation at solstices and equinox; London and the equator day length;
    polar day and night; missing coordinates.
  - **Other:** determinism and row order; input checks; group selection; config bounds; the
    manifest; FEATURES.md in sync; the CLI writes identical outputs and reports what is missing.
- The frontend was not re-run locally: no frontend file changed. CI runs it.
---

## 2026-10-25 — T014 ML forecaster vs baselines

**Inputs checked first.** Before any training:
- The BDG2, ERA5 and LEAD raw files all passed their pinned checksums (`verify`).
- Every processed output matched its manifest hash (BDG2 pipeline version 2, ERA5 with
  alignment passed, LEAD, features).
- The feature manifest's inputs matched the current files.

**Done**
- **`wattwise.ml.models`:** a `FeatureModel` with the baselines' `fit`/`predict` interface,
  so the T011 harness scores it unchanged.
  - **Families:** ridge, HistGradientBoosting, LightGBM.
  - **Variants:** `full` (target divided by the meter's mean over the week ending 168 h
    before; no meter identity) and `conditions` (no history; training mean and training
    hour-of-week median as a ratio).
  - **Rules:** everything is fitted on training rows. Columns with no training value are
    dropped. Rows without a usable scale (missing, or below 0.01) get no prediction.
    Predictions are clipped at zero.
  - **Study:** grid on validation, then the chosen settings scored once on test, plus building
    and site holdouts (25%, seed 0) for unseen buildings. A written adoption decision.
  - **CLI:** `comparison.json`, `comparison.md` and T011 reports per model and split.
- **Dependencies:** `uv add "scikit-learn>=1.9.1,<1.10" "lightgbm>=4.7,<4.8"`.
  - Added: scikit-learn 1.9.1 (2026-09-10), LightGBM 4.7.0 (2026-07-18), scipy 1.18.1,
    joblib 1.6.0, threadpoolctl 3.7.0, cloudpickle 3.1.2, narwhals 2.27.1 (2026-10-10,
    exactly 14 days).
  - A mypy override marks scikit-learn as untyped (it has no `py.typed`).
- **Fixed during the task:** HistGradientBoosting crashed on a feature that was missing in
  every training row (the synthetic tests have no ERA5). Such columns are now dropped at fit.
  Models also share the feature table instead of copying it.

**Result (BDG2 sample, same split as T012; about 5 minutes)**
- **Validation winner:** LightGBM full, 200 trees (MAE 7.570). Best per family: HGB full
  7.679, ridge full 8.391, LightGBM conditions 10.920, HGB conditions 11.007, ridge conditions
  13.570.
- **Test (scored once):** LightGBM full MAE 7.490 (seasonal-naive 8.763). On the 43,000
  common rows, 7.486 against 8.764 (**−14.6%**). Better on 17 of 20 meters; macro MAE 7.43
  against 8.71.
- **Unseen buildings** (LightGBM full against seasonal-naive):
  - building holdout (5 buildings at Eagle, Gator and Hog): +0.1%
  - site holdout (Hog and Lamb): −14.4%
  - So not adopted for unseen buildings.
- **No-history models:** 15–37% worse than seasonal-naive on test.
- **Decision (D026):** LightGBM full adopted for seen buildings; seasonal-naive stays for
  unseen buildings.
- **Determinism:** a second full run gave byte-identical files (44 of 44).

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 61
  files.
- `pytest -W error`: **467 passed**, 28 new, on a synthetic weather-driven load (labelled
  synthetic):
  - every family and variant beats seasonal-naive by more than 20% there
  - predictions are deterministic and never negative
  - conditions models are unchanged when every value outside training is rewritten
  - full models are unchanged before cutoff + 168 h when later readings are rewritten
  - unknown meters, unusable scales and unfitted models are handled
  - names and parameters
  - the conditions variant has no history inputs
  - grid choice on validation, with no test in the trials
  - the decision on common rows and unseen buildings
  - conditions models give no unseen predictions
  - summary and Markdown
  - the CLI without data

---

## 2026-10-25 — T015 Model artifacts, metadata and registry

**Done**
- **`wattwise.ml.registry`** (D027, [MODELS.md](MODELS.md)):
  - **`train`:** fits the D026 model (LightGBM, all features, 200 trees) on the split's training
    rows and scores validation and test with the T011 harness. The artifact is exactly the
    evaluated model.
  - **`save`:** writes `model.txt` (LightGBM text), `state.json` and `metadata.json` to a
    staging folder, flushes each file, and renames it to `<created_at>-<model hash>`. A failure
    removes the staging folder. Versions are never overwritten, and only LightGBM can be saved
    (no pickle).
  - **`promote`:** verifies, then replaces `CURRENT` with an atomic rename. Old versions stay
    for rollback.
  - **`load` and `verify`:** check hashes, strict metadata, artifact and feature-set versions,
    the feature table's columns, and the version name (no path escapes). Without a promoted
    model, `load` raises `NoModelError`.
  - **`reevaluate` and CLI:** `train [--promote]`, `evaluate` (must reproduce the recorded
    metrics exactly on the same data; reports when the data differ), `list`, `promote`.
- **Small refactors:**
  - `FeatureModel.usable` is public.
  - `baselines._utc` became `utc_argument`.
  - `models.overall` has a precise return type.
  - The synthetic model-test load moved to `tests/ml/conftest.py`.

**Real data (BDG2 sample)**
- **Before training:** `list` gave "no saved models"; `evaluate` exited 1 with "No model has
  been promoted".
- **`train --promote`:** about 22 s. Saved `20261025T070227Z-4cf91609c9ef` (720 KB model
  text), with validation MAE 7.570092 and test MAE 7.490129, equal to T014.
- **`evaluate`:** "data: same as training"; both metrics reproduced exactly from disk.
- **`list`:** one version, marked current.
- `git status` shows nothing from `artifacts/`.
- This artifact was trained from uncommitted code. After the commit, a retrain is promoted so
  the current artifact carries a clean code stamp.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 63
  files.
- `pytest -W error`: **486 passed**. 19 are new, on the synthetic load:
  - **Round trips:** predictions are identical after save and load (full and conditions
    variants), and re-evaluation reproduces the metrics.
  - **Metadata:** content checked.
  - **Pickle refusal:** ridge cannot be saved.
  - **No model:** a missing folder, saved but not promoted, and an empty `CURRENT`.
  - **Promotion:** promotion and rollback; versions are never overwritten.
  - **Failed writes:** a failed save (second file) leaves nothing, and a failed promotion
    (rename) keeps the current model.
  - **Integrity:** a tampered model cannot be promoted or loaded, and an unknown version is
    refused.
  - **Names:** path-escaping names are refused.
  - **Compatibility:** another feature set, a missing feature column, and invalid metadata are
    refused.
  - **CLI:** list, evaluate without a model, train and promote, evaluate reproduced, evaluate on
    changed data, bad promote.
  - **Ignore rule:** artifacts are git-ignored.

---

## 2026-10-25 — T016 Residual-based detector and event grouping

**Done**
- **`wattwise.ml.detection`** (D028, [DETECTION.md](DETECTION.md)):
  - **`calibrate`:** per meter, the median and 1.4826 × MAD of model residuals, and of
    reference (one-week-earlier) residuals, on calibration rows only. Floor: 1% of the mean
    absolute reading.
  - **`detect`:** a hysteresis state machine per meter and direction. It opens at z ≥ 4,
    continues at ≥ 2, bridges gaps of up to 2 h (low scores or missing hours), and keeps an
    event with at least 3 flagged hours or a z ≥ 8 spike. After 168 h it scores against the
    meter's reading at the same hour in the last week before the event.
  - **Event fields:** start, end (exclusive), duration, flagged, missing and reference hours,
    peak time, z and residual, residual sum, and whether it is ongoing.
  - **`run_detection` and CLI:** loads the promoted model, calibrates on its validation window,
    and detects in its test window. Writes `events.csv`, `scores.parquet`, `summary.json` and
    `report.md`, and refuses clearly when no model is promoted.
- `registry.read_inputs` is public.

**Real data (BDG2 sample; promoted model `20261025T070700Z-4cf91609c9ef`; about 13 s)**
- **Coverage:** 43,298 of 44,231 detection hours scored (Oct 2017 to 1 Jan 2018).
- **Events:** 355 (185 high, 170 low), 5,147 event hours (11.9%). Per meter 2–62 (median 15);
  19 of 20 meters. Median duration 8 h; 32 events of a day or more; 44 kept as spikes.
- **Pre-event reference:** used by 3 long events (Hog_parking_Marcus 480 h,
  Lamb_education_Lawrence 318 h, Eagle_lodging_Andy 241 h).
- **Plausible patterns (hypotheses):**
  - Gator whole-day low events on 1 Oct, 10 Nov (Veterans Day observed) and 30 Dec, where the
    region is unknown, so there are no holiday features.
  - Lamb's 318 h drop with a peak z of 407 (likely a meter or data fault).
- **Calibration check:**
  - |z| ≥ 4 in 2.98% of calibration hours (heavy tails), and 7.18% of detection hours
    (seasonal drift).
  - Thresholds are deliberately not tuned on the test quarter; T018 and T019 address this.
- **Determinism:** a second run gave byte-identical outputs (4 of 4 files).

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 65
  files.
- `pytest -W error`: **505 passed**. 19 are new, mostly on residuals with exactly known
  scores:
  - **Calibration:** only its rows count, and the scale floor applies.
  - **Thresholds:** nothing below `z_on`; persistence versus spikes.
  - **Hysteresis:** an event continues between the two thresholds.
  - **Merging:** gaps of 2 h merge and 3 h split; also with `max_gap_hours=0`.
  - **Missing hours:** bridged and counted.
  - **Directions:** high and low are separate.
  - **Event fields:** extent, peak and residual sum; an event at the window end is ongoing.
  - **Long events:** a 3-week step the model absorbs after a week stays one 504 h event with
    the reference, and is cut at 168 h without it.
  - **Configuration and order:** invalid thresholds; row-order independence; no scores without
    calibration.
  - **With the promoted model:** a 2-day injected surge is found as exactly one event, matching
    the injected window.
  - **CLI:** byte-identical outputs, and a clear error without a model.

---

## 2026-10-25 — T017 Anomaly signature rules

**Done**
- **`wattwise.ml.signatures`** (D029):
  - Six rules, each returning matched plus its measurements: `data_fault`, `flatline`, `spike`,
    `overnight_excess`, `drift`, `sustained`; otherwise `unclassified`.
  - **Primary signature:** the first match, with meter problems first.
  - **Evidence:** every rule's measurements and thresholds as JSON, with NaN written as null.
  - **Configuration:** `SignatureConfig`. Flatline and zero-run lengths come from T008's
    `QualityThresholds`; night hours are 22:00–05:59 local.
  - **Descriptions:** name patterns only, and a test checks them for causal words.
- **Detector:** `Detection.hours` gives every event hour (reading, baseline used, score), so the
  rules see exactly what the detector saw, including the pre-event baseline.
  `run_detection` takes the buildings table and returns classified events. The CLI writes
  signatures to `events.csv`, `summary.json` and `report.md`.

**Real data (BDG2 test quarter, same 355 events)**
- **Primary signatures:** `data_fault` 4, `flatline` 12, `spike` 80, `overnight_excess` 9,
  `drift` 0, `sustained` 19, `unclassified` 231.
- **All matches:** spike 82, sustained 32, overnight excess 22, flatline 13, data fault 4.
- **`data_fault`:** all 4 are implausible deviations (peak z 52–407; Bull ×3 and Lamb).
- **Correction to T016:** Gator_public_Geraldine's whole-day lows (1 Oct, 10 Nov, 12 Dec) have
  one value for every hour in BDG2's **raw** file too (3.3333 and 8.3333 kWh, which are 80/24
  and 200/24). That is consistent with daily totals spread evenly over the day, not holidays.
- **Determinism:** a rerun gave byte-identical outputs (4 of 4 files).

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 67
  files.
- `pytest -W error`: **521 passed**, 16 new:
  - Every rule has positive and negative cases:
    - **data fault:** negatives; a zero run of 24 against 23; 60% against 40% missing; z 60
      against 49
    - **flatline:** 10 h, 5 h, a 6-of-20 h share, and zeros
    - **spike:** 3 h against 4 h
    - **overnight:** night, day, and low
    - **drift:** rising, constant, too short, and a deepening low
    - **sustained:** full, half-flagged, and 20 h
  - **Precedence and labels:** precedence; unclassified; evidence JSON with nulls.
  - **Shared settings:** thresholds shared with the quality engine; no causal words.
  - **End to end:** detector events in New York local time (overnight, then spike).
  - **Docs:** DETECTION.md lists every signature.
  - The first end-to-end run labelled a perfectly constant injected night excess `flatline`,
    which the rule should do. The test now injects a varying excess.

---

## 2026-10-25 — T018 Injected-anomaly benchmark

**Roadmap first.** T018 was split:
- **T018:** the injected benchmark and tuning.
- **T018b (new):** LEAD human labels. They cover 2016, inside the model's training period, so
  they need a model trained on H1 2016 and scored on H2 2016.
- **Synthetic fixture:** too short (8 weeks) to train, calibrate and detect out-of-sample.
  Synthetic injections are covered by tests on the 100-day synthetic load instead.

**Done**
- **`wattwise.ml.benchmark`** (D030):
  - **Injections:** seven patterns relative to each meter's calibration median: spike, sustained,
    long sustained, overnight (local), drift, flatline and dropout. `plan` is seeded, places one
    injection per meter per replicate, rotates patterns, and records anything that does not fit.
  - **Replicates:** each rebuilds the features, so the model's history sees the injection.
  - **Scoring:** found if an event of the same meter overlaps; latency, coverage, event count,
    and the signature of the largest-overlap event; alerts outside injections.
  - **Tuning and evaluation:** a 16-setting grid per detector in the first third of the test
    window, chosen by best mean recall within an alert budget. Evaluated once on the rest, plus
    an uninjected run.
  - **Reports:** `benchmark.json` and `benchmark.md` in git-ignored `data/processed/benchmark/`.
- **`wattwise.ml.detection`:**
  - `rolling_same_hour` (the same hour on the previous 14 days, past only), the `Detector` enum
    and per-detector defaults.
  - `detect(z=...)` accepts precomputed scores without a calibration.
  - The CLI takes `--detector`, defaulting to `rolling-z`, and records the detector and settings.

**Real result (BDG2 sample; promoted model; 12 replicates per window; about 6.5 min)**
- **Tuning (Oct 2017, 240 injections):**
  - Model detector chosen: open 4, continue 3, 6 h. Recall 80% at 0.497 alerts per meter-week.
  - Rolling-z chosen: open 4, continue 2, 3 h. Recall 75% at 0.176.
  - Below 0.27 alerts the model detector has no setting at all.
- **Evaluation (Nov–Dec, 240 fresh injections, scored once):**
  - Model: 81% recall at 0.968 alerts per meter-week (0.971 without injections).
  - Rolling-z: 72% at 0.388 (0.457).
  - Model with the T016 defaults: 87% at 1.462.
- **Per pattern (model / rolling-z recall):** spike 76/56, sustained 85/71, long 89/86,
  overnight 91/83, drift 85/76, flatline 44/41, dropout 97/94.
  - Drift is labelled `drift` only 3% / 0% of the time.
  - Overnight coverage is 27% for the model.
- **Decision:** the rule as first coded (budget checked in tuning only) said "keep". It was
  tightened after the evaluation run to require the budget in evaluation too, and both
  results are reported. Under the corrected rule the model detector is not kept as the
  default, so the detection command now defaults to `rolling-z`.
- **Synthetic surge check:** the rolling z-score misses the weather-masked +60% 2-day surge
  (max z 2.31, against a 95th percentile of 2.11 on that meter). The model detector finds it
  exactly. A test pins both.
- **Detection with the new default:** 100 events (65 high, 35 low), 916 hours (2.1% of 43,545
  scored hours), 0.38 per meter-week. With `--detector model`: 207 events, 3,366 hours.
- **Determinism:** the benchmark rerun reproduced tuning, choices and evaluation exactly. The
  detection rerun was byte-identical.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 69
  files.
- `pytest -W error`: **538 passed**. 17 are new or changed:
  - **Benchmark (16):**
    - plan determinism, window bounds and rotation; skipping
    - each injection's exact effect (spike, local overnight, drift ramp, flatline and dropout
      keeping missing readings)
    - the rolling z-score's formula, its past-only behaviour and the 7-day minimum
    - `detect` with precomputed scores and its errors
    - overlap scoring (latency, coverage, two events, signature)
    - misses and outside alerts; summaries
    - the budget-constrained choice
    - windows from the model's split
    - a full reproducible run
    - the CLI
    - the stricter decision rule
  - **Detection:** the model-path test now asks for the model detector explicitly. New tests
    cover the default rolling detector (no calibration, and its weather-masked miss) and the
    CLI's `--detector`.

---

## 2026-10-25 — T018b Detector check against LEAD human labels

**Done**
- **Raw BDG2 for every eligible meter:** `bdg2_prepare --variant raw --sample-meters 0` gives
  1,171 eligible meters and 20,540,488 readings, in 103 s, git-ignored. LEAD labelled raw
  readings. This is an existing command; nothing in the pipeline changed.
- **`wattwise.ml.lead_check`** (D031):
  - **Setup:** LEAD's 173 meters; the adopted model settings trained on Jan–May 2016;
    calibration in June; both detectors with their T018 settings; detection Jul–Dec 2016.
  - **Context:** the check model is compared with seasonal-naive.
  - **Scoring:** trusted labels only, at three levels:
    - **hours:** precision, recall and F1, against the chance rate
    - **segments:** runs of labelled hours, by length
    - **events:** true, false or unjudged
  - **CLI:** writes `lead_check.json` and `lead_check.md` to git-ignored
    `data/processed/evaluation/lead_check/`.

**Real result (about 3 min; rerun byte-identical)**
- **Data:** 1,522,723 raw readings. 728,575 label rows in the detection window (10,989
  untrusted). 717,586 trusted hours, of which 10,484 are anomalies (chance 1.5%). 2,089 trusted
  segments, median 1 h (1,465 last 1–2 h).
- **Check model:** 561,210 training rows. Test MAE 22.07, against 19.72 for seasonal-naive
  (22.08 against 19.57 on 747,207 common rows): **worse** than seasonal-naive. Five months of
  winter and spring do not carry over to the second half of the year.
- **Rolling-z** (1,970 events, 0.43 per meter-week):
  - hour precision 11.5%, recall 13.8%, F1 12.6%
  - segment recall 18.9% (13.0% / 31.9% / 36.4% by length)
  - events: 344 true, 1,174 false, 452 unjudged; precision 22.7%
- **Model** (6,174 events, 1.35 per meter-week):
  - hour precision 4.5%, recall 20.9%, F1 7.4%
  - segment recall 21.2% (16.0% / 31.9% / 43.2%)
  - event precision 7.1%
- **Reading:** little agreement with these labels, but well above chance. Most labels are 1–2 h,
  which the persistence rules mostly ignore. Nothing was tuned on them. The rolling score is
  the more precise detector here too (D030).

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 71
  files.
- `pytest -W error`: **544 passed**, 6 new:
  - flagged hours per meter
  - segments by run and meter
  - exact hour, segment and event counts on crafted trusted and untrusted labels (including
    unjudged events)
  - the no-event case
  - a synthetic end-to-end check: the model detector finds the labelled surge, and the rolling
    score misses it (D030)
  - the CLI without data

---

## 2026-10-25 — T019 Prediction intervals

**Owner question answered first** ("is model training done, is the project on plan").
- **Training is done** for the 20-meter sample: LightGBM, −14.6% MAE against seasonal-naive,
  promoted and reproducible.
- **Gaps:** the model does not generalise to unseen sites; there were no intervals before this
  task; the model detector lost to a rolling z-score (D030); agreement with LEAD labels is low
  (D031); nothing has run at scale.
- **Plan:** 24 of 48 roadmap tasks done, but the API and UI are still a shell.
- **Suggested to the owner:** a thin end-to-end slice before the M7/M8 polish, and a scale-up
  evaluation.

**Roadmap:** T019 was split. T019 covers intervals; T019b (new) re-benchmarks the model
detector with the season-adaptive scale.

**Done**
- **`wattwise.ml.intervals`** (D032):
  - `conformal_quantile`: the finite-sample ⌈(n+1)(1−α)⌉-th order statistic.
  - `fit` and `Intervals.bounds` for the absolute and relative (level-scaled) methods.
  - `rolling_bounds`: daily per-meter recalibration from the 28 days ending 7 days before, from
    out-of-sample scores only.
  - `assess`: coverage overall, per month (months under 1,000 rows reported but not deciding)
    and per meter; width, relative width and the Winkler interval score; the "calibrated" rule
    (±2 points).
  - A CLI on the promoted model.
- **Bug found while testing:** `rolling_bounds` compared microsecond `asi8` with nanosecond
  `Timestamp.value`, so no window matched and the first real run gave no rolling intervals.
  Fixed, and covered by tests.

**Real result (BDG2 test quarter; promoted model; about 20 s; rerun byte-identical)**
- **Calibration window:** 80.1, 90.1 and 95.1% for the fixed methods, as constructed.
- **Test coverage at 80 / 90 / 95% nominal:**
  - absolute: 72.8 / 83.3 / 89.0%
  - relative: 75.6 / 85.8 / 91.7%
  - rolling: 77.2 / 86.7 / 91.7%
- **By month at 90%:**
  - absolute: Oct 88.9, Nov 80.4, Dec 80.4
  - relative: 90.1, 83.8, 83.3
  - rolling: 90.7, 82.0, 87.3
- **Worst / best meter at 90%:** absolute 44.7 / 99.5; relative 56.2 / 99.3; rolling 76.4 / 93.2.
- **Width at 90%:** absolute 34.4 kWh; relative 36.7; rolling 33.0 (32% of the mean reading).
  Interval scores 64.3 / 60.7 / 59.0.
- **None is calibrated.** Rolling is adopted as the default, always shown with its measured
  coverage.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 73
  files.
- `pytest -W error`: **554 passed**, 10 new, on synthetic data with known noise:
  - the order statistic and too-few-scores case
  - fixed intervals cover 90% when nothing changes
  - a level doubling breaks absolute but not relative intervals
  - missing prediction or scale, clipping and unknown meters
  - rolling recovers after the noise itself doubles, where fixed relative under-covers
  - rolling ignores everything inside its 7-day lag, but not older scores
  - the minimum number of scores
  - exact assessment counts, the interval score and months
  - a run on the promoted model; the CLI

---

## 2026-10-25 — T019b Season-adaptive model detector, re-benchmarked

**Done**
- **`detection.adaptive_scores` and `--detector model-adaptive`:** the relative residual
  (actual − expected) / recent level, centred and scaled by its median and 1.4826 × MAD over the
  meter's 28 days ending 7 days before each day. Only out-of-sample residuals count, and the
  scale floor is 1%. Long events keep the pre-event reference.
- **`intervals.daily_window_statistics`:** a shared daily rolling-window helper. T019's
  `rolling_bounds` now uses it, and its tests pass unchanged.
- **Benchmark:** three detectors, with a decision per candidate against the rolling z-score.
  The Markdown shows recall and signature match per pattern for each.
- **LEAD check:** pinned to the two detectors it was defined for (`CHECKED_DETECTORS`). A rerun
  confirmed its outputs are unchanged.

**Real result (T018 procedure unchanged; about 8 min)**
- **Reproduced:** rolling-z and the static model detector matched T018 exactly (tuning, choice
  and evaluation).
- **model-adaptive:**
  - **Tuning:** chosen open 5, continue 3, 3 h. Recall 69% at 0.49 alerts per meter-week.
  - **Evaluation:** 69% at 0.71 (0.81 without injections), against a budget of 0.5. Recall
    falls below rolling-z (72%).
  - **Per pattern:** spike 65, sustained 74, long 83 (coverage 43%), overnight 77, drift 74,
    flatline 24, dropout 85.
- **Decision (D033):** not adopted; the rolling z-score stays the default.
  - The out-of-season alert growth falls from ×1.9 (static) to ×1.45.
  - Hypothesis for the recall loss: the scale window absorbs anomalies after its 7-day lag.
- **On the BDG2 test quarter:** 194 events and 2,202 hours (rolling-z: 100 and 916; static
  model: 207 and 3,366). The default detection outputs are unchanged.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 73
  files.
- `pytest -W error`: **556 passed**. New: adaptive scores (exact value, the 14-day warm-up,
  the 7-day lag ignored), the CLI with `--detector model-adaptive`, and per-candidate decisions.
  Two benchmark assertions were updated to expect three detectors.
- On the first full run, one LEAD-check test failed: its loop picked up the new detector.
  Fixed by pinning its detectors.

---

## 2026-10-25 — T020 Alert explanations

**Done**
- **`FeatureModel.contributions`:** LightGBM's exact TreeSHAP (`pred_contrib`) per hour, scaled
  to kWh, plus a bias column. They add up to the expected value before clipping (tested), and
  return None for families without tree contributions.
- **`wattwise.ml.explanations`** (D034): an evidence bundle per event, covering:
  - the event, the detector's comparison, the model's expectation
  - the rolling 90% interval, with its coverage measured in the same detection window
  - whether the model agrees
  - the signature evidence, the top 5 influences, and a check by signature and direction

  `render` produces the plain-language text. A forbidden-phrase guard (causes, certainty,
  "waste") is enforced in tests and in the CLI. The CLI writes `explanations.json` and
  `explanations.md`.
- **No `shap` dependency:** LightGBM computes the same TreeSHAP values natively.

**Real data (BDG2 test quarter, default detector; about 18 s; rerun byte-identical)**
- **Explained:** all 100 events; 99 with a model expectation and influences. The interval's
  measured coverage in the window was 86.7%.
- **Model agreement:** agrees with the detector on 78 events, disagrees on 20 (every hour inside
  its interval, which the text now states), and is undefined on 2.
- **Most common top influence:** `same_hour_mean_4w` (66), `day_of_year_local` (13),
  `is_public_holiday` (8), `lag_168h` (7).
- **A wording fix during the task:** "for 2017-12-16 11:00 UTC, 72 h" became "for 72 h from
  2017-12-16 11:00 UTC".

**Owner request mid-task, planned here:** fix the known issues, stop training on the 20-meter
sample, and get the best model the data supports. New milestone M5b:
- **T042:** full-scale data, memory-efficient features and quality masking.
- **T043:** the best model at full scale.
- **T044:** a downstream re-run at full scale.

The machine has 15.3 GB of RAM, so full-scale features (about 5 GB in float64) must be built in
batches as float32.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 75
  files.
- `pytest -W error`: **564 passed**, 8 new:
  - every event gets a clean bundle
  - the surge bundle shows the interval, agreement and influences
  - contributions add up to the expected value
  - the fallback without contributions
  - template wording; the guard's positive cases
  - text without a model expectation, and with the model in disagreement
  - a byte-identical CLI, and the CLI without a model

---

## 2026-10-25 — T042 Full-scale data, memory-efficient features and quality masking

**Owner request:** fix the known issues, stop training on a 20-meter sample, and build the best
model. This is the first of the three M5b tasks.

**Done**
- **Full preparation:** `bdg2_prepare --sample-meters 0 --output ../data/processed/bdg2/cleaned-all`
  gives 1,148 meters at 15 sites, 20,137,056 readings (1,187,658 missing), in 93 s. The
  20-meter sample is kept for the earlier results.
- **`wattwise.ml.scale`** (D035):
  - `quality_mask`, using vectorised run lengths
  - `mask_summary`
  - `build_store` / `load_store`: float32 parts per 100 meters, SHA-256 and feature-set checks
  - `full_scale_baselines`, on all rows and on quality rows
  - a CLI
- **Mask policy revised after measuring:**
  - The first build masked from 6 identical hours (T008's length): 10.4% of readings.
  - The analysis found no negatives and no 24-hour zero runs. Identical runs of 6–23 hours
    held 180,532 readings, many of them steady loads on coarse meters; runs of 24 hours or
    more held 1,794,952.
  - The mask now drops runs of 24 hours or more only: **9.47% of readings, 376 meters, 195
    over 10%**. It is computed when needed, not stored.
- **Store rebuilt:** 517 s, peak 6.06 GB, 1,148 meters, 20,137,056 rows.
- **Real-data check:** for the 20 sample meters, every one of 350,816 rows and 32 features
  equals the in-memory features exactly (float32).
- **Performance bug:** the first full-scale baseline run took **18,299 s (5.1 h)**, peaking at
  6.33 GB with only about 5 GB free, so it paged to disk.
  - **Profiling:** 100 meters took 15 s, so the work itself scales linearly.
  - **Fix:** category identifiers, with identical reports on 100 meters and 5.8 times less
    memory.
  - **Rerun:** **597 s, peak 5.52 GB, identical summary to the 5.1-hour run.**
- **Housekeeping:** removed a whitespace-only line that the T020 commit added to this log.

**Full-scale baselines (T012 split)**
- **All rows:**
  - seasonal-naive: validation MAE 17.89, test MAE **15.72**, WAPE **10.8%**, macro MAE 15.78
    (1,132 meters, 2,411,534 rows)
  - profile: validation 28.31, test 21.63, WAPE 14.8%
- **Quality rows:**
  - seasonal-naive: test MAE 16.74, WAPE 10.3% (1,021 meters)
  - profile: test 22.54, WAPE 13.9%
- **Reading:** the 20-meter sample was easier than BDG2 as a whole (seasonal-naive test WAPE
  8.6%). The full-scale bar for T043 is test MAE 15.72 kWh.

**Validation** (Windows)
- `uv lock --check`: exit 0. ruff: clean. Format: clean. `mypy` (strict): no issues in 77
  files.
- `pytest -W error`: **573 passed**, 9 new:
  - masking of negatives, 24-hour zero runs and 24-hour identical runs
  - shorter runs kept
  - runs do not cross gaps or meters
  - row order
  - batched store equals in-memory features
  - tampered and outdated stores refused
  - full-scale baselines on all rows and quality rows
  - the CLI

---

## 2026-10-26 — T021a Sourced carbon-factor and price reference tables

Done in parallel, in the background, while T043's full-scale study trained (owner request:
"till then complete other work also"). No project dependencies were changed and the backend
venv was not touched, so it could not interfere with the T043 run.

**Done**
- **`wattwise.data.reference`** (D037): `CarbonFactor` and `ElectricityPrice` dataclasses,
  loaders for two committed CSV tables, and lookups (`carbon_factor`, `prices`,
  `site_carbon_factor`, `site_prices`) that resolve a BDG2 site to its geography first.
- **`data/reference/carbon_factors.csv`** (9 rows) and **`data/reference/electricity_prices.csv`**
  (10 geographies, every band/tax-basis variant kept, not collapsed to one guessed number). Every
  row carries its source name, URL, retrieval date, licence and the SHA-256 of the file it was
  read from.
- **`bdg2_sites.EGRID_SUBREGION`:** each of the 7 locatable US BDG2 sites mapped to its eGRID
  subregion by an actual point-in-polygon lookup (ray casting against
  `eGRID 2016 Subregions.kml`'s published polygons), not inferred from the state name. The
  ray-casting function was checked against a hand-built square first.
- **Vintage fallback, made explicit:** eGRID publishes roughly every two years (no eGRID2017);
  `carbon_factor` returns the nearest earlier vintage and reports it (`vintage_year`) rather than
  silently treating an old edition as a fresh measurement.
- **Ontario's gap, investigated and left open rather than papered over:** a prior task (T007b)
  cited a 2016/2017 Ontario intensity from an older NIR edition ("1990-2017", Table A13-7), but
  that edition could not be found at a stable public URL this task (the Open Government Portal
  record exposes only the current 1990-2024 edition, whose Ontario table skips 2016/2017; older
  ECCC Data Mart folders render client-side and could not be listed). Rather than commit a number
  without its own file's checksum, or interpolate, Ontario has no committed carbon row for those
  years. T021a's scope already specifies no Ontario price source.
- **Bug fixed before it shipped:** the first point-in-polygon attempt returned no matches for any
  site, including California, despite the bounding box containing the point. The cause was a
  swapped `(lon, lat)` unpacking order in the test-points loop; a sanity check against a known
  square, then a bounding-box-candidate trace on the real data, found it.

**Validation** (Windows)
- `uv lock --check`: exit 0 (no dependency changes). ruff: clean. Format: clean. `mypy` (strict):
  no issues.
- `pytest -W error`: 20 new tests (geography resolution, vintage fallback, "not configured" for
  every unconfigured case, the committed tables' schema, checksums and no duplicate rows).
