# Security controls and limits

T037 hardens the demo/API; it does **not** make an authenticated public service. Keep the
Compose deployment loopback-only. The one public deployment (T046, D064) is the synthetic demo in
**read-only mode** (`WATTWISE_READ_ONLY=true`): every API request other than GET, HEAD and
OPTIONS answers 403, it holds no real or private data, and it has no accounts. Before exposing private building data or feedback writes,
add authentication/authorization, TLS, edge rate limits and a deployment-specific origin policy.
CORS only controls browser response access: it neither authenticates callers nor prevents
non-browser requests or cross-origin simple POSTs. No cookies or credentialed CORS are enabled.

## Request controls

Settings use the `WATTWISE_` prefix and are validated at startup:

| Setting | Default | Meaning |
|---|---|---|
| `CORS_ORIGINS` | `[]` | JSON array of exact HTTP(S) origins; no paths, credentials or wildcards |
| `MAX_REQUEST_BYTES` | `32000000` | Entire body, counted while streaming before multipart parsing consumes each chunk |
| `MAX_UPLOAD_BYTES` | `10000000` | Additional per-CSV limit in the upload/analyze endpoints |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Overall HTTP response deadline (maximum 300 seconds) |
| `MAX_CONCURRENT_REQUESTS` | `16` | Maximum active application requests per worker, including work past its HTTP deadline |

Malformed/duplicate Content-Length returns 400; a declared or streamed excess returns 413.
Absent Content-Length does not bypass byte counting. At capacity, new requests return 503.
The deadline returns 504 before response headers are sent, suppresses later output, and keeps
the slot occupied until the underlying request finishes. Slow request-body reads also have
the remaining deadline, so they cannot retain a slot forever by withholding bytes.

**A timeout is not cancellation of computation or a transaction.** Python threads/native ML
work cannot safely be killed; feedback may finish committing after the caller receives 504.
Read the current state before retrying a write. Per-worker capacity prevents an unbounded queue
of such work, but CPU/GIL saturation can delay the event loop. These are response deadlines,
not hard process CPU/memory limits. Use process/container budgets and an authenticated job
queue for hostile workloads. The API currently returns finite JSON, not streaming responses;
an already-started response cannot be replaced with a different status.

Nginx additionally limits bodies to 32 MiB, header/body inactivity to 15 seconds, connection
setup to 5 seconds, and upstream reads to 65 seconds. The API's decimal-byte ceiling is slightly
smaller and normally answers first. Keep both layers aligned when changing the API settings.
The proxy adds nosniff, no-referrer and frame-denial headers; API responses use no-store and
nosniff. Same-origin Vite/Nginx access needs no CORS entry. Health preflights are handled by CORS.

## Errors and logs

- Unhandled errors return only `Internal server error`; database operational errors remain a
  safe 503. Validation errors expose locations/types, not submitted values, exception messages
  or validator context. Deliberate CSV contract reports still contain useful submitted row examples.
- Missing/incompatible models retain the explicit no-predictions state without exposing local
  registry paths or internal exceptions.
- API access records are JSON: generated request ID, method, route **template**, status, duration
  and exception class (when unhandled). They omit raw paths/query strings, bodies, headers,
  credentials, feedback text and connection URLs. The response exposes `X-Request-ID`.
- Run Uvicorn with `--no-access-log` (the container already does); its default access log includes
  raw URLs. Nginx JSON access records include only method, status and duration. Framework/server
  diagnostics are separate operational logs: restrict access and retention, and never enable
  SQL echo or debug tracebacks on a public deployment.

## Automated checks

CI fails closed when an audit/scanner cannot run. No `continue-on-error`, audit fixes or secret
allowlists are used:

- `pip-audit` checks the hashed, locked runtime **and development** dependency export at all
  severities, without invoking pip resolution. The local project itself is excluded from export.
- `npm audit --omit=dev --audit-level=low` blocks any known runtime advisory.
- `npm audit --audit-level=high` reports the entire tree and blocks high/critical tooling issues.
  Moderate/low development-tool advisories remain visible and require review; this threshold
  is not a claim of a zero-advisory tree.
- Digest-pinned Gitleaks scans full Git history with 100% redacted findings, a read-only mount
  and no scanner network. CI checks out full history. Ignored local `.env` files are not scanned
  or uploaded. A suspected real exposure requires credential rotation, not just deleting a line.

### Known tooling advisory (2026-11-01)

The full npm tree reports **13 moderate package findings** from one root advisory,
[GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249), in minimatch used by
ESLint/typescript-eslint/accessibility tooling. Runtime audit reports zero. The advisory lists
versions below 11.0.1; the current consumers require minimatch 3 or 10. A forced major override
would change the callable API used by older consumers, and npm's proposed force fix downgrades
TypeScript tooling rather than proving a compatible fix. No forced downgrade/override is applied.
Do not feed untrusted glob configurations to these tools. Recheck compatible upstream releases
before public deployment; this documented development-only risk remains unresolved.

## Reproduce

From `backend/` (delete the temporary export afterwards):

```bash
uv export --locked --no-emit-project --format requirements-txt --output-file /tmp/wattwise-audit.txt > /dev/null
uv run --locked pip-audit --disable-pip --require-hashes -r /tmp/wattwise-audit.txt --progress-spinner off
```

From `frontend/`, run both npm audit commands above. To scan history from the repository root:

```bash
docker run --rm --network none --mount "type=bind,source=$(pwd),target=/repo,readonly" \
  ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  git /repo --redact=100 --no-banner --log-opts=--all
```

Tool behavior: [pip-audit](https://github.com/pypa/pip-audit),
[Gitleaks](https://github.com/gitleaks/gitleaks).
