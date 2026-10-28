# WattWise AI — Database

PostgreSQL 18 (D007) holds what the API serves. The pipeline's readings stay in Parquet; the
database stores the entities of the [data contract](DATA_CONTRACT.md) and, with later tasks, alerts,
feedback and analysis runs. Decisions: D045.

## What exists (T023)

| Table | Primary key | Contents |
|---|---|---|
| `buildings` | `building_id` | `site_id`, `timezone`, optional `primary_use`, `floor_area_m2` (> 0), `latitude` (-90 to 90), `longitude` (-180 to 180), `created_at` |
| `meters` | `meter_id` | `building_id` (foreign key, `RESTRICT`), `meter_type`, `unit`, `created_at` |

- The meter type must be one of the contract's eight, and the unit must be that type's canonical
  unit (`kWh` or `m3`). The database enforces both, so data that skipped validation cannot
  contradict the contract.
- A building with meters cannot be deleted.
- Migrations are in `backend/src/wattwise/db/migrations` (inside the package, so a built image
  carries them). Revision `0001` is the baseline. A test builds the schema from the migrations
  and fails if the models differ from it.

## Readiness

`GET /api/v1/ready` is 200 only when the database is configured, reachable **and** migrated to the
head revision. Otherwise 503 with one reason:

| `database` | Meaning |
|---|---|
| `not_configured` | `WATTWISE_DATABASE_URL` is unset |
| `unreachable` | the connection failed or timed out (3 s) |
| `schema_outdated` | reachable, but not at the head revision (never migrated, or behind) |

The response never carries the host, user or error text; the exception type is logged. Liveness
(`/api/v1/health`) does not depend on the database.

## Local setup

1. **Create a role and two databases** (once), as a PostgreSQL superuser. Use your own password
   and keep it out of the repository:

   ```sql
   CREATE ROLE wattwise LOGIN PASSWORD '<a password you generate>';
   CREATE DATABASE wattwise OWNER wattwise;
   CREATE DATABASE wattwise_test OWNER wattwise;
   ```

2. **Write `backend/.env`** (git-ignored):

   ```text
   WATTWISE_DATABASE_URL=postgresql+psycopg://wattwise:<password>@localhost:5432/wattwise
   WATTWISE_TEST_DATABASE_URL=postgresql+psycopg://wattwise:<password>@localhost:5432/wattwise_test
   ```

3. **Migrate and test**, from `backend/`:

   ```bash
   uv run --env-file .env alembic upgrade head
   uv run --env-file .env pytest
   ```

No Docker is needed, but a throwaway container works too:
`docker run -d -e POSTGRES_USER=wattwise -e POSTGRES_PASSWORD=<pw> -e POSTGRES_DB=wattwise_test -p 127.0.0.1::5432 postgres:18`
(read the chosen port with `docker port <container> 5432`).

## Test strategy

- Real PostgreSQL, not SQLite or mocks: the constraints, the foreign keys and the migrations are
  what is under test.
- **A fresh schema per test** in `WATTWISE_TEST_DATABASE_URL`'s database, dropped afterwards.
  Tests cannot affect each other, run in any order and need no `CREATEDB` right.
- Without the variable the database tests **skip** locally; in CI a missing variable **fails**.
- CI runs a `postgres:18` service container, pinned by digest, with throwaway credentials.
