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
