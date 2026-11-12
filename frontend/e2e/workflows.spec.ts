import { expect, test, type Page } from '@playwright/test';

/** The Compose demo (an external base URL) holds only the synthetic sample; the standalone
 * fixture also has a synthetic multi-meter factory (backend/tests/factory_data.py). */
const composeDemo = Boolean(process.env.WATTWISE_E2E_BASE_URL?.trim());

let browserErrors: string[];
test.beforeEach(({ page }) => {
  browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
});
test.afterEach(() => {
  expect(browserErrors).toEqual([]);
});

async function noPageOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

test('overview → alert → feedback persists after reload', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 2, name: 'Overview' })).toBeVisible();
  await expect(page.getByRole('note', { name: 'Demo data' })).toBeVisible();
  await expect(page.getByLabel('Measured energy', { exact: true })).toBeVisible();
  await expect(page.getByText('Online', { exact: true })).toBeVisible();
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('overview.png'), fullPage: true });
  await page.getByRole('link', { name: 'Alerts', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Explanation', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Event in context' })).toBeVisible();
  const note = `Browser review: ${info.project.name}`;
  await page.getByLabel('Note (optional)').fill(note);
  await page.getByLabel('Reviewer (optional)').fill('Synthetic browser test');
  await page.getByRole('button', { name: 'Save review', exact: true }).click();
  await expect(page.getByText(note, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(note, { exact: true })).toBeVisible();
  await expect(page.getByText(/Saving one does not retrain/)).toBeVisible();
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('alert-review.png'), fullPage: true });
});

test('model lab shows real metrics, filterable buildings and dataset health', async ({
  page,
}, info) => {
  await page.goto('/models');
  await expect(page.getByRole('heading', { name: 'Model lab', exact: true })).toBeVisible();
  await expect(page.getByText('Validation and test errors', { exact: true })).toBeVisible();
  const metrics = page.getByRole('region', { name: 'Recorded metrics', exact: true });
  await expect(metrics.getByText('Data provenance: Synthetic', { exact: true })).toBeVisible();
  await expect(metrics.getByText('Data provenance: Observed', { exact: true })).toHaveCount(0);
  await expect(page.getByText('seasonal-naive-1w', { exact: true })).toBeVisible();
  await expect(page.getByText(/Missing values: 6/)).toBeVisible();
  await expect(page.getByText('No recorded analyses', { exact: true })).toBeVisible();
  await expect(page.getByText('syn-retail-b', { exact: true })).toBeVisible();
  await page.getByLabel('Building identifier').fill('syn-retail-b');
  await page.getByRole('button', { name: 'Find building' }).click();
  await expect(page).toHaveURL(/building=syn-retail-b/);
  const buildingTable = page.getByRole('table', { name: 'Test errors by building' });
  await expect(buildingTable.getByRole('row')).toHaveCount(2);
  await page.reload();
  await expect(buildingTable.getByRole('row')).toHaveCount(2);
  await page.getByText('Settings, features and reproducibility', { exact: true }).click();
  await expect(page.getByText(/Data fingerprint:/)).toBeVisible();
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('model-lab.png'), fullPage: true });
});

test('model lab recovers from an API failure and handles no matching building', async ({
  page,
}) => {
  await page.route('**/api/v1/models/metadata', (route) =>
    route.fulfill({ status: 503, json: { detail: 'Browser test failure' } }),
  );
  await page.goto('/models');
  await expect(page.getByText('Served model unavailable', { exact: true })).toBeVisible();
  await expect(page.getByText('Dataset health', { exact: true })).toBeVisible();
  await page.unroute('**/api/v1/models/metadata');
  const servedModel = page.getByRole('region', { name: 'Served model', exact: true });
  await servedModel.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(servedModel.getByText('lightgbm', { exact: true })).toBeVisible();
  await page.getByLabel('Building identifier').fill('does-not-exist');
  await page.getByRole('button', { name: 'Find building' }).click();
  await expect(page.getByText('No matching building errors', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole('table', { name: 'Test errors by building' }).getByRole('row'),
  ).toHaveCount(5);
  await noPageOverflow(page);
});

test('data health shows the stored audit and filters meters', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Data health', exact: true }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Data health' })).toBeVisible();
  const audit = page.getByRole('region', { name: 'Data-quality audit' });
  await expect(audit.getByText(/of expected intervals/)).toBeVisible();
  await expect(
    audit.getByRole('table').getByText('Duplicate timestamps', { exact: true }),
  ).toBeVisible();
  await audit.getByRole('checkbox', { name: 'Warnings only' }).check();
  await expect(page).toHaveURL(/warnings=1/);
  await expect(audit.getByText(/^\d+ warnings?$/).first()).toBeVisible();
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('data-health.png'), fullPage: true });
});

test('model lab shows data drift against the training period', async ({ page }) => {
  await page.goto('/models');
  const drift = page.getByRole('region', { name: 'Data drift' });
  await expect(drift.getByRole('table')).toBeVisible();
  await expect(drift.getByText(/not failure/)).toBeVisible();
  await expect(drift.getByRole('columnheader', { name: /In interval/ })).toBeVisible();
  await drift.getByLabel(/Group by/).selectOption('month');
  await expect(page).toHaveURL(/driftPeriod=month/);
  await expect(drift.getByRole('columnheader', { name: 'Month' })).toBeVisible();
  await noPageOverflow(page);
});

