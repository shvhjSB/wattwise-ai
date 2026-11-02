import { expect, test, type Page } from '@playwright/test';

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
