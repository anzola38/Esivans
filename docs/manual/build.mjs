// Ensambla el manual de usuario y lo imprime en PDF con el Chromium de Playwright.
//
//   node docs/manual/build.mjs
//       -> docs/manual/manual.html y docs/manual/Manual_de_usuario.pdf
//   OUT=<carpeta> node docs/manual/build.mjs   -> deja el PDF en otra carpeta (el HTML siempre queda aqui,
//                                                 porque las rutas img/ y fonts/ son relativas a docs/manual/)
//   ONLY=03-simulador node docs/manual/build.mjs -> solo los fragmentos cuyo nombre contiene ese texto
//   FECHA="13 de octubre de 2026" node docs/manual/build.mjs -> fija la fecha de la portada (por defecto, hoy)
//
// Que hace:
//   1. Une sections/NN-*.html en orden (01..12 son capitulos; 90 y 91 son los anexos A y B).
//   2. Numera capitulos, secciones y figuras, arma la portada, la tabla de contenido y el indice de figuras,
//      y resuelve las referencias cruzadas (<a class="xref" href="#id"></a> -> "sección 5.3").
//   3. Imprime borradores para medir (con page-gaps.py) el hueco al final de cada pagina y encoger las figuras
//      que saltaron de pagina por poco; despues lee en que pagina cae cada titulo y cada figura (toc-pages.py)
//      y pone esos numeros en la tabla de contenido. Los dos guiones necesitan "uv"; si no esta disponible,
//      la tabla queda con enlaces y sin numeros de pagina.
//   4. Reduce las capturas a la resolucion de impresion solo dentro del PDF (los PNG de img/ no se tocan).
//
// El encabezado, el pie y "Pagina N de M" salen de @page en manual.css. No necesita la demo encendida.
import { readFileSync, readdirSync, writeFileSync, mkdirSync, existsSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import '../../e2e/scripts/env.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, '../../e2e/package.json'));
const { chromium } = require('@playwright/test');

const TITLE = 'Manual de usuario';
const SUBTITLE = 'Sistema de suministro de combustible · Transportes Esivans S.A.S.';
const FOOTER = 'Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección';
const PDF_NAME = 'Manual_de_usuario.pdf';
const PRINT_DPI = Number(process.env.DPI ?? 200); // resolucion de las capturas dentro del PDF
const JPEG_QUALITY = Number(process.env.JPEG_QUALITY ?? 0.86);

const today = process.env.FECHA
  ?? new Intl.DateTimeFormat('es-CO', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date());

const only = process.env.ONLY;
const files = readdirSync(resolve(here, 'sections'))
  .filter((name) => /^\d\d-.*\.html$/.test(name) && !name.startsWith('00-') && (!only || name.includes(only)))
  .sort();

const chapters = files
  .map((name) => {
    const annex = name.startsWith('9');
    return `<section class="chapter${annex ? ' chapter--annex' : ''}" data-file="${name}">\n${readFileSync(resolve(here, 'sections', name), 'utf8')}\n</section>`;
  })
  .join('\n\n');

const cover = `<div class="cover">
  <div class="cover__eyebrow">Transportes Esivans S.A.S.</div>
  <div class="cover__title">${TITLE}</div>
  <div class="cover__subtitle">${SUBTITLE}</div>
  <div class="cover__rule"></div>
  <div class="cover__meta">
    <p><strong>Versión del prototipo:</strong> ${today}</p>
    <p><strong>Pantallas que cubre:</strong> Simulador del conductor, Consola del técnico, Alertas del coordinador y Tablero del piloto</p>
    <p><strong>Para quién es:</strong> personal de operaciones y evaluadores, sin conocimientos técnicos</p>
  </div>
  <div class="cover__note">Este manual describe un prototipo de demostración. Los vehículos, las placas, las personas,
  las estaciones y las cifras que aparecen son datos ilustrativos; ninguno corresponde a la operación real.</div>
  <div class="cover__foot">${FOOTER}</div>
</div>`;

const source = `<!doctype html>
<html lang="es-CO">
<head>
<meta charset="utf-8">
<title>${TITLE} · ${SUBTITLE}</title>
<link rel="stylesheet" href="manual.css">
</head>
<body>
${cover}
<section class="front" id="contenido"></section>
${chapters}
<section class="back" id="indice-de-figuras"></section>
</body>
</html>
`;

// ---------- Transformacion del documento (corre dentro de Chromium) ----------

function decorate() {
  const LETTERS = 'ABCDEFGH';
  const problems = [];
  const slug = (text) =>
    text.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const used = new Set([...document.querySelectorAll('[id]')].map((el) => el.id));
  const unique = (base) => {
    let id = base;
    for (let i = 2; used.has(id); i += 1) id = base + '-' + i;
    used.add(id);
    return id;
  };

  const toc = [];
  const figures = [];
  const targets = new Map();
  let chapterNo = 0;
  let annexNo = 0;

  for (const section of document.querySelectorAll('section.chapter')) {
    const annex = section.classList.contains('chapter--annex');
    const h1 = section.querySelector('h1');
    if (!h1) { problems.push('Sin <h1>: ' + section.dataset.file); continue; }
    const number = annex ? LETTERS[annexNo++] : String(++chapterNo);
    const kind = annex ? 'Anexo' : 'Capítulo';
    if (!h1.id) h1.id = unique(slug(h1.textContent));
    h1.dataset.label = kind + ' ' + number;
    const title = h1.textContent.trim();
    targets.set(h1.id, { ref: (annex ? 'anexo ' : 'capítulo ') + number, title });
    const entry = { id: h1.id, label: (annex ? 'Anexo ' : '') + number, title, subs: [] };
    toc.push(entry);

    let sectionNo = 0;
    for (const h2 of section.querySelectorAll('h2:not(.no-num)')) {
      sectionNo += 1;
      if (!h2.id) h2.id = unique(h1.id + '-' + slug(h2.textContent));
      h2.dataset.num = number + '.' + sectionNo;
      const subTitle = h2.textContent.trim();
      targets.set(h2.id, { ref: 'sección ' + h2.dataset.num, title: subTitle });
      entry.subs.push({ id: h2.id, label: h2.dataset.num, title: subTitle });
    }
    for (const h3 of section.querySelectorAll('h3[id]')) {
      const owner = [...section.querySelectorAll('h2:not(.no-num)')].filter((h2) => h2.compareDocumentPosition(h3) & Node.DOCUMENT_POSITION_FOLLOWING).pop();
      targets.set(h3.id, { ref: owner ? 'sección ' + owner.dataset.num : 'capítulo ' + number, title: h3.textContent.trim() });
    }

    let figureNo = 0;
    for (const figure of section.querySelectorAll('figure.fig')) {
      figureNo += 1;
      const caption = figure.querySelector('figcaption');
      if (!caption) { problems.push('Figura sin pie en ' + section.dataset.file); continue; }
      const num = number + '.' + figureNo;
      figure.id = figure.id || unique('fig-' + num.replace('.', '-').toLowerCase());
      caption.dataset.num = num;
      figures.push({ id: figure.id, num, title: caption.textContent.trim(), chapter: (annex ? '' : 'Capítulo ') + entry.label + '. ' + title });
      targets.set(figure.id, { ref: 'figura ' + num, title: caption.textContent.trim() });
    }
  }

  // Las tablas cortas no se parten entre paginas (evita un encabezado con una sola fila al pie).
  for (const table of document.querySelectorAll('section.chapter table')) {
    if (table.querySelectorAll('tbody > tr').length <= 5 && !table.closest('li, td')) table.classList.add('keep');
  }

  // Referencias cruzadas: <a class="xref" href="#id"></a> -> "sección 5.3"; con data-title, añade el titulo.
  for (const link of document.querySelectorAll('a[href^="#"]')) {
    const target = targets.get(link.getAttribute('href').slice(1));
    if (!target) { problems.push('Enlace sin destino: ' + link.getAttribute('href')); continue; }
    if (link.classList.contains('xref') && !link.textContent.trim()) {
      link.textContent = link.hasAttribute('data-short')
        ? target.ref.replace(/^\S+ /, '')
        : target.ref + (link.hasAttribute('data-title') ? ', «' + target.title + '»' : '');
    }
  }

  // Tabla de contenido
  const esc = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const row = (item, cls) =>
    `<li class="${cls}"><a href="#${item.id}"><span class="toc__num">${item.label}</span>${esc(item.title)}</a>` +
    `<span class="toc__page" data-target="${item.id}"></span></li>`;
  const front = document.querySelector('section.front');
  front.innerHTML =
    '<h1 class="no-num" data-label="">Contenido</h1><ul class="toc">' +
    toc.map((ch) => row(ch, 'toc__ch') + ch.subs.map((s) => row(s, 'toc__sub')).join('')).join('') +
    row({ id: 'indice-de-figuras-titulo', label: '', title: 'Índice de figuras' }, 'toc__ch') +
    '</ul>';

  // Indice de figuras
  const back = document.querySelector('section.back');
  let html = '<h1 class="no-num" data-label="" id="indice-de-figuras-titulo">Índice de figuras</h1><div class="figindex">';
  let current = '';
  for (const fig of figures) {
    if (fig.chapter !== current) {
      current = fig.chapter;
      html += `<p class="figindex__ch">${esc(current)}</p>`;
    }
    const short = fig.title.length > 104 ? fig.title.slice(0, 101).replace(/\s+\S*$/, '').replace(/[,;:.]$/, '') + '…' : fig.title;
    html += `<p class="figindex__row"><a href="#${fig.id}"><span class="figindex__num">${fig.num}</span>${esc(short)}</a>` +
      `<span class="toc__page" data-target="${fig.id}"></span></p>`;
  }
  back.innerHTML = html + '</div>';

  const ids = [...document.querySelectorAll('[id]')].map((el) => el.id);
  for (const id of new Set(ids.filter((id, i) => ids.indexOf(id) !== i))) problems.push('id repetido: ' + id);
  return { problems, chapters: toc.map((c) => c.label + '. ' + c.title + ' (' + c.subs.length + ' secciones)'), figures: figures.length };
}

function setPages(pages) {
  let missing = 0;
  for (const span of document.querySelectorAll('.toc__page[data-target]')) {
    const page = pages[span.dataset.target];
    if (page) span.textContent = String(page);
    else { span.textContent = ''; missing += 1; }
  }
  return missing;
}

// Reduce cada captura al tamaño con el que se imprime (PRINT_DPI) y la deja como JPEG dentro del PDF.
async function shrinkImages({ dpi, quality }) {
  for (const img of document.images) {
    const cssWidth = img.getBoundingClientRect().width;
    if (!cssWidth || !img.naturalWidth) continue;
    const targetWidth = Math.min(img.naturalWidth, Math.ceil((cssWidth / 96) * dpi));
    const targetHeight = Math.max(1, Math.round(img.naturalHeight * (targetWidth / img.naturalWidth)));
    // Reduccion por mitades: evita el texto "mordido" cuando el salto es grande.
    let sourceEl = img;
    let w = img.naturalWidth;
    let h = img.naturalHeight;
    while (w / 2 > targetWidth) {
      const half = document.createElement('canvas');
      half.width = Math.round(w / 2);
      half.height = Math.round(h / 2);
      const hctx = half.getContext('2d');
      hctx.imageSmoothingQuality = 'high';
      hctx.drawImage(sourceEl, 0, 0, half.width, half.height);
      sourceEl = half;
      w = half.width;
      h = half.height;
    }
    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, targetWidth, targetHeight);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(sourceEl, 0, 0, targetWidth, targetHeight);
    img.style.width = cssWidth + 'px';
    img.src = canvas.toDataURL('image/jpeg', quality);
    await img.decode();
  }
}