test('what-if lab tries a scenario without changing the recording', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'What-if lab', exact: true }).click();
  await expect(page.getByText('Choose a meter', { exact: true })).toBeVisible();
  await page.getByPlaceholder('Meter ID').fill('syn-office-a:electricity');
  await page.getByRole('button', { name: 'Explore', exact: true }).click();
  const scenario = page.getByRole('region', { name: 'Scenario' });
  const totals = scenario.getByRole('table', { name: 'Scenario totals' });
  await expect(totals.getByText('Recorded', { exact: true })).toBeVisible();
  const recorded = await totals.getByRole('row').first().innerText();
  await scenario.getByLabel('Cut, percent').fill('30');
  await expect(totals.getByText('Consumption under the scenario', { exact: true })).toBeVisible();
  expect(await totals.getByRole('row').first().innerText()).toBe(recorded);
  await expect(scenario.getByRole('note')).toContainText('recorded readings are unchanged');
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('what-if.png'), fullPage: true });
});

test('bill analyser checks a synthetic bill without sending it anywhere', async ({
  page,
}, info) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Bill analyser', exact: true }).click();
  await expect(page.getByRole('note', { name: 'How the bill analyser works' })).toBeVisible();
  const apiCalls: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.includes('/api/')) apiCalls.push(path);
  });
  await page.getByRole('button', { name: 'Fill in a synthetic example', exact: true }).click();
  const checks = page.getByRole('region', { name: 'Checks against the bill' });
  await expect(
    checks.getByText('The charges add up to the total payable: ₹507,280.00.'),
  ).toBeVisible();
  await page.getByLabel(/Fuel and other surcharges/).fill('3600');
  await expect(checks.getByText(/a difference of ₹32,400\.00/)).toBeVisible();
  const tod = page.getByRole('region', { name: 'Time of day' });
  await tod.getByLabel('Move from').selectOption('1');
  await tod.getByLabel('Move to').selectOption('2');
  await expect(tod.getByRole('status')).toContainText('would save ₹1,225.00');
  expect(apiCalls).toEqual([]);
  expect(new URL(page.url()).search).toBe('');
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('bill.png'), fullPage: true });
});

test('machines page compares each meter of a site with its main meter', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Machines', exact: true }).click();
  await expect(page.getByText('Choose a building', { exact: true })).toBeVisible();
  if (composeDemo) {
    // The Compose demo holds only the synthetic sample, one meter per building: the real API
    // must say why there is nothing to compare.
    await page.getByPlaceholder('Building ID').fill('syn-office-a');
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    await expect(page.getByText('No comparison for this building', { exact: true })).toBeVisible();
    await expect(page.getByText(/this building has 1./)).toBeVisible();
    await noPageOverflow(page);
    return;
  }
  await page.getByPlaceholder('Building ID').fill('test-factory');
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  const section = page.getByRole('region', { name: 'Machine comparison' });
  await expect(section.getByText('Data provenance: Synthetic', { exact: true })).toBeVisible();
  const press = section.getByRole('row', { name: /test-factory:press/ });
  await expect(press).toContainText('3,280 kWh');
  await expect(press).toContainText('13.2%');
  await expect(press).toContainText('80 kWh');
  await expect(section.getByRole('row', { name: /Not metered separately/ })).toContainText('81.3%');
  await page.getByLabel('Sat').check();
  await expect(page).toHaveURL(/days=0%2C1%2C2%2C3%2C4%2C5/);
  await section.getByLabel('Main meter').selectOption('test-factory:press');
  await expect(section.getByText('(chosen)', { exact: true })).toBeVisible();
  await expect(section.getByRole('alert')).toContainText('Check the main meter.');
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('machines.png'), fullPage: true });
});

test('meter check reads a file in the browser and finds the left-on Sunday', async ({
  page,
}, info) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Meter check', exact: true }).click();
  await expect(page.getByText('Choose a meter file', { exact: true })).toBeVisible();
  const apiCalls: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.includes('/api/')) apiCalls.push(path);
  });
  await page.getByRole('button', { name: 'Use a synthetic example', exact: true }).click();
  const unusual = page.getByRole('region', { name: 'Unusual periods' });
  await expect(unusual.getByRole('row', { name: /2018-01-21 00:00/ })).toContainText('higher');
  await expect(
    page.getByRole('region', { name: 'Use while closed' }).getByText(/31\.6% of all use/),
  ).toBeVisible();
  await page.getByLabel('Meter file').setInputFiles({
    name: 'meter.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('time,kWh\n2018-02-01 00:00,5\n2018-02-01 00:15,6\n2018-02-01 00:30,7\n'),
  });
  await expect(
    page.getByRole('region', { name: 'Data check' }).getByText('15 minutes', { exact: true }),
  ).toBeVisible();
  expect(apiCalls).toEqual([]);
  expect(new URL(page.url()).search).toBe('');
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath('meter.png'), fullPage: true });
});
