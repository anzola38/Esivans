// Capturas de pantalla a 1366x768 y 1920x1080.
//
//   node scripts/capture.mjs                      -> rutas por defecto
//   node scripts/capture.mjs /consola /alertas    -> solo esas rutas
//   BASE_URL=http://localhost:18080 OUT_DIR=../docs/screenshots node scripts/capture.mjs
//   FULL_PAGE=1 ...                               -> ademas guarda la pagina completa (-full.png)
//
// Tambien revisa que no haya desborde horizontal y que el pie tenga el rotulo exacto.
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE_URL, VIEWPORTS } from './env.mjs';

const { chromium } = await import('@playwright/test');

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, '..', process.env.OUT_DIR ?? 'screenshots');
const fullPage = process.env.FULL_PAGE === '1';
const FOOTER = 'Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección';

const args = process.argv.slice(2);
const routes = args.length
  ? args
  : ['/simulador', '/consola', '/alertas', '/tablero', '/guia-estilo'];

mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
let problems = 0;

for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => {
    problems++;
    console.error('  ERROR de JavaScript:', error.message);
  });

  for (const route of routes) {
    await page.goto(BASE_URL + route, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);

    const slug = route.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-') || 'inicio';
    const file = resolve(outDir, slug + '-' + viewport.name + '.png');
    await page.screenshot({ path: file });

    const report = await page.evaluate(() => {
      const doc = document.documentElement;
      const content = document.querySelector('main.content');
      return {
        overflowX: doc.scrollWidth > doc.clientWidth,
        contentOverflowX: content ? content.scrollWidth > content.clientWidth : false,
        footer: document.querySelector('footer')?.textContent?.trim() ?? '',
        font: getComputedStyle(document.body).fontFamily,
        latoLoaded: document.fonts.check('16px Lato'),
        contentHeight: content ? content.scrollHeight : 0,
      };
    });

    const notes = [];
    if (report.overflowX || report.contentOverflowX) notes.push('DESBORDE HORIZONTAL');
    if (report.footer !== FOOTER) notes.push('PIE DISTINTO: "' + report.footer + '"');
    if (!report.latoLoaded) notes.push('LATO NO CARGADA');
    problems += notes.length;
    console.log(viewport.name, route, '->', file, notes.length ? '| ' + notes.join(' | ') : '| ok');

    if (fullPage && report.contentHeight > viewport.height) {
      // El contenido hace scroll dentro de <main>: se agranda la ventana para verlo entero.
      await page.setViewportSize({ width: viewport.width, height: report.contentHeight + 120 });
      await page.waitForTimeout(200);
      await page.screenshot({ path: file.replace(/\.png$/, '-full.png') });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
    }
  }
  await context.close();
}

await browser.close();
console.log(problems ? 'Problemas encontrados: ' + problems : 'Sin problemas automáticos.');
process.exit(problems ? 1 : 0);