// Encoge las figuras que saltaron de pagina por poco y dejaron un hueco al final de la pagina anterior.
// Recibe la medicion de page-gaps.py y devuelve dos cosas:
//   heights: {id: altoMaximoEnMm}  figuras que caben en el hueco si se encogen un poco;
//   moves:   {id: n}               figuras que no caben ni encogidas: se bajan n bloques de texto, para
//                                  que ese texto llene el hueco (nunca cruzan un titulo ni otra figura).
function fitFigures({ pages, tops, floor, moved }) {
  const MM = 96 / 25.4;
  const free = Object.fromEntries(pages.map((p) => [p.page, p.free_mm]));
  const result = {};
  const moves = {};
  const height = (el) => el.getBoundingClientRect().height / MM;
  const tryMove = (figure, block, space) => {
    if (moved.includes(figure.id) || block.parentElement.closest('.two-col, li, td, .keep')) return;
    if (block !== figure && block.querySelector('figure.fig') !== figure) return; // un bloque se mueve una sola vez
    let filled = 0;
    let count = 0;
    for (let node = block.nextElementSibling; node && count < 6; node = node.nextElementSibling) {
      if (node.matches('h1, h2, h3, h4, figure, .two-col, .page-break, section, style')) break;
      filled += height(node) + 3;
      count += 1;
      if (filled >= space - 14) break;
    }
    if (count && filled >= Math.min(space - 14, space * 0.55)) moves[figure.id] = count;
  };
  for (const figure of document.querySelectorAll('figure.fig')) {
    const top = tops[figure.id];
    const img = figure.querySelector('img');
    if (!top || !img || top.page < 3) continue;
    const lead = Math.max(0, top.y_mm); // lo que hay encima de la figura en su pagina (un titulo, una frase)
    const space = free[top.page - 1] ?? 0;
    if (lead > 30 || space < 32) continue;
    const block = figure.closest('.two-col') ?? figure; // bloque que no se parte
    const blockHeight = block.getBoundingClientRect().height / MM;
    const imgHeight = img.getBoundingClientRect().height / MM;
    const need = lead + blockHeight + 7 - space;
    if (need <= 0) continue;
    if (block !== figure) {
      const others = [...block.children].filter((child) => !child.matches('figure.fig')).map((child) => child.getBoundingClientRect().height / MM);
      if (Math.max(0, ...others) + lead + 7 > space) { // la otra columna tampoco cabe
        if (space >= 45) tryMove(figure, block, space);
        continue;
      }
    }
    const target = imgHeight - need;
    // Las capturas de ventana completa son vistas generales: admiten encogerse un poco mas.
    const limit = img.naturalWidth >= 2800 && img.naturalHeight <= 1900 ? floor - 0.1 : floor;
    if (target < imgHeight * limit || target < 28) {
      if (space >= 45) tryMove(figure, block, space);
      continue;
    }
    result[figure.id] = Number(target.toFixed(1));
  }
  return { heights: result, moves };
}

