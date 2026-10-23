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

Requires Python 3.12 or newer (developed on 3.13). Always use the project virtualenv.

PowerShell (Windows):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

bash/zsh (macOS, Linux):

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

## Run the API

```powershell
.venv\Scripts\python -m uvicorn wattwise.api.main:create_app --factory --reload --port 8000
```

- Liveness: <http://127.0.0.1:8000/api/v1/health>
- Interactive OpenAPI docs: <http://127.0.0.1:8000/docs>

## Checks

Run these from `backend/` before every commit:

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
```

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
