# WattWise AI — Database

PostgreSQL 18 (D007) holds what the API serves: the [data contract](DATA_CONTRACT.md)'s
buildings, meters and readings, each dataset labelled synthetic or observed, and, with later
tasks, alerts, feedback and analysis runs. The ML pipeline still reads its Parquet tables.
Decisions: D045, D046.

## Tables

| Table | Primary key | Contents |
|---|---|---|
| `datasets` | `dataset_id` | `name`, `kind` (`synthetic` or `observed`), `source` (provenance), `loaded_at` (T024); totals computed at load: `reading_count`, `missing_count`, `first_reading`, `last_reading`, `measured_kwh` (T029) |
| `buildings` | `building_id` | `dataset_id` (foreign key), `site_id`, `timezone`, optional `primary_use`, `floor_area_m2` (> 0), `latitude` (-90 to 90), `longitude` (-180 to 180), `created_at` |
| `meters` | `meter_id` | `building_id` (foreign key, `RESTRICT`), `meter_type`, `unit`, `created_at` |
| `readings` | (`meter_id`, `timestamp`) | `value`: NULL means not measured, never 0 (T024) |
| `alerts` | `alert_id` | one detected event: meter, detector, start/end, signature, kind, priority score and severity band (T022), potential excess (never verified), the whole evidence bundle (JSONB), `review_status`, `reviewed_at`, `superseded` (T025) |
| `analysis_runs` | `run_id` | one record per `/inference/analyze` call: `created_at`, `model_version` (NULL without a model), `detector`, input range, meters, readings, missing values, predictions, alerts; never the readings (T027) |
| `alert_feedback` | `feedback_id` | `alert_id`, `label`, optional `note` (at most 2,000 characters) and `reviewer` (at most 100), `created_at`; append-only (T025) |

- **Every building belongs to a dataset whose kind is synthetic or observed**, so the API never
  serves data without that label.
- The meter type must be one of the contract's eight, and the unit must be that type's canonical
  unit (`kWh` or `m3`). The database enforces both, so data that skipped validation cannot
  contradict the contract.
- A building with meters cannot be deleted.
- **Time is UTC.** Timestamps are `timestamptz`; every session the engine opens runs in UTC, and
  the API converts every timestamp it returns to UTC. The tests run on a non-UTC session to keep
  it so.
- Migrations are in `backend/src/wattwise/db/migrations` (inside the package, so a built image
  carries them): `0001` the baseline, `0002` datasets and readings, `0003` alerts and
  feedback, `0004` analysis runs, `0005` dataset totals. A test builds the schema from
  the migrations and fails if the models differ from it; each revision downgrades to the one
  before.

## Loading a dataset

```bash
uv run --env-file .env python -m wattwise.db.load --source ../data/sample/synthetic \
    --dataset-id synthetic-sample --kind synthetic --name "WattWise synthetic sample (seed 2016)"
```

- `--source` holds `buildings` and `readings` as CSV (the upload format) or Parquet (canonical
  tables). Both are **validated against the contract first**; a violation loads nothing and
  prints every error.
- **A dataset is replaced as a whole**, in one transaction: a reload never mixes two versions.
  Buildings and meters are updated in place, so alerts keep pointing at them; readings are
  replaced; buildings and meters no longer present are removed, **unless a meter still has
  alerts**, in which case nothing is loaded (T025).
- A building or meter that belongs to **another** dataset is refused, never moved. Readings that
  name a building missing from the buildings table are refused.
- **Totals are stored at load time** (reading and missing counts, range and measured kWh), so the
  dashboard summary never scans the readings (11 s at 20 million rows; now 0.19 s).
- Readings go in with PostgreSQL `COPY`, in CSV chunks of 500,000 rows written by pandas; floats
  round-trip exactly (tested).
- BDG2 may be loaded into a **local** database (`--kind observed`); it is never redistributed
  (D014).

## Loading alerts

```bash
uv run --env-file .env python -m wattwise.db.alerts --dataset-id bdg2-cleaned-all \
    --explanations ../data/processed/fullscale-downstream/explanations-lean/explanations.json
```

- The input is `explanations.json` from `wattwise.ml.explanations`. Each bundle is scored with the
  T022 formula and stored with its severity band and the whole bundle.
- **Reloading keeps reviews.** Alerts are matched on (meter, detector, start): a match is updated
  in place (same id, same feedback); an alert no longer detected is deleted, **unless it has
  feedback**, in which case it is kept and marked `superseded`; new alerts are inserted.
- A load touches only one dataset and the detectors in the file.
- Feedback is never deleted (`RESTRICT`), and **no model is retrained from it** (D047).

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