function applyFits({ heights, moves }) {
  for (const [id, count] of Object.entries(moves)) {
    const figure = document.getElementById(id);
    const block = figure.closest('.two-col') ?? figure;
    let anchor = block;
    for (let i = 0; i < count && anchor.nextElementSibling; i += 1) anchor = anchor.nextElementSibling;
    if (anchor !== block) anchor.after(block);
  }
  for (const [id, mm] of Object.entries(heights)) {
    const img = document.getElementById(id)?.querySelector('img');
    if (img) img.style.maxHeight = mm + 'mm';
  }
}

// ---------- Ejecucion ----------

const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.svg': 'image/svg+xml' };
const ORIGIN = 'http://manual.local';
const FIT_PASSES = Number(process.env.FIT_PASSES ?? 8);
const FIT_FLOOR = Number(process.env.FIT_FLOOR ?? 0.7); // una figura nunca baja de este porcentaje de su alto

const browser = await chromium.launch();
// 665 px = 176 mm: el ancho util de la pagina A4 con los margenes de manual.css. Asi lo que se mide
// con la hoja de impresion emulada coincide con lo que sale en el PDF.
const context = await browser.newContext({ viewport: { width: 665, height: 1000 } });
const page = await context.newPage();
const missing = [];
let currentHtml = source;
// Todo se sirve desde el disco bajo un origen ficticio: asi el lienzo puede reescalar las imagenes.
await page.route(ORIGIN + '/**', (route) => {
  const path = decodeURIComponent(new URL(route.request().url()).pathname).replace(/^\//, '');
  if (path === 'manual.html') return route.fulfill({ contentType: MIME['.html'], body: currentHtml });
  const file = resolve(here, path);
  if (!file.startsWith(here) || !existsSync(file)) {
    missing.push(path);
    return route.fulfill({ status: 404, body: '' });
  }
  return route.fulfill({ contentType: MIME[extname(file)] ?? 'application/octet-stream', body: readFileSync(file) });
});

async function load(html) {
  currentHtml = html;
  await page.emulateMedia({ media: 'print' });
  await page.goto(ORIGIN + '/manual.html', { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
}

async function print(path) {
  await page.emulateMedia({ media: 'print' });
  await page.evaluate(shrinkImages, { dpi: PRINT_DPI, quality: JPEG_QUALITY });
  await page.pdf({ path, preferCSSPageSize: true, printBackground: true, outline: true, tagged: true });
}

function python(script, pdf) {
  const run = spawnSync('uv', ['run', '--quiet', '--with', 'pymupdf', 'python', resolve(here, script), pdf], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  try { return JSON.parse(run.stdout); } catch (error) { console.error(script + ': ' + (run.error?.message ?? run.stderr ?? error.message)); return null; }
}

await load(source);
const info = await page.evaluate(decorate);
const broken = await page.evaluate(() =>
  [...document.images].filter((img) => !img.complete || img.naturalWidth === 0).map((img) => img.getAttribute('src')),
);
const serialize = () => page.evaluate(() => '<!doctype html>\n' + document.documentElement.outerHTML + '\n');
const decorated = await serialize();

const outDir = process.env.OUT ? resolve(process.env.OUT) : here;
mkdirSync(outDir, { recursive: true });
const pdfPath = resolve(outDir, PDF_NAME);
const draftPath = resolve(outDir, PDF_NAME.replace('.pdf', '.borrador.pdf'));

let finalHtml = decorated;
let pagesNote = 'tabla de contenido sin numeros de pagina';
const fits = { heights: {}, moves: {} };
if (only) {
  await print(pdfPath);
} else {
  // Borradores: se imprime, se mide el hueco al final de cada pagina y se encogen las figuras que
  // saltaron por poco. Se repite hasta que no haya nada que encoger.
  let usable = true;
  for (let pass = 0; pass <= FIT_PASSES; pass += 1) {
    await load(decorated);
    await page.evaluate(applyFits, fits);
    await print(draftPath);
    if (pass === FIT_PASSES) break;
    const gaps = python('page-gaps.py', draftPath);
    if (!gaps) { usable = false; break; }
    const more = await page.evaluate(fitFigures, { ...gaps, floor: FIT_FLOOR, moved: Object.keys(fits.moves) });
    if (!Object.keys(more.heights).length && !Object.keys(more.moves).length) break;
    Object.assign(fits.heights, more.heights);
    Object.assign(fits.moves, more.moves);
  }
  const first = usable ? python('toc-pages.py', draftPath) : null;
  await load(decorated);
  await page.evaluate(applyFits, fits);
  if (first && Object.keys(first.targets).length) {
    const notFound = await page.evaluate(setPages, first.targets);
    finalHtml = await serialize();
    await print(pdfPath);
    // Comprobacion: con los numeros puestos, cada destino debe seguir en la misma pagina.
    const second = python('toc-pages.py', pdfPath);
    const moved = Object.keys(first.targets).filter((id) => first.targets[id] !== second?.targets[id]);
    if (!second || moved.length || notFound) {
      console.error('Numeros de pagina no fiables (' + moved.length + ' destinos cambiaron, ' + notFound + ' sin pagina): se quitan.');
      await load(decorated);
      await page.evaluate(applyFits, fits);
      finalHtml = await serialize();
      await print(pdfPath);
    } else {
      pagesNote = second.pages + ' paginas; ' + Object.keys(second.targets).length + ' destinos con numero de pagina comprobado; ' + Object.keys(fits.heights).length + ' figuras ajustadas de alto y ' + Object.keys(fits.moves).length + ' bajadas tras el texto que las sigue';
    }
  } else {
    console.error('No se pudo leer el PDF con uv + pymupdf: la tabla de contenido queda sin numeros de pagina.');
    finalHtml = await serialize();
    await print(pdfPath);
  }
  rmSync(draftPath, { force: true });
}
writeFileSync(resolve(here, 'manual.html'), finalHtml, 'utf8');
await browser.close();

console.log(files.length + ' fragmentos, ' + info.figures + ' figuras -> ' + pdfPath);
console.log(pagesNote);
for (const chapter of info.chapters) console.log('  ' + chapter);
const all = [...new Set([...broken, ...missing])];
if (info.problems.length || all.length) {
  for (const problem of info.problems) console.error('PROBLEMA: ' + problem);
  for (const item of all) console.error('No cargo: ' + item);
  process.exit(1);
}
