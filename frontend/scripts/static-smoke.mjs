// Check the static demo (T050) the way GitHub Pages serves it: files under /wattwise-ai/, and
// 404.html (a copy of index.html) for any other path, so deep links load the app.
// Usage, after `WATTWISE_BASE=/wattwise-ai/ VITE_SNAPSHOT=1 npm run build` and copying the
// snapshot into dist/snapshot and dist/index.html to dist/404.html:
//   node scripts/static-smoke.mjs [dist]
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';

const frontend = resolve(fileURLToPath(new URL('..', import.meta.url)));
const dist = resolve(process.argv[2] ?? join(frontend, 'dist'));
const BASE = '/wattwise-ai/';
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};
const NOT_RECORDED = 'not part of the static demo';

async function file(path) {
  try {
    if ((await stat(path)).isFile()) return await readFile(path);
  } catch {
    // missing
  }
  return null;
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', 'http://localhost');
  let body = null;
  let type = TYPES['.html'];
  if (url.pathname.startsWith(BASE)) {
    const relative = decodeURIComponent(url.pathname.slice(BASE.length)) || 'index.html';
    const target = normalize(join(dist, relative));
    if (target.startsWith(dist + sep) || target === dist) {
      body = await file(target);
      type = TYPES[extname(target)] ?? 'application/octet-stream';
    }
  }
  if (body === null) {
    response.writeHead(404, { 'content-type': TYPES['.html'] });
    response.end(await readFile(join(dist, '404.html')));
    return;
  }
  response.writeHead(200, { 'content-type': type });
  response.end(body);
});
await new Promise((ready) => server.listen(0, '127.0.0.1', ready));
const origin = `http://127.0.0.1:${String(server.address().port)}`;

const index = JSON.parse(await readFile(join(dist, 'snapshot', 'index.json'), 'utf8'));
const meter = Object.keys(index.entries)
  .map((key) => /^\/api\/v1\/meters\/([^/?]+)\/expectation/.exec(key)?.[1])
  .find(Boolean);

const pages = [
  ['', 'Overview'],
  ['explorer', 'Buildings & meters'],
  ['alerts', 'Alerts'],
  ['impact', 'Cost impact'],
  [`whatif?meter=${encodeURIComponent(meter ?? '')}&days=all`, 'What-if lab'],
  ['bill', 'Bill analyser'],
  ['data', 'Data health'],
  ['models', 'Model lab'],
];

const failures = [];
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`));
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/snapshot/') && response.status() !== 200) {
      failures.push(`HTTP ${String(response.status())} for ${url}`);
    }
  });
  for (const [path, heading] of pages) {
    await page.goto(`${origin}${BASE}${path}`);
    try {
      await page.getByRole('heading', { level: 2, name: heading, exact: true }).waitFor();
      await page.waitForLoadState('networkidle');
    } catch (error) {
      failures.push(`/${path}: ${error.message.split('\n')[0]}`);
      continue;
    }
    const text = await page.locator('main').innerText();
    if (text.includes(NOT_RECORDED)) failures.push(`/${path}: shows "${NOT_RECORDED}"`);
    if (/unavailable/i.test(text)) failures.push(`/${path}: shows an unavailable state`);
    console.log(`ok  /${path}`);
  }
  // The highest-priority alert opens with its evidence, and reviews are refused politely.
  await page.goto(`${origin}${BASE}alerts`);
  await page.getByRole('heading', { name: 'Explanation', exact: true }).waitFor();
  await page
    .getByText(/read-only/)
    .first()
    .waitFor();
  // Navigation keeps the base path.
  await page.getByRole('link', { name: 'Data health', exact: true }).click();
  if (!page.url().startsWith(`${origin}${BASE}data`))
    failures.push(`navigation left the base: ${page.url()}`);
  console.log('ok  alert detail, read-only review, navigation');
} finally {
  await browser.close();
  server.close();
}

if (failures.length) {
  console.error(`FAIL\n${failures.join('\n')}`);
  process.exit(1);
}
console.log(
  `PASS: ${String(pages.length)} pages from ${String(Object.keys(index.entries).length)} recorded answers`,
);
