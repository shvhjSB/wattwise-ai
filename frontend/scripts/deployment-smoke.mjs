import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const workspace = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const artifactRoot = join(workspace, 'artifacts');
await mkdir(artifactRoot, { recursive: true });
const directory = await mkdtemp(join(artifactRoot, 'deployment-'));
const project = `wattwise-deploy-check-${randomUUID().slice(0, 8)}`;
const label = 'com.wattwise.deployment-verifier';
const volumes = [];
const environment = { ...process.env };
const port = process.env.WATTWISE_DEPLOY_CHECK_PORT ?? '8082';
assert(/^\d+$/.test(port) && Number(port) > 1024 && Number(port) < 65536);
const origin = `http://127.0.0.1:${port}`;
const recipe = join(workspace, 'deploy/compose.yaml');

function docker(args, allowFailure = false) {
  const result = spawnSync('docker', args, {
    cwd: workspace,
    env: environment,
    encoding: 'utf8',
    timeout: 180_000,
    maxBuffer: 5_000_000,
  });
  if (!allowFailure && result.status !== 0) {
    throw new Error(
      `Docker verification command failed: ${result.stderr || result.error?.message}`,
    );
  }
  return { status: result.status, output: result.stdout ?? '', error: result.stderr ?? '' };
}

function compose(args, allowFailure = false) {
  return docker(['compose', '-p', project, '-f', recipe, ...args], allowFailure);
}

function imageId(reference) {
  const image = JSON.parse(docker(['image', 'inspect', reference]).output)[0];
  assert(/^sha256:[0-9a-f]{64}$/.test(image.Id));
  return image.Id;
}

function createVolume(suffix) {
  const name = `${project}-${suffix}`;
  docker(['volume', 'create', '--label', `${label}=${project}`, name]);
  const info = JSON.parse(docker(['volume', 'inspect', name]).output)[0];
  assert.equal(info.Labels[label], project, 'Refusing to use an unowned volume');
  volumes.push(name);
  return name;
}

/** fetch, naming the request if the connection itself fails (CI showed only "fetch failed"). */
async function request(path, options) {
  try {
    return await fetch(new URL(path, origin), { ...options, signal: AbortSignal.timeout(15_000) });
  } catch (error) {
    throw new Error(`${options?.method ?? 'GET'} ${path}: ${error.cause?.code ?? error.message}`, {
      cause: error,
    });
  }
}

async function json(path, options) {
  const response = await request(path, options);
  assert(response.ok, `${path}: HTTP ${response.status}`);
  assert(response.headers.get('content-type')?.includes('application/json'));
  return response.json();
}

async function assertRelease(modelVersion, alertId, note) {
  const response = await request('/');
  assert.equal(response.status, 200);
  assert((await response.text()).includes('id="root"'));
  assert.equal((await json('/api/v1/ready')).status, 'ready');
  assert.equal((await json('/api/v1/health')).environment, 'production');
  assert.equal((await json('/api/v1/models/metadata')).version, modelVersion);
  assert.equal((await json('/api/v1/models/evaluation')).available, true);
  assert.equal((await json('/api/v1/models/metrics')).data_label, 'synthetic');
  const summary = await json('/api/v1/dashboard/summary');
  assert.equal(summary.readings, 5376);
  assert.deepEqual(summary.data_kinds, ['synthetic']);
  if (note !== undefined) {
    const detail = await json(`/api/v1/alerts/${alertId}`);
    assert(detail.feedback.some((item) => item.note === note));
  }
}

