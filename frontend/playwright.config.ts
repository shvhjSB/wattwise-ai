import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const state = process.env.WATTWISE_E2E_STATE;
if (!state)
  throw new Error('Run browser tests with npm run test:e2e to create an isolated fixture.');
const backend = resolve(import.meta.dirname, '../backend');
const python = resolve(
  backend,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['junit', { outputFile: 'test-results/browser.xml' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:4175',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python.replaceAll('\\', '/')}" -m tests.browser_fixture serve --state "${state.replaceAll('\\', '/')}"`,
      cwd: backend,
      url: 'http://127.0.0.1:8765/api/v1/ready',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command:
        'node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 4175 --strictPort',
      url: 'http://127.0.0.1:4175',
      env: { WATTWISE_DEV_API_TARGET: 'http://127.0.0.1:8765' },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
  projects: [
    { name: 'desktop-light', use: { ...devices['Desktop Chrome'], colorScheme: 'light' } },
    { name: 'desktop-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark' } },
    {
      name: 'mobile',
      use: { ...devices['Pixel 5'], viewport: { width: 390, height: 844 }, colorScheme: 'light' },
    },
  ],
});
