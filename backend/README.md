# WattWise AI — backend

Python project `wattwise`: the FastAPI service, the data contracts and, later, the data
pipeline and ML code. It uses a src layout. See [docs/DECISIONS.md](../docs/DECISIONS.md)
entries D002 and D010.

```
src/wattwise/
  api/            HTTP layer: app factory, routes, schemas, dependencies
  core/           settings and shared utilities
  data/           canonical data contracts, validation, CSV reading (docs/DATA_CONTRACT.md)
  db/             SQLAlchemy models, the engine, Alembic migrations (docs/DATABASE.md)
tests/            pytest suite, mirroring the package layout
```

Domain, data and ML code must never import from `wattwise.api`.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and locked for every platform in
`uv.lock` (D010). You need **uv 0.12.24 or a later 0.12.x release**.
`[tool.uv] required-version` (`>=0.12.24,<0.13`) rejects anything else, including the newest
0.13 releases, so install a pinned version:

- Windows: `winget install --id astral-sh.uv --exact --version 0.12.24`
- macOS/Linux: `curl -LsSf https://astral.sh/uv/0.12.24/install.sh | sh`
- An existing standalone uv install: `uv self update 0.12.24`

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
| `WATTWISE_DATABASE_URL` | `postgresql+psycopg://user:password@host:port/database` | unset (no database) |
| `WATTWISE_TEST_DATABASE_URL` | the same form; **tests only** | unset (database tests skip) |

The database URL carries a password: keep it in an untracked file, never in the repository.
`backend/.env` is git-ignored; run commands with `uv run --env-file .env ...` to load it. See
[docs/DATABASE.md](../docs/DATABASE.md) for creating the local role and databases.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness only: the process is up. It does **not** check dependencies. |
| GET | `/api/v1/buildings` | Buildings, a page at a time (`limit` 1-200, `offset`), filtered by `site_id` or `dataset_id`. |
| GET | `/api/v1/buildings/{building_id}` | One building; 404 if unknown. |
| GET | `/api/v1/meters` | Meters, a page at a time, filtered by `building_id` or `meter_type`. |
| GET | `/api/v1/meters/{meter_id}` | One meter; 404 if unknown. |
| GET | `/api/v1/meters/{meter_id}/series` | Readings in [`start`, `end`) (ISO 8601 with an offset), at most `limit` points, with `truncated`. Missing readings are `null`. |
| GET | `/api/v1/dashboard/summary` | Counts per dataset and overall, meters by type, missing values and the time range. |
| GET | `/api/v1/alerts` | Alerts, highest priority first, filtered by building, meter, dataset, `signature`, `severity`, `kind`, `review_status` and an overlap with [`start`, `end`); superseded ones only with `include_superseded=true`. |
| GET | `/api/v1/alerts/{alert_id}` | One alert with its evidence bundle, explanation, every review and the caveats; 404 if unknown. |
| POST | `/api/v1/alerts/{alert_id}/feedback` | A reviewer's verdict: `label` (`confirmed_waste`, `expected_behaviour`, `sensor_or_data_fault`, `needs_investigation`), optional `note` and `reviewer`. 201; 422 for anything invalid. Stored only: no model is retrained. |
| GET | `/api/v1/ready` | Readiness: 200 when the database is reachable and migrated to the head revision; 503 otherwise, naming the reason (`not_configured`, `unreachable`, `schema_outdated`) and never the connection details. |

## Database

```bash
uv run --env-file .env alembic upgrade head     # create or update the schema
uv run --env-file .env alembic downgrade base   # remove it
uv run --env-file .env python -m wattwise.db.load --source ../data/sample/synthetic \
    --dataset-id synthetic-sample --kind synthetic --name "WattWise synthetic sample"
```

Every response from the data endpoints carries `data_kind` (`synthetic` or `observed`), and all
timestamps are UTC.

The tests that need PostgreSQL create a throwaway schema per test in the database named by
`WATTWISE_TEST_DATABASE_URL` and drop it afterwards, so use a database that holds nothing that
matters. Without the variable they skip locally; in CI (`CI` set) a missing variable is a
failure, so they cannot stop running unnoticed.
