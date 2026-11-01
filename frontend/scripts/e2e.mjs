import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = resolve(frontend, '..');
const backend = join(workspace, 'backend');
const python = join(
  backend,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const artifactRoot = join(workspace, 'artifacts', 'e2e');
await mkdir(artifactRoot, { recursive: true });
const runDirectory = await mkdtemp(join(artifactRoot, 'run-'));
const state = join(runDirectory, 'state.json');
const env = { ...process.env, WATTWISE_E2E_STATE: state, VITE_API_BASE_URL: '' };

function run(command, args, cwd) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit' });
    child.once('error', reject);
    child.once('exit', (code) => resolveRun(code ?? 1));
  });
}

let status = 1;
try {
  for (const [command, args, cwd] of [
    [process.execPath, ['node_modules/typescript/bin/tsc', '-b'], frontend],
    [process.execPath, ['node_modules/vite/bin/vite.js', 'build'], frontend],
    [python, ['-m', 'tests.browser_fixture', 'prepare', '--state', state], backend],
    [
      process.execPath,
      ['node_modules/@playwright/test/cli.js', 'test', ...process.argv.slice(2)],
      frontend,
    ],
  ]) {
    status = await run(command, args, cwd);
    if (status !== 0) break;
  }
} catch (error) {
  status = 1;
  console.error(error.message);
} finally {
  const cleaned = await run(
    python,
    ['-m', 'tests.browser_fixture', 'cleanup', '--state', state],
    backend,
  );
  if (cleaned !== 0) status = cleaned;
  if (
    cleaned === 0 &&
    dirname(runDirectory) === artifactRoot &&
    runDirectory.startsWith(join(artifactRoot, 'run-'))
  ) {
    await rm(runDirectory, { recursive: true, force: true });
  }
  process.exitCode = status;
}
