#!/usr/bin/env bash
# Build the public-demo image (deploy/render/Dockerfile) and check it the way Render runs it:
# a platform-style DATABASE_URL, PORT=10000, Render's free-instance limits (0.1 CPU, 512 MB),
# a fresh database seeded at startup, then a restart that must not reseed. Only the resources
# this script creates (named wwverify-*) are removed. Usage: bash deploy/render/verify.sh
set -euo pipefail

image=wattwise-public:verify
net=wwverify-net
db=wwverify-db
app=wwverify-app
port=${WATTWISE_VERIFY_PORT:-18090}
base="http://127.0.0.1:${port}"

cleanup() {
  docker rm -f "$app" "$db" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  docker logs "$app" 2>&1 | tail -40 >&2 || true
  exit 1
}

wait_ready() {
  for _ in $(seq 1 90); do
    if curl -fs "${base}/api/v1/health" >/dev/null 2>&1; then return 0; fi
    sleep 5
  done
  fail "the app did not answer its health check within 450 s"
}

docker build -f deploy/render/Dockerfile -t "$image" .
cleanup
docker network create "$net" >/dev/null
docker run -d --name "$db" --network "$net" \
  -e POSTGRES_USER=wattwise -e POSTGRES_PASSWORD=verify-only -e POSTGRES_DB=wattwise_demo \
  postgres:18@sha256:979bccfde35445db618c65107d27d08c6c21339d8dc3ad4c830c6633947be0e4 >/dev/null
for _ in $(seq 1 30); do
  docker exec "$db" pg_isready -U wattwise -d wattwise_demo >/dev/null 2>&1 && break
  sleep 2
done
docker run -d --name "$app" --network "$net" --cpus 0.1 --memory 512m -e PORT=10000 \
  -e DATABASE_URL="postgresql://wattwise:verify-only@${db}:5432/wattwise_demo" \
  -p "127.0.0.1:${port}:10000" "$image" >/dev/null

started=$(date +%s)
wait_ready
echo "first start (seeding) ready after $(( $(date +%s) - started )) s"
docker logs "$app" 2>&1 | grep -q '"seeded": true' || fail "the fresh database was not seeded"

health=$(curl -fs "${base}/api/v1/health")
[[ "$health" == *'"read_only":true'* ]] || fail "health does not report read_only: ${health}"
curl -fs "${base}/" | grep -q '<div id="root"' || fail "the frontend is not served at /"
curl -fs "${base}/alerts" | grep -q '<div id="root"' || fail "app routes do not fall back"
curl -fs "${base}/api/v1/dashboard/summary" | grep -q '"kind":"synthetic"' || fail "no synthetic data"
curl -fs "${base}/api/v1/models/evaluation" | grep -q '"available":true' || fail "no evaluation"
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"label":"needs_investigation"}' "${base}/api/v1/alerts/1/feedback")
[[ "$status" == 403 ]] || fail "a review was not refused (HTTP ${status})"
curl -fsI "${base}/" | grep -qi '^x-frame-options: DENY' || fail "security headers missing"

docker restart "$app" >/dev/null
started=$(date +%s)
wait_ready
echo "restart ready after $(( $(date +%s) - started )) s"
docker logs "$app" 2>&1 | grep -q '"seeded": false' || fail "a restart reseeded the database"
echo "memory: $(docker stats --no-stream --format '{{.MemUsage}}' "$app")"
echo "PASS: public demo image"
