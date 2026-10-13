// Renders the sample dashboard photos (SVG) to PNG with Chromium, for the vision models that do
// not accept SVG. The PNG files are versioned next to the SVG ones, so nothing is rendered at run time.
//
//   node scripts/rasterize-photos.mjs            -> backend/app/seed/media/raster/<name>.png + index.json
//   node scripts/rasterize-photos.mjs 640 out/   -> another width or folder (used to compare sizes)
//
// index.json maps the SHA-256 of each SVG to its PNG: if an SVG changes and this script is not run
// again, the backend finds no PNG for it and asks the driver for the reading instead of guessing.
import './env.mjs';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const mediaDir = resolve(here, '../../backend/app/seed/media');
const width = Number(process.argv[2] ?? 800);
const outDir = resolve(process.argv[3] ?? join(mediaDir, 'raster'));
const RATIO = 520 / 800; // viewBox of the drawings

mkdirSync(outDir, { recursive: true });
const height = Math.round(width * RATIO);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
const index = {};
for (const file of readdirSync(mediaDir).filter((name) => name.endsWith('.svg')).sort()) {
  const svg = readFileSync(join(mediaDir, file));
  const name = file.replace(/\.svg$/, '');
  await page.setContent(
    '<style>html,body{margin:0;background:#000}img{display:block;width:' + width + 'px;height:' + height + 'px}</style>' +
      '<img src="data:image/svg+xml;base64,' + svg.toString('base64') + '">',
  );
  await page.waitForFunction(() => document.images[0].complete && document.images[0].naturalWidth > 0);
  const png = await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width, height } });
  writeFileSync(join(outDir, name + '.png'), png);
  index[createHash('sha256').update(svg).digest('hex')] = { file: name + '.png', width, height };
  console.log(name + '.png', width + 'x' + height, png.length + ' bytes');
}
writeFileSync(join(outDir, 'index.json'), JSON.stringify(index, null, 2) + '\n');
await browser.close();
