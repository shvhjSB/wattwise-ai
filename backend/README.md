# WattWise AI — backend

Python project `wattwise`: the FastAPI service now, and later the data pipeline and ML code.
It uses a src layout. See [docs/DECISIONS.md](../docs/DECISIONS.md) entries D002 and D003.

```
src/wattwise/
  api/            HTTP layer: app factory, routes, schemas, dependencies
  core/           settings and shared utilities
tests/            pytest suite, mirroring the package layout
```

Domain, data and ML code must never import from `wattwise.api`.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and locked for every platform in
`uv.lock` (D010). You need **uv 0.12.x**, as enforced by `[tool.uv] required-version`:

- Windows: `winget install --id astral-sh.uv --exact --version 0.12.24`
- macOS/Linux: see the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)

Then, from `backend/`:

```bash
uv sync --locked
```

This creates `backend/.venv` with the exact locked versions of the app and the `dev` tools. If
Python 3.13 (from `.python-version`) is missing, uv installs it. Windows tip: if uv warns that
it cannot hardlink, because its cache and the repo are on different drives, set
`UV_LINK_MODE=copy`.

## Run the API

```bash
uv run uvicorn wattwise.api.main:create_app --factory --reload --port 8000
```

- Liveness: <http://127.0.0.1:8000/api/v1/health>
- Interactive OpenAPI docs: <http://127.0.0.1:8000/docs>

## Checks

Run these from `backend/` before every commit. CI runs the same commands
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

## Changing dependencies

```bash
uv add "some-package>=1.2"         # runtime dependency
uv add --group dev "some-tool>=3"  # development-only tool
```

Commit `pyproject.toml` and `uv.lock` together. In CI, `uv sync --locked` fails if the lock is out
of date.

## Configuration

Settings come from environment variables prefixed with `WATTWISE_`. See
[`../.env.example`](../.env.example) for the full list.

| Variable | Values | Default |
|---|---|---|
| `WATTWISE_ENVIRONMENT` | `development`, `test`, `production` | `development` |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness only: the process is up. It does **not** check dependencies. |

A readiness endpoint (`/api/v1/ready`) that checks the database arrives with the database
foundation (roadmap task T023).
