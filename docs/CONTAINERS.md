# Local synthetic demo with Docker Compose

From the repository root, with Docker Desktop's Linux engine running:

```bash
docker compose up --build -d --wait --wait-timeout 180
```

Open <http://127.0.0.1:8080>. Without `-d`, `docker compose up --build` runs the same stack in
the foreground. The first build downloads pinned images and locked dependencies; initialization
trains the small synthetic demo model. No BDG2 or LEAD download is required.

This is a **local synthetic demo**, not a production deployment. The committed demonstration
password is public, and the only host listener is the frontend on loopback. Neither PostgreSQL
nor the API publishes a host port. The native PostgreSQL service and local model registry are
not used. Deployment and security hardening remain T038 and T037.

## Services and startup

| Service | Role | Ready when |
|---|---|---|
| `db` | Pinned PostgreSQL 18; named `postgres-data` volume | `pg_isready` succeeds |
| `init` | Apply Alembic migrations; initialize or verify the synthetic demo | One-shot process exits successfully |
| `api` | Non-root FastAPI image; read-only demo artifact mount | `/api/v1/ready` confirms database and migration revision |
| `frontend` | Non-root Nginx image; compiled SPA and same-origin `/api/` proxy | `/healthz` succeeds |

Compose waits for the database, then for initialization, then API readiness before starting
Nginx. The frontend serves deep links such as `/models` through the SPA fallback; unknown API
paths still return the API's JSON 404 rather than HTML. Nginx resolves the API through Docker DNS.

All base images and the uv installer image are pinned by digest. Python uses `uv.lock` with
`--locked --no-dev --no-editable`; Node uses `npm ci` and `package-lock.json`. Runtime images
contain neither the build toolchain nor local virtual environments, environment files, raw data
or model artifacts from the checkout. The root `.dockerignore` limits the build context to source,
configuration, the committed synthetic sample and the two sourced reference CSV tables.

## Demo data, models and persistence

The demo uses the committed sample: four buildings/meters, 5,376 hourly rows and six missing
values. Its chronological split trains before 2016-01-25, validates until 2016-02-08 and tests
until 2016-02-29. Actual detections, explanations, expectations and evaluation reports are
generated; displayed results are labelled synthetic and do not establish real-world accuracy.

Two project-scoped named volumes retain PostgreSQL data and demo artifacts. PostgreSQL 18 mounts
at `/var/lib/postgresql`; model, prepared-table and evaluation files live under `/state`. The
initializer records a source-hash/model checkpoint. On restart it verifies that checkpoint,
reuses the model and leaves readings, alerts and review history in place. It refuses other
datasets or mismatched/missing artifacts instead of replacing existing data. An empty database
can be seeded from a matching retained model, but lost database reviews require a database backup.

Stop and recreate containers while keeping both volumes:

```bash
docker compose down
docker compose up -d --wait --wait-timeout 180
```

Do **not** add `--volumes` to `down` unless you intend to erase the demo database, review history
and model artifacts. Back up both volumes together before changing fixture versions or resetting
the demo. No automatic reset is performed.

## Ports and diagnostics

`WATTWISE_DEMO_PORT` overrides the default host port. For PowerShell:

```powershell
$env:WATTWISE_DEMO_PORT = '8081'
docker compose up --build -d --wait --wait-timeout 180
```

```bash
docker compose ps -a
docker compose logs --tail 50 init api frontend
```

The initializer should be `Exited (0)`; the other three services should be healthy. API checks
are available through Nginx at `/api/v1/health` and `/api/v1/ready`. Initialization errors stop
startup before the API is exposed. A source/checkpoint mismatch needs matching saved volumes or
a deliberate demo reset, not a forced reload into an existing database.

## Verification

With Node and the frontend test dependencies installed, from `frontend/`:

```bash
node scripts/compose-smoke.mjs initial
npm run test:e2e:compose
```

The smoke check verifies built assets, deep links, JSON API errors, readiness, synthetic totals,
model/evaluation identity and a review write. The nine Chromium scenarios exercise the actual
Nginx/container API path in desktop light/dark and mobile contexts. They write only demo feedback.

After the container recreation commands above:

```bash
node scripts/compose-smoke.mjs restored
```

This confirms the model version, readings and recorded smoke review survive recreation. Set
`WATTWISE_COMPOSE_URL=http://127.0.0.1:8081` for checks against a different port. Test helpers
accept only loopback HTTP origins. Smoke state is stored under git-ignored `artifacts/`; browser
screenshots and reports remain under the frontend's ignored test-output folders.

CI builds and starts this Compose stack, runs smoke and browser checks, recreates the containers,
verifies persistence and removes only its disposable CI project and volumes. Normal unit and
PostgreSQL pipeline tests run in their own jobs.

## Implementation references

Security controls, audit policy and remaining public-deployment prerequisites are described in
[SECURITY.md](SECURITY.md). The demo has no authentication; do not publish it as a private-data
service merely by changing its port binding.

- [Compose startup conditions](https://docs.docker.com/compose/how-tos/startup-order/)
- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
- [PostgreSQL container guide and version 18 volume layout](https://docs.docker.com/guides/postgresql/)
