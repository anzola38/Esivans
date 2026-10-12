import { defineConfig } from '@playwright/test';
import { BASE_URL, VIEWPORTS } from './scripts/env.mjs';

// Los navegadores viven en e2e/node_modules (lo fija scripts/env.mjs).
// La base de la demo es compartida: un solo worker, sin paralelismo y sin reintentos.
export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  globalSetup: './tests/support/global-setup.mjs',
  globalTeardown: './tests/support/global-teardown.mjs',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    permissions: ['clipboard-read', 'clipboard-write'],
  },
  projects: VIEWPORTS.map((viewport) => ({
    name: viewport.name,
    use: { browserName: 'chromium', viewport: { width: viewport.width, height: viewport.height } },
  })),
});
