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
