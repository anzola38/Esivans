import { defineConfig } from '@playwright/test';
import { BASE_URL, VIEWPORTS } from './scripts/env.mjs';

// Los navegadores viven en e2e/node_modules (lo fija scripts/env.mjs).
export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
    screenshot: 'only-on-failure',
  },
  projects: VIEWPORTS.map((viewport) => ({
    name: viewport.name,
    use: { browserName: 'chromium', viewport: { width: viewport.width, height: viewport.height } },
  })),
});