try {
  environment.WATTWISE_API_IMAGE = imageId(
    process.env.WATTWISE_DEPLOY_API_IMAGE ?? 'wattwise-api:demo',
  );
  environment.WATTWISE_FRONTEND_IMAGE = imageId(
    process.env.WATTWISE_DEPLOY_FRONTEND_IMAGE ?? 'wattwise-frontend:demo',
  );
  environment.WATTWISE_POSTGRES_VOLUME = createVolume('database');
  environment.WATTWISE_ARTIFACT_VOLUME = createVolume('artifacts');
  environment.WATTWISE_MODEL_DATA_KIND = 'synthetic';
  environment.WATTWISE_MODEL_VERSION = '20000101T000000Z-000000000000';
  environment.WATTWISE_PORT = port;
  const password = randomBytes(32).toString('hex');
  environment.WATTWISE_DB_PASSWORD_FILE = join(directory, 'db_password');
  environment.WATTWISE_DB_ADMIN_PASSWORD_FILE = join(directory, 'db_admin_password');
  environment.WATTWISE_DATABASE_URL_FILE = join(directory, 'database_url');
  await writeFile(environment.WATTWISE_DB_PASSWORD_FILE, password, { mode: 0o444 });
  await writeFile(environment.WATTWISE_DB_ADMIN_PASSWORD_FILE, randomBytes(32).toString('hex'), {
    mode: 0o444,
  });
  await writeFile(
    environment.WATTWISE_DATABASE_URL_FILE,
    `postgresql+psycopg://wattwise:${password}@db:5432/wattwise`,
    { mode: 0o444 },
  );
  const config = JSON.parse(compose(['config', '--format', 'json']).output);
  assert.equal(config.services.frontend.ports[0].host_ip, '127.0.0.1');
  assert.equal(config.services.api.ports, undefined);
  assert.equal(config.services.db.ports, undefined);
  assert.equal(config.volumes['postgres-data'].external, true);
  assert.equal(config.volumes.artifacts.external, true);
  assert.equal(config.services.api.read_only, true);
  assert.equal(config.services.frontend.read_only, true);
  assert.equal(config.services.api.environment.WATTWISE_DATABASE_URL, undefined);
  assert.equal(config.services.api.volumes[0].read_only, true);
  assert.equal(config.services.api.build, undefined);
  compose(['up', '-d', '--wait', '--wait-timeout', '120', 'db']);
  const privileges = compose([
    'exec',
    '-T',
    'db',
    'psql',
    '-U',
    'wattwise',
    '-d',
    'wattwise',
    '-At',
    '-c',
    "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname='wattwise'",
  ]);
  assert.equal(privileges.output.trim(), 'f');
  compose(['run', '--rm', '--no-deps', 'migrate']);
  const refused = compose(['up', '-d', '--wait', '--wait-timeout', '120', 'api'], true);
  assert.notEqual(refused.status, 0, 'Missing model must prevent API startup');
  const running = compose(['ps', '--status', 'running', '--services']).output.split(/\s+/);
  assert(!running.includes('api'));
  console.log('Deployment gate refuses a missing model before API startup.');
  const seeded = docker([
    'run',
    '--rm',
    '--network',
    `${project}_default`,
    '--env',
    'WATTWISE_SECRETS_DIR=/run/secrets',
    '--mount',
    `type=bind,source=${environment.WATTWISE_DATABASE_URL_FILE},target=/run/secrets/WATTWISE_DATABASE_URL,readonly`,
    '--mount',
    `type=volume,source=${environment.WATTWISE_ARTIFACT_VOLUME},target=/state`,
    environment.WATTWISE_API_IMAGE,
    'python',
    '-m',
    'wattwise.demo',
    '--artifacts',
    '/state',
  ]);
  const fixture = JSON.parse(seeded.output.trim().split('\n').at(-1));
  environment.WATTWISE_MODEL_VERSION = fixture.model_version;
  const modelVersion = fixture.model_version;
  assert(/^\d{8}T\d{6}Z-[0-9a-f]{12}$/.test(modelVersion));
  compose(['up', '-d', '--wait', '--wait-timeout', '180']);
  await assertRelease(modelVersion);
  const alertId = (await json('/api/v1/alerts')).items[0].alert_id;
  const note = `Deployment restore verification ${randomUUID()}`;
  await json(`/api/v1/alerts/${alertId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: 'needs_investigation', note }),
  });
  const write = compose(
    [
      'exec',
      '-T',
      'api',
      'python',
      '-c',
      "from pathlib import Path; Path('/state/forbidden').write_text('no')",
    ],
    true,
  );
  assert.notEqual(write.status, 0, 'The running API must not write model artifacts');
  const inspected = JSON.parse(
    docker(['inspect', compose(['ps', '-q', 'api']).output.trim()]).output,
  )[0];
  assert(!inspected.Config.Env.some((value) => value.includes(password)));
  const wrongPin = compose(
    [
      'run',
      '--rm',
      '--no-deps',
      'check',
      'python',
      '-m',
      'wattwise.operations',
      'check',
      '--model-version',
      '20000101T000000Z-000000000000',
    ],
    true,
  );
  assert.notEqual(wrongPin.status, 0);
  assert(wrongPin.error.includes('model_version_mismatch'));
  await assertRelease(modelVersion, alertId, note);
  compose(['down', '--volumes']);
  for (const volume of volumes) docker(['volume', 'inspect', volume]);
  compose(['up', '-d', '--wait', '--wait-timeout', '180']);
  await assertRelease(modelVersion, alertId, note);
  console.log(
    'Private deployment starts, rejects writes/wrong model pins, and survives recreation.',
  );
  compose(['stop', 'frontend', 'api']);
  compose([
    'exec',
    '-T',
    'db',
    'pg_dump',
    '-U',
    'wattwise',
    '-Fc',
    '-f',
    '/tmp/wattwise.dump',
    'wattwise',
  ]);
  compose(['cp', 'db:/tmp/wattwise.dump', join(directory, 'database.dump')]);
  assert((await readFile(join(directory, 'database.dump'))).length > 0);
  docker([
    'run',
    '--rm',
    '--network',
    'none',
    '--user',
    '0',
    '--entrypoint',
    'tar',
    '--mount',
    `type=volume,source=${environment.WATTWISE_ARTIFACT_VOLUME},target=/state,readonly`,
    '--mount',
    `type=bind,source=${directory},target=/backup`,
    environment.WATTWISE_API_IMAGE,
    '-czf',
    '/backup/artifacts.tgz',
    '-C',
    '/state',
    '.',
  ]);
  compose(['down']);
  environment.WATTWISE_POSTGRES_VOLUME = createVolume('restored-database');
  environment.WATTWISE_ARTIFACT_VOLUME = createVolume('restored-artifacts');
  docker([
    'run',
    '--rm',
    '--network',
    'none',
    '--user',
    '0',
    '--entrypoint',
    'tar',
    '--mount',
    `type=volume,source=${environment.WATTWISE_ARTIFACT_VOLUME},target=/state`,
    '--mount',
    `type=bind,source=${directory},target=/backup,readonly`,
    environment.WATTWISE_API_IMAGE,
    '-xzf',
    '/backup/artifacts.tgz',
    '-C',
    '/state',
  ]);
  compose(['up', '-d', '--wait', '--wait-timeout', '120', 'db']);
  compose(['cp', join(directory, 'database.dump'), 'db:/tmp/wattwise.dump']);
  compose([
    'exec',
    '-T',
    'db',
    'pg_restore',
    '-U',
    'wattwise',
    '--exit-on-error',
    '--no-owner',
    '--no-acl',
    '-d',
    'wattwise',
    '/tmp/wattwise.dump',
  ]);
  compose(['up', '-d', '--wait', '--wait-timeout', '180']);
  await assertRelease(modelVersion, alertId, note);
  console.log(
    'Backup restore into fresh external database/artifact volumes preserves the model and review.',
  );
} catch (error) {
  // Keep the evidence: the project is torn down below. API and Nginx logs hold no URLs, bodies
  // or secrets (D059); the database's logs are deliberately not printed.
  const logs = compose(['logs', '--no-color', '--tail', '150', 'api', 'frontend'], true);
  console.error(`--- api and frontend logs before teardown ---
${logs.output}${logs.error}`);
  const states = compose(['ps', '-a', '--format', 'json'], true);
  console.error(`--- container states ---
${states.output}`);
  throw error;
} finally {
  if (environment.WATTWISE_DB_PASSWORD_FILE !== undefined)
    compose(['down', '--remove-orphans'], true);
  for (const volume of volumes) {
    const info = JSON.parse(docker(['volume', 'inspect', volume]).output)[0];
    assert.equal(info.Labels[label], project, 'Refusing cleanup of an unowned volume');
    docker(['volume', 'rm', volume]);
  }
  assert(resolve(directory).startsWith(resolve(artifactRoot) + sep));
  await rm(directory, { recursive: true, force: true });
}
