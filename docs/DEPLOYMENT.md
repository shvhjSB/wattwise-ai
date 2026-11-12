# Private Docker-host deployment

**Status:** a deployment recipe, not a deployed service. No cloud resources, registry publication,
DNS, TLS endpoint or remote host has been provisioned. The owner selected a private Docker host
for T038. The separate **public, read-only synthetic demo on Render** (T046) is described in
[its own section](#public-demo-on-render-t046-d064); the card-free
**static demo on GitHub Pages** (T050) in [another](#public-static-demo-on-github-pages-t050-d068). Local/CI verification uses only disposable synthetic data and is not evidence of
real-building accuracy, production capacity or a hosted service.

## Boundary and prerequisites

Use a maintained Linux Docker Engine with the Compose plugin. Run the commands below in Bash
from a trusted checkout of a CI-passing commit. Host administration, registry access, capacity,
firewall policy, encrypted off-host backups and recovery ownership remain operator decisions.
The example resource limits are budgets, not sizing guarantees; benchmark your actual model and
workload before choosing a host. Docker access is effectively host-root access.

The recipe is `deploy/compose.yaml`, **not** the synthetic quickstart `compose.yaml`. It has no
automatic training, dataset import or demo seeding. It publishes only Nginx on `127.0.0.1:8080`;
PostgreSQL and the API have no host ports. Use an SSH tunnel for private access:

```bash
ssh -N -L 8080:127.0.0.1:8080 operator@YOUR_PRIVATE_HOST
```

Then open `http://127.0.0.1:8080` locally. Keep the host firewall closed except approved SSH/VPN
access. There is **no application authentication or authorization**. Do not change the binding
to `0.0.0.0` or add a public proxy without a separately reviewed identity/access-control and TLS
design. CORS is not authentication. Review [SECURITY.md](SECURITY.md), including the 13 moderate
development-tool findings and the fact that a 504 does not cancel a committed write or ML thread.

## 1. Build and record an immutable release

On a trusted builder, from the exact, clean commit whose CI passed:

```bash
set -euo pipefail
REV=$(git rev-parse HEAD)
test -z "$(git status --porcelain)"
REGISTRY=YOUR_REGISTRY/YOUR_NAMESPACE
docker build --label "org.opencontainers.image.revision=$REV" -f backend/Dockerfile -t "$REGISTRY/wattwise-api:$REV" .
docker build --label "org.opencontainers.image.revision=$REV" -f frontend/Dockerfile -t "$REGISTRY/wattwise-frontend:$REV" .
docker push "$REGISTRY/wattwise-api:$REV"
docker push "$REGISTRY/wattwise-frontend:$REV"
docker image inspect --format '{{json .RepoDigests}}' "$REGISTRY/wattwise-api:$REV"
docker image inspect --format '{{json .RepoDigests}}' "$REGISTRY/wattwise-frontend:$REV"
```

These are instructions, not commands already run against your registry. Record the resulting
`repository@sha256:...` references, commit, target architecture, CI run, schema revision, model
version, data kind and artifact/backup identifiers in your release record. Keep both current
and previous image digests available. Do not deploy `latest`, `:demo` or a mutable release tag.
The verifier uses immutable **local image IDs**, not a claim of registry publication.

Copy `deploy/release.env.example` to a protected file such as
`/etc/wattwise/releases/RELEASE.env` on the host and replace **every** placeholder. Keep the same
PostgreSQL volume between compatible releases, but use a distinct artifact volume per release.
The file contains configuration and secret-file paths, not secret values. Never commit actual
release configuration or secrets. The Compose file requires all critical values but does not
itself validate image-reference syntax; validate digests before using it:

```bash
set -euo pipefail
export RELEASE_FILE=/etc/wattwise/releases/RELEASE.env
set -a
. "$RELEASE_FILE"
set +a
[[ "$WATTWISE_API_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]
[[ "$WATTWISE_FRONTEND_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]
docker pull "$WATTWISE_API_IMAGE"
docker pull "$WATTWISE_FRONTEND_IMAGE"
dc() { docker compose -p wattwise-private --env-file "$RELEASE_FILE" -f deploy/compose.yaml "$@"; }
dc config --quiet
```

Use a shell with `set -euo pipefail` for the procedure, so failed guards/commands stop execution.
Clear conflicting exported `WATTWISE_*` values before loading a release: shell variables take
precedence over Compose's env file. Keep the Compose project name stable across upgrades.

## 2. Provision mounted secrets and persistent storage

On the host, as the administrator, create a private directory. Generate separate bootstrap-admin
and application passwords once for a **new** database; the hexadecimal alphabet is URL-safe:

```bash
install -d -m 0700 /etc/wattwise/secrets
test ! -e "$WATTWISE_DB_ADMIN_PASSWORD_FILE"
test ! -e "$WATTWISE_DB_PASSWORD_FILE"
test ! -e "$WATTWISE_DATABASE_URL_FILE"
umask 077
openssl rand -hex 32 > "$WATTWISE_DB_ADMIN_PASSWORD_FILE"
openssl rand -hex 32 > "$WATTWISE_DB_PASSWORD_FILE"
printf 'postgresql+psycopg://wattwise:%s@db:5432/wattwise\n' "$(cat "$WATTWISE_DB_PASSWORD_FILE")" > "$WATTWISE_DATABASE_URL_FILE"
chmod 0444 "$WATTWISE_DB_ADMIN_PASSWORD_FILE" "$WATTWISE_DB_PASSWORD_FILE" "$WATTWISE_DATABASE_URL_FILE"
docker volume create --label com.wattwise.environment=private "$WATTWISE_POSTGRES_VOLUME"
docker volume create --label com.wattwise.environment=private "$WATTWISE_ARTIFACT_VOLUME"
```

All three paths must be direct children of the protected directory in this example. The directory
must remain root-owned and `0700`; file read permission allows non-root container users to read
their individual bind-mounted secrets without exposing the host directory to other host users.
Compose file-secret `uid`/`mode` remapping is not portable; do not rely on it. Docker administrators
can always read mounted secrets. Do not copy secrets to a public backup directory or echo them.

PostgreSQL receives only its admin/application password files. On a fresh database,
`deploy/init-db.sh` creates an application/schema owner `wattwise` with **no superuser, database
creation, role creation or replication privilege**. The bootstrap admin is `wattwise_admin`.
API/migration/check containers receive only the URL file, named `/run/secrets/WATTWISE_DATABASE_URL`.
The frontend receives no secrets. `WATTWISE_SECRETS_DIR` makes missing/conflicting database sources
fail at startup; no password is passed as a container environment value or command argument.

The app role owns its schema so migrations can run; it is not a separately restricted read/write
runtime role. Separation of migration and runtime database privileges is a future improvement.
First-start scripts run **only on an empty PostgreSQL volume**. Changing a password file does not
rotate an existing role: arrange a reviewed SQL password rotation, update the URL secret, and
recreate dependent containers. Never fix mismatched credentials by deleting the database volume.

Both volumes are explicitly **external**: ordinary container recreation, `down`, and Compose's
`down --volumes` do not own their lifecycle. A host/volume deletion still loses data, and a named
volume on the same machine is not a backup. Never use `volume prune` on the deployment host.
PostgreSQL 18 stores data under `/var/lib/postgresql`; do not change its major version in place.

## 3. Stage a verified model/report bundle

Prepare an approved bundle outside the checkout:

```text
BUNDLE/
  models/CURRENT
  models/<WATTWISE_MODEL_VERSION>/metadata.json
  models/<WATTWISE_MODEL_VERSION>/model.txt
  models/<WATTWISE_MODEL_VERSION>/state.json
  evaluation/chosen.json
  evaluation/seasonal-naive-1w.json
```

Use the evaluation model described in D039, with held-out validation/test windows, not the
all-data production refit that cannot calibrate honest intervals. `CURRENT` must name exactly
`WATTWISE_MODEL_VERSION`. Reports must match its data fingerprint, split, family/settings and
recorded test scores. Set `WATTWISE_MODEL_DATA_KIND=synthetic` for generated models; never use
`observed` to relabel synthetic results. In production the setting is required: without it the
API refuses to start rather than assume a label (T053). Registry integrity checks are not an accuracy claim.
Only trusted model artifacts are permitted; hashes detect corruption, not a malicious publisher.

Copy into a **new, empty** per-release volume; never overwrite the live bundle:

```bash
export BUNDLE=/srv/wattwise/staging/APPROVED_BUNDLE
docker run --rm --network none --user 0 --entrypoint sh \
  --mount "type=bind,source=$BUNDLE,target=/bundle,readonly" \
  --mount "type=volume,source=$WATTWISE_ARTIFACT_VOLUME,target=/state" \
  "$WATTWISE_API_IMAGE" -ec \
  'test -z "$(ls -A /state)"; cp -a /bundle/models /bundle/evaluation /state/; chown -R 10001:10001 /state'
```

The application mounts `/state` read-only. Model training, promotion and evaluation are offline
release steps, never API startup behavior. The runtime does not need raw training datasets.
Import approved operational data using [DATABASE.md](DATABASE.md), or restore an approved
snapshot. A new migrated database starts empty; this recipe does not secretly fill it with demo
rows. Keep the prior image/model/report bundle available together for rollback.

## 4. Start, verify and monitor

Back up before touching an existing database. For a new installation:

```bash
dc up -d --wait --wait-timeout 180
dc ps -a
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/ready
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/models/metadata
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/models/evaluation
```

Startup is `db healthy → migrate succeeds → check succeeds → API ready → frontend healthy`.
Migrations are serialized with a PostgreSQL transaction advisory lock; no downgrade or seeding
is performed. The one-shot release check verifies the database head, pinned model files and
matching saved evaluation reports. A failed gate prevents a new API from starting, but migration
effects are **not automatically rolled back if a later model check fails**.

Confirm the returned model `version` equals the release pin and evaluation `available` is true;
a 200 response alone is not enough. Exercise an approved, non-sensitive inference canary and
the frontend via the tunnel before allowing users. The recipe is not an automatic zero-downtime
rollout or scheduler; `unless-stopped` restarts processes but does not rerun release gates after
a host reboot. Operators must rerun checks after an image/model/storage change or recovery.

| Probe | What it establishes | What it does not establish |
|---|---|---|
| `/health` | API process/liveness and environment | Database or model readiness |
| `/ready` | Database reachable at this code's schema head | Model correctness or healthy inference |
| `/healthz` | Nginx serves its health location | The API/database are reachable |
| `wattwise.operations check --model-version ...` | Startup model/report integrity and schema compatibility | Real-world accuracy or load capacity |

Monitor all probes, model identity, 5xx/504 rates, disk/volume space, memory/OOM restarts and backup
age. Docker health status alone does not restart an unhealthy container. Logs are bounded locally
to three 10 MB files per service; arrange restricted centralized retention separately. API and
proxy access logs avoid raw URLs/payloads, but operational/database logs still need restricted
access. Do not enable SQL echo, dump container secrets or post unredacted diagnostics publicly.

## 5. Back up and rehearse restore

Stop **all writers**, including imports/maintenance jobs, and quiesce API traffic. Back up the
logical database, immutable artifact volume and release record as a pair. Example:

```bash
export BACKUP=/var/backups/wattwise/UNIQUE_BACKUP_ID
install -d -m 0700 "$BACKUP"
dc stop frontend api
dc exec -T db pg_dump -U wattwise -Fc -f /tmp/wattwise.dump wattwise
dc cp db:/tmp/wattwise.dump "$BACKUP/database.dump"
docker run --rm --network none --user 0 --entrypoint tar \
  --mount "type=volume,source=$WATTWISE_ARTIFACT_VOLUME,target=/state,readonly" \
  --mount "type=bind,source=$BACKUP,target=/backup" "$WATTWISE_API_IMAGE" \
  -czf /backup/artifacts.tgz -C /state .
cp "$RELEASE_FILE" "$BACKUP/release.env"
(cd "$BACKUP" && sha256sum database.dump artifacts.tgz release.env > SHA256SUMS)
dc exec -T db rm -f /tmp/wattwise.dump
dc up -d --wait --wait-timeout 180
```

The dump is a sensitive copy of operational data and reviews. Protect it with private permissions,
encrypted off-host storage, documented retention/recovery objectives and a tested independent
secret-recovery path. Do not tar a live PostgreSQL data directory as a substitute for a consistent
database backup. This logical dump excludes global roles; the recipe creates the fixed app/admin
roles on fresh storage. Record and back up any additional grants/roles separately.

For a rehearsal or recovery, retain the old volumes. Verify archive checksums and use a copy of
the saved release file with **new** PostgreSQL/artifact volume names and a different loopback port
if the old instance is still running. A second concurrent instance also needs a distinct Compose
project name in `dc`. Recover the secret files through your protected secret-management process.
Create the two new external volumes, then:

```bash
dc up -d --wait --wait-timeout 120 db
dc cp "$BACKUP/database.dump" db:/tmp/wattwise.dump
dc exec -T db pg_restore -U wattwise --exit-on-error --no-owner --no-acl -d wattwise /tmp/wattwise.dump
docker run --rm --network none --user 0 --entrypoint tar \
  --mount "type=volume,source=$WATTWISE_ARTIFACT_VOLUME,target=/state" \
  --mount "type=bind,source=$BACKUP,target=/backup,readonly" "$WATTWISE_API_IMAGE" \
  -xzf /backup/artifacts.tgz -C /state
dc exec -T db rm -f /tmp/wattwise.dump
dc up -d --wait --wait-timeout 180
```

Restore **only trusted archives into empty target volumes**. Check schema/model identity,
dataset counts, a known review and an approved inference canary before switching users. If any
restore command fails, do not expose or reuse the partially restored database; investigate and
rehearse again in new storage. Restore testing does not authorize deleting production volumes.

## 6. Upgrade and rollback

1. Review schema changes and artifact/feature compatibility; run CI and a staging canary with
   the proposed image/model/report bundle. Retain the old release file, digests and model volume.
2. Schedule a maintenance window, block all writers, back up the current release and stop its
   frontend/API **using the old release file**. Do not let old code write during schema changes.
3. Load the new release file into a clean shell, validate/pull its image digests, and stage its
   new artifact volume. Run `dc up -d --wait --wait-timeout 180`; verify all probes and canaries.
4. On failure, leave access closed. Review the migration result before using old images. If the
   schema remains compatible, reload the saved old release file and recreate the old services.
   Do not edit `CURRENT` in the live mounted volume; select the prior immutable bundle and pin.
5. If the schema is incompatible, application-image rollback alone is unsafe. Restore the paired
   backup into fresh volumes using the compatible saved release. **No automatic Alembic downgrade**
   is performed. Recovery loses writes after that backup; obtain approval and reconcile them.

Changing the release model does not regenerate historical alerts, reviews or stored expectations;
those retain their own model provenance. A UI/API rollback is not a rollback of reviewed operator
decisions. Never delete old volumes or models until retention/recovery policy permits it.

## Automated verification

After building both images with `docker compose build api frontend`, run from `frontend/`:

```bash
npm run test:deployment
```

The verifier uses a random `wattwise-deploy-check-*` project, separate labelled external volumes,
temporary random mounted secrets and a free loopback port chosen at run time (override with
`WATTWISE_DEPLOY_CHECK_PORT`; it refuses a port that already answers HTTP).
It checks the actual recipe: non-superuser app role, missing-model startup refusal, valid pinned
startup, read-only artifacts, absent URL/password environment values, wrong-pin refusal, review
persistence after recreation, and logical database/artifact restore into **fresh** volumes.
It removes only resources it created after checking their ownership labels. It never resets the
owner's 8080 demo or uses the host PostgreSQL database. CI runs the same verifier after image and
browser checks. Tests are synthetic; no registry push, remote host deployment, full-scale capacity
test, disaster-recovery SLA or historical application-image rollback is claimed.

## Public demo on Render (T046, D064)

A separate, **public, read-only** deployment of the **synthetic demo only**, on Render's free
plan, from [`render.yaml`](../render.yaml). It is not the private recipe above and shares nothing
with it. Status: the Blueprint and image are built and verified (below); the site exists only
once the owner applies the Blueprint in their Render account.

**What is public:** the committed synthetic sample (4 buildings, 8 weeks, generated, not
measured), a model trained on it inside the image, its alerts, expectations and evaluation. No
BDG2, LEAD, Building 59 or HKUST data or model is deployed. Every page shows the synthetic-data
banner.

**Read-only:** `WATTWISE_READ_ONLY=true`. Every API request other than GET, HEAD and OPTIONS
answers 403 with a plain reason, so reviews, uploads and analyses are off; the review form shows a
notice instead. There are no accounts or logins. Request-size and time limits (D059) still apply.

**How it runs:** one Docker web service (`deploy/render/Dockerfile`) serves the API and the
built frontend on the same origin (no CORS), plus one free Render Postgres reachable only on
Render's private network (`ipAllowList: []`). The demo model is trained at image build time; at
startup `python -m wattwise.public_demo` converts Render's `DATABASE_URL`, seeds an empty
database (or replaces a demo made by an older model), then serves on `$PORT`.

### Set it up (owner, once)

1. Sign in at <https://dashboard.render.com> with the GitHub account `shvhjSB` and allow Render
   to read the repository `shvhjSB/wattwise-ai`.
2. **New → Blueprint**, choose `shvhjSB/wattwise-ai`, branch `main`. Render reads `render.yaml`
   and proposes the web service `wattwise-demo` and the database `wattwise-demo-db`, both free.
3. **Apply.** The first deploy builds the image (a few minutes) and starts it; the first start
   seeds the database (about 1.5 minutes at the free plan's 0.1 CPU, measured locally).
4. Open the service URL Render shows (`https://wattwise-demo....onrender.com`). Later pushes to
   `main` redeploy automatically **after GitHub CI passes** (`autoDeployTrigger: checksPass`).

### Keep it awake with UptimeRobot (optional)

A free web service sleeps after 15 minutes without traffic and takes about a minute to wake
(Render's docs; our container then needs about 70 s at 0.1 CPU). A monitor that requests it
every 5 minutes keeps it awake:

- <https://uptimerobot.com> → **New monitor** → type **HTTP(s)**, URL
  `https://<your-service>.onrender.com/api/v1/health`, interval **5 minutes**. HEAD and GET both
  answer 200.
- Budget: Render gives 750 free instance hours per workspace per month; one service awake all
  month uses at most 744. **Do not run a second free web service** in the same workspace, or the
  hours run out and Render suspends all free services until the next month.

### Free-plan limits (Render's docs, checked 2026-11-02)

| Limit | Effect here | What to do |
|---|---|---|
| Free Postgres **expires 30 days after creation**; 14-day grace, then deleted; no backups; 1 GB | The demo stops with a database error after 30 days | Delete the expired database and re-apply the Blueprint (or create `wattwise-demo-db` again); the next start reseeds it. Nothing is lost: the data is synthetic and the site is read-only |
| One free Postgres per workspace | | Do not create another |
| 0.1 CPU, 512 MB | First start about 1.5 min, restart about 1.2 min, 170-195 MB used (local runs with the same limits) | |
| Ephemeral filesystem | Runtime files vanish on restart | The model and reports are baked into the image |
| Sleep after 15 min idle | First visit after idle waits about a minute | UptimeRobot (above), within the hour budget |

### Verify

- Locally and in CI: `bash deploy/render/verify.sh` builds the image and runs it with
  `--cpus 0.1 --memory 512m`, a platform-style `DATABASE_URL` and `PORT=10000`; it checks seeding,
  the frontend, the synthetic data, the evaluation, a refused review (403), security headers, and
  that a restart does not reseed. It removes only its own `wwverify-*` resources.
- Live: `curl https://<your-service>.onrender.com/api/v1/health` must show `"read_only":true`.

## Public static demo on GitHub Pages (T050, D068)

The public demo that needs **no card**: <https://shvhjsb.github.io/wattwise-ai/>, live since
2026-11-02 (Pages run 41421223255). Render (T046), Koyeb and Hugging Face's Docker Spaces all ask for a card or a paid
plan (checked 2026-11-02); GitHub Pages is free for this public repository.

**What it is:** the synthetic demo as a static site with no server. After CI passes on `main`,
`.github/workflows/pages.yml` seeds the synthetic demo into a throwaway PostgreSQL, records the
API's answers for every preset view (`python -m wattwise.snapshot`: 92 answers, about 480 KB),
builds the frontend in snapshot mode under `/wattwise-ai/`, opens every page in a browser
(`frontend/scripts/static-smoke.mjs`), and only then publishes. A failed check publishes nothing
and the previous site stays.

**What works:** every page and chart, alert detail and evidence, the explorer, data health with
all filters, drift by week or month, the model lab, the What-if lab, the Bill analyser and the
Meter check (all three computed in the browser).
**What does not:** anything not recorded, such as free-text building search and alert date
filters, shows "not part of the static demo"; reviews and uploads are refused as on the read-only
demo. The Cost impact tariff form is disabled, because the synthetic sites have no tariff
geography (the What-if lab's tariff works, in the browser). The Machines page opens empty: no
comparison is recorded, and the synthetic sample's buildings have one meter each. Nothing sleeps
and nothing expires.
Deep links such as `/wattwise-ai/alerts` load the app through `404.html`, so GitHub Pages answers
them with HTTP status 404 even though the page renders (T051).

### Set it up (owner, once)

1. On GitHub, open **shvhjSB/wattwise-ai → Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**. Nothing else to fill in.
3. Open **Actions → Pages → Run workflow** (branch `main`), or push any commit to `main`. When
   it finishes, the site is at <https://shvhjsb.github.io/wattwise-ai/>.

Every later push to `main` that passes CI republishes it.

### Verify locally

```bash
# from backend/, with WATTWISE_DATABASE_URL pointing at an empty database
uv run --env-file .env python -m wattwise.snapshot --output ../data/processed/snapshot
# from frontend/
WATTWISE_BASE=/wattwise-ai/ VITE_SNAPSHOT=1 npx vite build --outDir ../data/processed/static-dist
cp -r ../data/processed/snapshot ../data/processed/static-dist/snapshot
cp ../data/processed/static-dist/index.html ../data/processed/static-dist/404.html
node scripts/static-smoke.mjs ../data/processed/static-dist
```

(On Git Bash for Windows, prefix the build with `MSYS_NO_PATHCONV=1`, or `/wattwise-ai/` is
rewritten into a Windows path.)

## References

- [Compose secrets and mount permissions](https://docs.docker.com/compose/how-tos/use-secrets)
- [Compose environment precedence](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation)
- [External volume lifecycle](https://docs.docker.com/reference/compose-file/volumes)
- [Health-gated startup](https://docs.docker.com/compose/how-tos/startup-order/)
- [PostgreSQL logical backups](https://www.postgresql.org/docs/18/backup-dump.html)
