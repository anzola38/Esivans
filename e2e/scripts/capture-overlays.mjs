// Captura el modal de "Reiniciar demo" y el toast que deja (con o sin backend).
//   BASE_URL=http://localhost:18080 node scripts/capture-overlays.mjs
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE_URL, VIEWPORTS } from './env.mjs';

const { chromium } = await import('@playwright/test');

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, '..', process.env.OUT_DIR ?? 'screenshots');
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const viewport = VIEWPORTS[0];
const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });

await page.goto(BASE_URL + '/simulador', { waitUntil: 'networkidle' });
await page.getByTestId('reset-demo').click();
await page.waitForTimeout(400);
await page.screenshot({ path: resolve(outDir, 'reiniciar-modal-' + viewport.name + '.png') });

await page.getByTestId('reset-demo-confirm').click();
await page.locator('.ui-toast').waitFor();
await page.waitForTimeout(400);
await page.screenshot({ path: resolve(outDir, 'reiniciar-toast-' + viewport.name + '.png') });

await browser.close();
console.log('Capturas en', outDir);
