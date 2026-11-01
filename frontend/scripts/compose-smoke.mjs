import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const state = resolve(frontend, '../artifacts/compose-verification.json');
const base = new URL(process.env.WATTWISE_COMPOSE_URL ?? 'http://127.0.0.1:8080');
assert(base.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(base.hostname));
assert(!base.username && !base.password && base.pathname === '/');
const command = process.argv[2] ?? 'initial';

async function response(path, options = {}) {
  return fetch(new URL(path, base), { ...options, signal: AbortSignal.timeout(15_000) });
}

async function json(path, options) {
  const result = await response(path, options);
  assert(result.ok, `${path}: HTTP ${result.status}`);
  assert(result.headers.get('content-type')?.includes('application/json'));
  return result.json();
}

if (command === 'browser') {
  const child = spawn(process.execPath, ['node_modules/@playwright/test/cli.js', 'test'], {
    cwd: frontend,
    env: { ...process.env, WATTWISE_E2E_BASE_URL: base.origin },
    stdio: 'inherit',
  });
  process.exitCode = await new Promise((resolveExit, reject) => {
    child.once('error', reject);
    child.once('exit', (code) => resolveExit(code ?? 1));
  });
} else {
  assert(['initial', 'restored'].includes(command));
  const index = await response('/');
  assert.equal(index.status, 200);
  const html = await index.text();
  assert(html.includes('id="root"'));
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map((match) => match[1]);
  assert(assets.length >= 2);
  for (const asset of assets) assert.equal((await response(asset)).status, 200);
  assert((await (await response('/models')).text()).includes('id="root"'));
  const missing = await response('/api/v1/does-not-exist');
  assert.equal(missing.status, 404);
  assert(missing.headers.get('content-type')?.includes('application/json'));
  assert.equal((await json('/api/v1/health')).status, 'ok');
  await json('/api/v1/ready');
  const summary = await json('/api/v1/dashboard/summary');
  assert.deepEqual(summary.data_kinds, ['synthetic']);
  assert.equal(summary.readings, 5376);
  assert.equal(summary.missing_values, 6);
  assert.equal(summary.buildings, 4);
  const metadata = await json('/api/v1/models/metadata');
  const metrics = await json('/api/v1/models/metrics');
  const evaluation = await json('/api/v1/models/evaluation');
  assert.equal(metrics.data_label, 'synthetic');
  assert.equal(evaluation.available, true);
  assert.equal(evaluation.version, metadata.version);
  const alerts = await json('/api/v1/alerts');
  assert(alerts.total > 0);
  if (command === 'initial') {
    const alertId = alerts.items[0].alert_id;
    const note = `Compose persistence check ${randomUUID()}`;
    await json(`/api/v1/alerts/${alertId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: 'needs_investigation', note }),
    });
    await mkdir(dirname(state), { recursive: true });
    await writeFile(
      state,
      JSON.stringify({ origin: base.origin, version: metadata.version, alertId, note }),
    );
  } else {
    const saved = JSON.parse(await readFile(state, 'utf8'));
    assert.equal(saved.origin, base.origin);
    assert.equal(metadata.version, saved.version);
    const detail = await json(`/api/v1/alerts/${saved.alertId}`);
    assert(detail.feedback.some((item) => item.note === saved.note));
  }
  console.log(
    `Compose ${command} verification passed: built assets, SPA, proxy, readiness, synthetic data, model, evaluation and feedback.`,
  );
}
