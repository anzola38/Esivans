// Capturas del manual de usuario (1440x900, deviceScaleFactor 2) contra la demo en marcha.
//
//   node docs/manual/capture.mjs                -> regenera docs/manual/img/*.png
//   ONLY="Reglas,Tablero" node docs/manual/capture.mjs   -> solo los bloques cuyo titulo contiene esos textos
//                                  (ojo: cada bloque parte del estado que dejan los anteriores)
//   TEXT_DIR=<carpeta> node docs/manual/capture.mjs   -> ademas guarda el texto visible de cada captura
//
// Usa siempre la IA simulada (nunca llama a un servicio externo) y empieza y termina con
// "Reiniciar demo" (POST /api/dev/reset). No modifica nada del producto.
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE_URL } from '../../e2e/scripts/env.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, '../../e2e/package.json'));
const { chromium, expect } = require('@playwright/test');

const outDir = resolve(here, 'img');
const textDir = process.env.TEXT_DIR ? resolve(process.env.TEXT_DIR) : null;
mkdirSync(outDir, { recursive: true });
if (textDir) mkdirSync(textDir, { recursive: true });

const W = 1440;
const H = 900;
const problems = [];
const done = [];

async function api(path, { method = 'GET', body, role = 'technician' } = {}) {
  const response = await fetch(BASE_URL + '/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Demo-Role': role, 'X-Demo-User': 'Manual' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* not JSON */
  }
  if (!response.ok) throw new Error(method + ' ' + path + ' respondio ' + response.status);
  return json;
}

async function reset() {
  await api('/dev/ai', { method: 'PUT', body: { provider: 'mock', pinned: true } });
  await api('/dev/reset', { method: 'POST' });
}

const WA = { GREEN: '573005550901', VEH015: '573005550015', VEH199: '573005550199' };

/** Runs the script of a demo case through the simulator API and returns the request it created. */
async function seedCase(code) {
  const cases = (await api('/dev/simulator/cases')).items;
  for (const step of cases.find((c) => c.code === code).script) {
    const before = ((await api('/dev/simulator/conversations/' + WA[code]))?.messages ?? []).length;
    await api('/dev/simulator/messages', { method: 'POST', body: { case_code: code, ...step } });
    for (let i = 0; i < 80; i += 1) {
      const current = await api('/dev/simulator/conversations/' + WA[code]);
      const last = current.messages.at(-1);
      if (current.messages.length > before + 1 && !current.assistant_typing && last?.direction === 'outbound') break;
      await new Promise((r) => setTimeout(r, 150));
    }
  }
  return (await api('/dev/simulator/conversations/' + WA[code])).request;
}

await reset();
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 2,
  locale: 'es-CO',
  timezoneId: 'America/Bogota',
});
const page = await context.newPage();
page.on('pageerror', (error) => problems.push('error de JavaScript: ' + error.message));

// ---------- helpers ----------

async function settle() {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(450);
}

async function closeToasts() {
  for (const close of await page.locator('.ui-toast button').all()) await close.click().catch(() => {});
  await page.locator('.ui-toast').first().waitFor({ state: 'detached', timeout: 1500 }).catch(() => {});
}

function saveText(name, text) {
  if (textDir) writeFileSync(resolve(textDir, name + '.txt'), (text ?? '').replace(/ | /g, ' '), 'utf8');
}

/** Whole window. */
async function shot(name, { keepToasts = false } = {}) {
  try {
    if (!keepToasts) await closeToasts();
    await settle();
    await page.screenshot({ path: resolve(outDir, name + '.png'), animations: 'disabled' });
    saveText(
      name,
      await page.evaluate(() => {
        const dialog = document.querySelector('.ui-modal__dialog');
        return (dialog ? '[DIALOGO]\n' + dialog.innerText + '\n[FONDO]\n' : '') + document.body.innerText;
      }),
    );
    done.push(name);
    console.log('  ' + name);
  } catch (error) {
    problems.push(name + ': ' + error.message.split('\n')[0]);
  }
}

/** Crop around one or several elements (their union), with a small margin. */
async function crop(name, targets, { pad = 10, keepToasts = false } = {}) {
  try {
    if (!keepToasts) await closeToasts();
    const list = (Array.isArray(targets) ? targets : [targets]).map((t) => (typeof t === 'string' ? page.locator(t).first() : t));
    await list[0].scrollIntoViewIfNeeded();
    await settle();
    const boxes = [];
    const texts = [];
    for (const item of list) {
      const box = await item.boundingBox();
      if (!box) throw new Error('elemento no visible');
      boxes.push(box);
      texts.push(await item.innerText().catch(() => ''));
    }
    const size = page.viewportSize();
    const x0 = Math.max(0, Math.min(...boxes.map((b) => b.x)) - pad);
    const y0 = Math.max(0, Math.min(...boxes.map((b) => b.y)) - pad);
    const x1 = Math.min(size.width, Math.max(...boxes.map((b) => b.x + b.width)) + pad);
    const y1 = Math.min(size.height, Math.max(...boxes.map((b) => b.y + b.height)) + pad);
    if (x1 - x0 < 20 || y1 - y0 < 10) throw new Error('recorte vacio');
    await page.screenshot({
      path: resolve(outDir, name + '.png'),
      clip: { x: x0, y: y0, width: x1 - x0, height: y1 - y0 },
      animations: 'disabled',
    });
    saveText(name, texts.join('\n'));
    done.push(name);
    console.log('  ' + name);
  } catch (error) {
    problems.push(name + ': ' + error.message.split('\n')[0]);
  }
}

/** Runs `fn` with a taller window so the cards that scroll inside show all their content. */
async function tall(height, fn) {
  await page.setViewportSize({ width: W, height });
  await page.waitForTimeout(400);
  try {
    await fn();
  } finally {
    await page.setViewportSize({ width: W, height: H });
    await page.waitForTimeout(300);
  }
}

/** Whole routed content of a page that scrolls inside <main>. */
async function fullShot(name) {
  const extra = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra + 8, () => shot(name));
}

async function scrollContent(position) {
  await page.evaluate((to) => {
    const main = document.querySelector('main.content');
    main.scrollTo({ top: to === 'bottom' ? main.scrollHeight : 0 });
  }, position);
  await page.waitForTimeout(200);
}

async function go(path) {
  await page.goto(BASE_URL + path, { waitUntil: 'networkidle' });
  await settle();
}

async function role(value) {
  await page.getByTestId('role-select').selectOption(value);
  await page.waitForTimeout(300);
}

/** One block of the tour: a failure is reported and the next block still runs. */
const only = (process.env.ONLY ?? '').split(',').map((t) => t.trim()).filter(Boolean);
async function block(title, fn) {
  if (only.length && !only.some((t) => title.includes(t))) return;
  console.log('\n== ' + title + ' ==');
  try {
    await fn();
  } catch (error) {
    problems.push('[' + title + '] ' + error.message.split('\n')[0]);
    await page.setViewportSize({ width: W, height: H }).catch(() => {});
  }
}

const tid = (id) => page.getByTestId(id);
const chat = page.locator('.ui-phone__body');
const phone = page.locator('.sim__phone');
const dialog = page.locator('.ui-modal__dialog');

async function waitForReply(count) {
  await expect(chat.locator('.ui-bubble--out')).toHaveCount(count, { timeout: 20000 });
  await expect(tid('typing')).toHaveCount(0, { timeout: 20000 });
  await expect(chat.locator('.ui-bubble').last()).not.toHaveClass(/ui-bubble--out/, { timeout: 20000 });
}

async function scriptStep() {
  const before = await chat.locator('.ui-bubble--out').count();
  await tid('script-next').click();
  await waitForReply(before + 1);
}

async function quickReply(text) {
  const before = await chat.locator('.ui-bubble--out').count();
  await tid('quick-replies').getByRole('button', { name: text }).click();
  await waitForReply(before + 1);
}

async function selectCase(code) {
  await tid('case-' + code).click();
  await expect(tid('case-' + code)).toHaveAttribute('aria-selected', 'true');
  await settle();
}

// =====================================================================================
// 0. Estado recien reiniciado
// =====================================================================================

await block('General', async () => {
  await go('/simulador');
  await expect(tid('case-driver')).toHaveText('Carlos Andrés Pérez');
  await shot('general-01-pantalla-completa');
  await crop('general-02-menu-recorrido', '.sidebar', { pad: 0 });
  await crop('general-03-cabecera', '.topbar', { pad: 0 });
  await crop('general-04-rol-tecnico', '.topbar__actions');
  for (const [value, name] of [['coordinator', 'coordinador'], ['finance', 'finanzas'], ['support', 'soporte']]) {
    await role(value);
    await crop('general-04-rol-' + name, '.topbar__actions');
  }
  await role('technician');
  await crop('general-07-pie', tid('footer'), { pad: 0 });
  await tid('reset-demo').click();
  await expect(dialog).toBeVisible();
  await shot('general-05-reiniciar-dialogo');
  await crop('general-06-reiniciar-dialogo-recorte', dialog, { pad: 16 });
  await dialog.getByRole('button', { name: 'Cancelar' }).click();
  await expect(dialog).toHaveCount(0);
});

await block('Simulador: vista inicial', async () => {
  await go('/simulador');
  await shot('simulador-01-inicio');
  await crop('simulador-02-selector-casos', '.sim__cases');
  await crop('simulador-03-ficha-caso', [page.locator('.sim__cases'), page.locator('.sim__clock-help')]);
  await crop('simulador-04-ia-opciones', [page.locator('.sim__kv-row').filter({ has: tid('ai-switch') }), tid('ai-note')]);
  await crop('simulador-05-guion-sugerido', [page.locator('.sim__script-title'), tid('script-next'), page.locator('.sim__next-hint')]);
  await crop('simulador-06-telefono-vacio', phone);
  await crop('simulador-07-estado-sin-solicitud', tid('status-card'), { pad: 4 });
});

await block('Consola y tablero recien reiniciados', async () => {
  await go('/consola');
  await expect(page.getByText('No hay solicitudes en la cola')).toBeVisible();
  await shot('consola-01-cola-vacia');
  await go('/tablero');
  await expect(tid('indicators').locator('.kpi')).toHaveCount(9);
  await shot('tablero-01-recien-reiniciado');
  await fullShot('tablero-02-recien-reiniciado-completo');
});

await block('Alertas recien reiniciadas (Coordinador)', async () => {
  await go('/alertas');
  await role('coordinator');
  await tid('tab-refuels').click();
  await expect(tid('alert-detail')).toBeVisible();
  await shot('alertas-01-tanqueos-lista-y-detalle');
  await crop('alertas-02-pestanas-y-resumen', '.tabs', { pad: 6 });
  await crop('alertas-03-filtros', '.list__bar', { pad: 6 });
  await crop('alertas-04-lista-tanqueos', '.split__list', { pad: 4 });
  await crop('alertas-05-fila-de-la-lista', tid('alert-list').locator('.item').first(), { pad: 6 });
  await tall(2300, async () => {
    await crop('alertas-06-tanqueo-detalle-completo', tid('alert-detail'), { pad: 6 });
    await crop('alertas-07-tanqueo-razones-y-evidencia', [page.locator('.detail__head'), page.locator('.tx-grid').last()], { pad: 8 });
    await crop('alertas-08-formulario-resultado', tid('review'), { pad: 8 });
  });

  await tid('tab-vehicles').click();
  await expect(tid('alert-vehicle')).toHaveText('VEH129');
  await shot('alertas-10-vehiculos-veh129');
  await tall(2300, async () => {
    await crop('alertas-11-veh129-detalle-completo', tid('alert-detail'), { pad: 6 });
    await crop('alertas-12-veh129-razones', [page.locator('.detail__head'), tid('alert-reasons')], { pad: 8 });
    await crop('alertas-13-veh129-evidencia', '.veh-evidence', { pad: 8 });
  });
  const vehicles = tid('alert-list');
  await vehicles.locator('[data-vehicle=VEH215]').click();
  await expect(tid('alert-vehicle')).toHaveText('VEH215');
  await shot('alertas-14-vehiculos-veh215');
  await tall(2300, () => crop('alertas-15-veh215-detalle-completo', tid('alert-detail'), { pad: 6 }));
  await vehicles.locator('[data-vehicle=VEH160]').click();
  await expect(tid('alert-vehicle')).toHaveText('VEH160');
  await expect(tid('ledger-comparison')).toBeVisible();
  await shot('alertas-16-vehiculos-veh160');
  await tall(2300, async () => {
    await crop('alertas-17-veh160-detalle-completo', tid('alert-detail'), { pad: 6 });
    await crop('alertas-18-veh160-libro-unico', tid('ledger'), { pad: 8 });
    await crop('alertas-19-veh160-comparacion', tid('ledger-comparison'), { pad: 8 });
    await tid('ledger-provider-gopass').click();
    await page.waitForTimeout(300);
    await crop('alertas-20-veh160-libro-unico-gopass', tid('ledger'), { pad: 8 });
  });

  await tid('tab-reconciliation').click();
  await expect(tid('import-sample')).toBeEnabled();
  await shot('conciliacion-01-antes-de-cargar');
  await crop('conciliacion-02-para-que-sirve', tid('reconciliation-purpose'), { pad: 6 });
  await crop('conciliacion-03-boton-cargar', '.upload', { pad: 8 });

  await role('technician');
});

await block('Reglas recien reiniciadas (Coordinador)', async () => {
  await go('/alertas');
  await role('coordinator');
  await tid('tab-rules').click();
  await expect(tid('rules-table').locator('tbody tr.is-clickable')).toHaveCount(25);
  await shot('reglas-01-catalogo');
  await tall(2100, async () => {
    await crop('reglas-02-catalogo-completo', page.locator('app-card').filter({ has: tid('rules-table') }), { pad: 4 });
  });
  await tid('rule-row-R08').click();
  await expect(tid('rule-detail')).toContainText('R08');
  await shot('reglas-03-detalle-r08');
  await tall(1500, () => crop('reglas-04-detalle-r08-recorte', tid('rule-detail'), { pad: 6 }));
  await role('technician');
});

// =====================================================================================
// 1. Simulador: los tres casos hasta "En revision"
// =====================================================================================

await block('Simulador: caso verde', async () => {
  await go('/simulador');
  await selectCase('GREEN');
  await scriptStep();
  await shot('simulador-10-verde-saludo-y-servicio');
  await crop('simulador-11-verde-telefono-saludo', phone);
  await crop('simulador-12-respuestas-rapidas', [tid('quick-replies'), page.locator('.sim__composer')], { pad: 8 });
  await crop('simulador-13-guion-en-curso', [page.locator('.sim__script-title'), tid('script-next'), page.locator('.sim__next-hint')]);
  await scriptStep();
  await crop('simulador-14-verde-telefono-pide-foto', phone);
  await crop('simulador-15-estado-lo-que-falta', tid('status-card'), { pad: 4 });
  await scriptStep();
  await expect(chat.locator('img.sim__photo')).toHaveCount(1);
  await page.waitForFunction(() => {
    const img = document.querySelector('img.sim__photo');
    return img && img.complete && img.naturalWidth > 0;
  });
  await shot('simulador-16-verde-foto-y-lectura');
  await crop('simulador-17-verde-telefono-foto-y-lectura', phone);
  await scriptStep();
  await expect(tid('request-stage')).toHaveText('En revisión');
  await shot('simulador-18-verde-en-revision');
  await crop('simulador-19-estado-en-revision', tid('status-card'), { pad: 4 });
  await crop('simulador-20-linea-de-estados', tid('timeline'), { pad: 10 });
  await crop('simulador-21-verde-telefono-en-revision', phone);
});

await block('Simulador: VEH015', async () => {
  await selectCase('VEH015');
  await expect(tid('case-plate')).toHaveText('ZZA015');
  await shot('simulador-30-veh015-inicio');
  await scriptStep();
  await scriptStep();
  await scriptStep();
  await expect(chat).toContainText('34.086 km');
  await shot('simulador-31-veh015-propone-34086');
  await crop('simulador-32-veh015-telefono-propuesta', phone);
  await crop('simulador-33-veh015-respuestas-rapidas', [tid('quick-replies'), page.locator('.sim__composer')], { pad: 8 });
  await quickReply('Sí, es 34.086');
  await expect(tid('request-stage')).toHaveText('En revisión');
  await shot('simulador-34-veh015-en-revision');
  await crop('simulador-35-veh015-telefono-confirmado', phone);
});

await block('Simulador: VEH199 a las 23:14', async () => {
  await selectCase('VEH199');
  await expect(tid('case-clock')).toHaveValue('23:14');
  await shot('simulador-40-veh199-inicio-2314');
  await crop('simulador-41-veh199-ficha-hora-simulada', [page.locator('.sim__cases'), page.locator('.sim__clock-help')]);
  await scriptStep();
  await scriptStep();
  await crop('simulador-42-veh199-telefono-sin-servicio', phone);
  await scriptStep();
  await scriptStep();
  await expect(tid('request-stage')).toHaveText('En revisión');
  await shot('simulador-43-veh199-en-revision');
  await crop('simulador-44-veh199-telefono', phone);
  await crop('simulador-45-veh199-estado', tid('status-card'), { pad: 4 });
});

// =====================================================================================
// 2. Consola del tecnico
// =====================================================================================

await block('Consola: cola con los tres semaforos', async () => {
  await go('/consola');
  await expect(tid('queue-table').locator('tbody tr')).toHaveCount(3);
  await shot('consola-02-cola-tres-semaforos');
  await crop('consola-03-contadores', tid('queue-counts'), { pad: 8 });
  await crop('consola-04-fila-verde-con-sla', page.locator('[data-plate=ZZA901]'), { pad: 4 });
  await crop('consola-05-tabla-de-la-cola', tid('queue-table'), { pad: 4 });
  await crop('consola-06-encabezado-de-la-cola', 'app-section-header', { pad: 6 });
  await crop('consola-07-pie-de-la-cola', '.queue__footer', { pad: 6 });
});

await block('Consola: detalle verde', async () => {
  await page.locator('[data-plate=ZZA901]').click();
  await expect(tid('detail-plate')).toHaveText('ZZA901');
  await expect(tid('approve')).toHaveText(/Aprobar en un clic/);
  await shot('consola-10-detalle-verde-arriba');
  await scrollContent('bottom');
  await shot('consola-11-detalle-verde-abajo');
  await scrollContent('top');
  await fullShot('consola-12-detalle-verde-completo');
  const extra = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra + 8, async () => {
    await crop('consola-13-panel-de-decision', '.det__panel', { pad: 8 });
    await crop('consola-14-razones-verde-sin-alertas', tid('reasons-card'), { pad: 6 });
    await crop('consola-15-foto-y-lectura', tid('evidence-card'), { pad: 6 });
    await crop('consola-16-libro-unico', tid('ledger-card'), { pad: 6 });
    await crop('consola-17-calculo-valor-sugerido', tid('calc-card'), { pad: 6 });
    await crop('consola-18-bitacora-antes-de-decidir', tid('audit-card'), { pad: 6 });
  });
  await page.locator('.det__photo').click();
  await expect(dialog).toBeVisible();
  await shot('consola-19-foto-ampliada');
  await dialog.getByRole('button', { name: 'Cerrar' }).click();
  await expect(dialog).toHaveCount(0);

  await tid('approve').click();
  await expect(tid('enablement')).toContainText('Habilitar en el portal del proveedor');
  await shot('consola-20-habilitacion');
  await crop('consola-21-panel-de-habilitacion', '.det__panel', { pad: 8 });
  await crop('consola-22-valores-para-copiar', '.det__enable-grid', { pad: 8 });
  await crop('consola-23-referencia-del-portal', '.det__field--ref', { pad: 8 });
  await tid('copy-plate').click();
  await expect(page.locator('.ui-toast')).toContainText('Placa en el portapapeles');
  await crop('consola-24-aviso-placa-copiada', page.locator('.ui-toast').first(), { pad: 8, keepToasts: true });
  await closeToasts();
  await tid('confirm-enablement').click();
  await expect(tid('detail-stage')).toHaveText('Autorizada');
  await page.locator('.ui-toast').first().waitFor().catch(() => {});
  await crop('consola-25-aviso-autorizada', page.locator('.ui-toast').first(), { pad: 8, keepToasts: true });
  await shot('consola-26-autorizada');
  await crop('consola-27-panel-autorizada', '.det__panel', { pad: 8 });
  await fullShot('consola-28-autorizada-completo');
  const extra2 = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra2 + 8, () => crop('consola-29-bitacora-completa', tid('audit-card'), { pad: 6 }));

  await tid('to-simulator').click();
  await expect(tid('case-plate')).toHaveText('ZZA901');
  await expect(tid('authorization-summary')).toBeVisible();
  await shot('simulador-22-verde-autorizada');
  await crop('simulador-23-mensaje-de-autorizacion', phone);
  await crop('simulador-24-estado-autorizada-ver-en-consola', tid('status-card'), { pad: 4 });
  await crop('simulador-25-burbuja-de-autorizacion', chat.locator('.ui-bubble:not(.ui-bubble--out)').last(), { pad: 10 });
});

await block('Consola: detalle amarillo VEH015', async () => {
  await go('/consola');
  await page.locator('[data-plate=ZZA015]').click();
  await expect(tid('detail-plate')).toHaveText('ZZA015');
  await expect(tid('approve')).toHaveText(/Aprobar con motivo/);
  await shot('consola-30-detalle-amarillo-veh015');
  await fullShot('consola-31-detalle-amarillo-veh015-completo');
  await crop('consola-32-amarillo-panel-de-decision', '.det__panel', { pad: 8 });
  await crop('consola-33-amarillo-razones-r02', tid('reasons-card'), { pad: 6 });
  await crop('consola-34-amarillo-foto-y-correccion', tid('evidence-card'), { pad: 6 });
  await tid('approve').click();
  await expect(dialog).toBeVisible();
  await crop('consola-35-aprobar-con-motivo-dialogo', dialog, { pad: 16 });
  await tid('decision-confirm').click();
  await expect(tid('reason-error')).toBeVisible();
  await shot('consola-36-aprobar-con-motivo-obligatorio');
  await crop('consola-37-motivo-obligatorio-recorte', dialog, { pad: 16 });
  await page.locator('.det__suggestion').first().click();
  await crop('consola-38-aprobar-con-motivo-lleno', dialog, { pad: 16 });
  await tid('decision-confirm').click();
  await expect(tid('enablement')).toContainText('$50.000');
  await shot('consola-39-amarillo-habilitacion');
  await tid('confirm-enablement').click();
  await expect(tid('detail-stage')).toHaveText('Autorizada');
  await shot('consola-40-amarillo-autorizada');
  await crop('consola-41-amarillo-panel-autorizada', '.det__panel', { pad: 8 });
});

await block('Consola: detalle rojo VEH199', async () => {
  await go('/consola');
  await page.locator('[data-plate=ZZA199]').click();
  await expect(tid('detail-plate')).toHaveText('ZZA199');
  await expect(tid('detail-light')).toContainText('Rojo');
  await shot('consola-50-detalle-rojo-veh199');
  await fullShot('consola-51-detalle-rojo-veh199-completo');
  await crop('consola-52-rojo-panel-de-decision', '.det__panel', { pad: 8 });
  await crop('consola-53-rojo-razones', tid('reasons-card'), { pad: 6 });
  await crop('consola-54-rojo-nota-coordinador', tid('red-review-note'), { pad: 8 });
  await crop('consola-55-rojo-nota-y-razones', '.det__lead', { pad: 6 });
  const extra = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra + 8, async () => {
    await crop('consola-56-rojo-libro-unico', tid('ledger-card'), { pad: 6 });
    await crop('consola-57-rojo-calculo', tid('calc-card'), { pad: 6 });
    await crop('consola-58-rojo-foto-y-lectura', tid('evidence-card'), { pad: 6 });
  });

  await role('support');
  await expect(tid('read-only')).toBeVisible();
  await shot('consola-60-solo-lectura-soporte');
  await crop('consola-61-solo-lectura-aviso', tid('read-only'), { pad: 8 });
  await crop('consola-62-solo-lectura-botones', '.det__panel', { pad: 8 });
  await role('technician');
  await expect(tid('adjust')).toBeEnabled();

  await tid('adjust').click();
  await expect(dialog).toBeVisible();
  await crop('consola-63-ajustar-dialogo', dialog, { pad: 16 });
  await tid('amount-input').fill('500000');
  await tid('decision-confirm').click();
  await expect(tid('reason-error')).toBeVisible();
  await crop('consola-64-ajustar-validacion', dialog, { pad: 16 });
  await tid('amount-input').fill('20000');
  await page.locator('.det__suggestion').first().click();
  await shot('consola-65-ajustar-valor-y-motivo');
  await crop('consola-66-ajustar-valor-y-motivo-recorte', dialog, { pad: 16 });
  await tid('decision-confirm').click();
  await expect(tid('enablement')).toContainText('$20.000');
  await shot('consola-67-rojo-habilitacion-valor-ajustado');
  await crop('consola-68-rojo-panel-habilitacion-ajustada', '.det__panel', { pad: 8 });
  await tid('confirm-enablement').click();
  await expect(tid('detail-stage')).toHaveText('Autorizada');
  await shot('consola-69-rojo-autorizada');
  await crop('consola-70-rojo-autorizada-nota-coordinador', [page.locator('.det__panel'), tid('red-review-note')], { pad: 8 });
  const extra2 = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra2 + 8, () => crop('consola-71-rojo-bitacora-con-ajuste', tid('audit-card'), { pad: 6 }));
});

// =====================================================================================
// 3. Casos de borde del simulador
// =====================================================================================

await block('Simulador: VEH902 no necesita tanquear', async () => {
  await go('/simulador');
  await selectCase('NO_FUEL');
  await expect(tid('case-plate')).toHaveText('ZZA902');
  await shot('simulador-50-veh902-inicio');
  for (let i = 0; i < 4; i += 1) await scriptStep();
  await shot('simulador-51-veh902-no-necesita-tanquear');
  await crop('simulador-52-veh902-telefono-dos-respuestas', phone);
  await crop('simulador-53-veh902-respuestas-rapidas', [tid('quick-replies'), page.locator('.sim__composer')], { pad: 8 });
  await scriptStep();
  await expect(tid('request-stage')).toHaveText('Cerrada sin tanqueo');
  await shot('simulador-54-veh902-cerrada-sin-tanqueo');
  await crop('simulador-55-veh902-telefono-cierre', phone);
  await crop('simulador-56-veh902-estado-cerrada', tid('status-card'), { pad: 4 });
});

await block('Simulador: numero sin registro', async () => {
  await selectCase('UNREGISTERED');
  await expect(tid('case-driver')).toHaveText('Número no registrado');
  await shot('simulador-60-sin-registro-inicio');
  await scriptStep();
  await expect(tid('request-stage')).toHaveText('En revisión');
  await shot('simulador-61-sin-registro-pasa-al-tecnico');
  await crop('simulador-62-sin-registro-telefono', phone);
  await crop('simulador-63-sin-registro-estado', tid('status-card'), { pad: 4 });
  await tid('open-console').click();
  await expect(tid('detail-plate')).toHaveText('Sin placa');
  await shot('consola-80-detalle-sin-registro');
  await fullShot('consola-81-detalle-sin-registro-completo');
  await go('/consola');
  await expect(tid('queue-table').locator('tbody tr').first()).toBeVisible();
  await shot('consola-82-cola-despues-de-usar');
  await crop('consola-83-cola-filas-decididas-y-cerradas', tid('queue-table'), { pad: 4 });
  await crop('consola-84-contadores-despues-de-usar', tid('queue-counts'), { pad: 8 });
});

// =====================================================================================
// 4. Alertas del coordinador despues de usar la demo
// =====================================================================================

await block('Alertas: C03 del VEH199', async () => {
  await go('/alertas');
  await role('coordinator');
  await tid('tab-refuels').click();
  const row = tid('alert-list').locator('[data-vehicle=VEH199][data-rules~="C03"]').first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(tid('alert-vehicle')).toHaveText('VEH199');
  await expect(tid('alert-request')).toBeVisible();
  await shot('alertas-30-c03-veh199');
  await crop('alertas-31-c03-fila', row, { pad: 6 });
  await tall(2300, async () => {
    await crop('alertas-32-c03-detalle-completo', tid('alert-detail'), { pad: 6 });
    await crop('alertas-33-c03-autorizacion-en-rojo', [page.locator('.detail__head'), tid('alert-request')], { pad: 8 });
  });
});

await block('Alertas: registrar el resultado (VEH129)', async () => {
  await go('/alertas');
  await role('coordinator');
  await tid('tab-vehicles').click();
  await expect(tid('alert-vehicle')).toHaveText('VEH129');
  await role('finance');
  await expect(tid('review-readonly')).toBeVisible();
  await tid('review').scrollIntoViewIfNeeded();
  await shot('alertas-40-solo-lectura-finanzas');
  await crop('alertas-41-solo-lectura-finanzas-recorte', tid('review'), { pad: 8 });
  await role('coordinator');
  await tid('review').scrollIntoViewIfNeeded();
  await crop('alertas-42-resultado-tres-opciones', tid('review'), { pad: 8 });
  await tid('review-save').click();
  await expect(tid('comment-error')).toBeVisible();
  await tid('review').scrollIntoViewIfNeeded();
  await crop('alertas-43-resultado-validacion', tid('review'), { pad: 8 });
  await tid('result-confirmed').click();
  await tid('review-comment').fill('Rinde 61 % menos que su grupo y no tiene servicios en EOM: va a revisión mecánica.');
  await tid('review').scrollIntoViewIfNeeded();
  await shot('alertas-44-resultado-confirmado-por-guardar');
  await crop('alertas-45-resultado-lleno', tid('review'), { pad: 8 });
  await tid('review-save').click();
  await expect(tid('review-result')).toHaveText('Confirmado');
  await page.locator('.ui-toast').first().waitFor().catch(() => {});
  await crop('alertas-46-aviso-resultado-registrado', page.locator('.ui-toast').first(), { pad: 8, keepToasts: true });
  await tid('review').scrollIntoViewIfNeeded();
  await shot('alertas-47-alerta-revisada');
  await crop('alertas-48-revisada-con-corregir', tid('review'), { pad: 8 });
  await page.getByRole('button', { name: 'Corregir' }).click();
  await tid('review').scrollIntoViewIfNeeded();
  await crop('alertas-49-corregir-formulario', tid('review'), { pad: 8 });
  await page.getByRole('button', { name: 'Cancelar' }).click();

  await tid('filter-reviewed').click();
  await page.waitForTimeout(300);
  await shot('alertas-50-filtro-revisadas');
  await crop('alertas-51-filtro-revisadas-lista', '.split__list', { pad: 4 });
  await tid('filter-all').click();
  await page.waitForTimeout(300);
  await shot('alertas-52-filtro-todas');
  await tid('filter-open').click();
  await page.waitForTimeout(300);
  await shot('alertas-53-filtro-abiertas');
});

await block('Conciliacion', async () => {
  await tid('tab-reconciliation').click();
  await expect(tid('import-sample')).toBeEnabled();
  await tid('import-sample').click();
  await expect(tid('import-summary')).toBeVisible();
  await page.locator('.ui-toast').first().waitFor({ timeout: 2000 }).catch(() => {});
  await shot('conciliacion-10-despues-de-cargar');
  await crop('conciliacion-11-resumen-de-la-carga', [tid('import-summary'), page.locator('.import__message')], { pad: 8 });
  await crop('conciliacion-12-tarjeta-veh023', tid('overpaid-card'), { pad: 8 });
  await tall(1280, async () => {
    await shot('conciliacion-13-despues-de-cargar-completo');
    await crop('conciliacion-14-autorizaciones-conciliadas', tid('matched'), { pad: 8 });
    await crop('conciliacion-15-filas-del-archivo', tid('import-lines'), { pad: 8 });
    await crop('conciliacion-16-otras-desviaciones', tid('deviations'), { pad: 8 });
    await crop('conciliacion-17-lo-que-no-cuadra', page.locator('app-card').filter({ has: tid('overpaid-card') }), { pad: 4 });
  });
  await crop('conciliacion-18-pestana-con-contador', '.tabs', { pad: 6 });

  await tid('import-sample').click();
  await expect(tid('import-imported')).toHaveText('0');
  await shot('conciliacion-20-segunda-carga-no-duplica');
  await crop('conciliacion-21-segunda-carga-resumen', [tid('import-summary'), page.locator('.import__message')], { pad: 8 });

  await role('support');
  await expect(tid('import-readonly')).toBeVisible();
  await crop('conciliacion-22-solo-lectura-soporte', [page.locator('.upload'), tid('import-readonly')], { pad: 8 });
  await role('coordinator');

  await tid('overpaid-review').click();
  await expect(tid('alert-vehicle')).toHaveText('VEH023');
  await shot('alertas-60-veh023-detalle');
  await tall(2300, async () => {
    await crop('alertas-61-veh023-detalle-completo', tid('alert-detail'), { pad: 6 });
    await crop('alertas-62-veh023-pagado-de-mas', tid('alert-overpaid'), { pad: 8 });
  });
});

await block('Reglas y umbrales', async () => {
  await go('/alertas');
  await role('coordinator');
  await tid('tab-rules').click();
  await expect(tid('rules-table').locator('tbody tr.is-clickable')).toHaveCount(25);
  await shot('reglas-10-catalogo-con-precision');
  await tid('rule-row-R08').click();
  await role('technician');
  await expect(tid('rules-readonly')).toBeVisible();
  await shot('reglas-11-solo-lectura-tecnico');
  await crop('reglas-12-solo-lectura-recorte', '.rule__edit', { pad: 8 });
  await role('coordinator');
  await crop('reglas-13-formulario-cambiar-umbral', '.rule__edit', { pad: 8 });
  await tid('rule-detail').locator('[data-testid^=param-]').first().fill('12');
  await tid('rule-save').click();
  await expect(tid('rule-error')).toContainText('motivo');
  await crop('reglas-14-motivo-obligatorio', '.rule__edit', { pad: 8 });
  await tid('rule-reason').fill('Ajuste acordado con operación tras la muestra etiquetada');
  await shot('reglas-15-cambio-pendiente');
  await crop('reglas-16-cambio-pendiente-recorte', '.rule__edit', { pad: 8 });
  await tid('rule-save').click();
  await expect(tid('rule-version')).toHaveText('v2');
  await page.locator('.ui-toast').first().waitFor({ timeout: 2000 }).catch(() => {});
  await crop('reglas-17-aviso-version-guardada', page.locator('.ui-toast').first(), { pad: 8, keepToasts: true });
  await shot('reglas-18-version-2-guardada');
  await tall(1500, async () => {
    await crop('reglas-19-detalle-version-2', tid('rule-detail'), { pad: 6 });
    await crop('reglas-20-historial-de-versiones', tid('rule-history'), { pad: 10 });
  });
  await crop('reglas-21-fila-r08-version-2', tid('rule-row-R08'), { pad: 4 });
  await crop('reglas-22-pie-del-catalogo', '.rules__footer', { pad: 6 });
});

// =====================================================================================
// 5. Tablero despues de usar la demo
// =====================================================================================

await block('Tablero despues de usar la demo', async () => {
  await go('/tablero');
  await role('technician');
  await expect(tid('indicators').locator('.kpi')).toHaveCount(9);
  await shot('tablero-10-despues-de-usar');
  await scrollContent('bottom');
  await shot('tablero-11-despues-de-usar-abajo');
  await scrollContent('top');
  await fullShot('tablero-12-despues-de-usar-completo');
  const extra = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra + 8, async () => {
    await crop('tablero-13-franja-del-piloto', '.pilot', { pad: 8 });
    await crop('tablero-14-indicadores', tid('indicators'), { pad: 8 });
    await crop('tablero-15-tarjeta-tiempo-de-atencion', tid('indicators').locator('.kpi').first(), { pad: 8 });
    await crop('tablero-16-tarjeta-alertas-prioridad-alta', tid('kpi-high_priority_alerts'), { pad: 8 });
    await crop('tablero-17-tarjeta-integraciones-ilustrativa', tid('kpi-integrations'), { pad: 8 });
    await crop('tablero-18-grafico-de-horas', 'app-card.context', { pad: 6 });
    await crop('tablero-19-desviaciones-abiertas', 'app-card.deviations', { pad: 6 });
    await crop('tablero-20-decision-al-cierre', 'app-card.decision', { pad: 6 });
  });
});

// =====================================================================================
// 6. Rechazo (demo reiniciada, con el VEH199 sembrado otra vez)
// =====================================================================================

await block('Rechazo de una solicitud', async () => {
  await reset();
  const request = await seedCase('VEH199');
  await go('/consola/' + request.id);
  await role('technician');
  await expect(tid('detail-plate')).toHaveText('ZZA199');
  await tid('reject').click();
  await expect(dialog).toBeVisible();
  await shot('consola-90-rechazar-dialogo');
  await crop('consola-91-rechazar-dialogo-recorte', dialog, { pad: 16 });
  await tid('decision-confirm').click();
  await expect(tid('reason-error')).toBeVisible();
  await crop('consola-92-rechazar-motivo-obligatorio', dialog, { pad: 16 });
  await page.locator('.det__suggestion').first().click();
  await crop('consola-93-rechazar-con-motivo', dialog, { pad: 16 });
  await tid('decision-confirm').click();
  await expect(tid('rejection')).toBeVisible();
  await shot('consola-94-solicitud-rechazada');
  await crop('consola-95-panel-rechazada', '.det__panel', { pad: 8 });
  const extra = await page.evaluate(() => {
    const main = document.querySelector('main.content');
    return Math.max(0, main.scrollHeight - main.clientHeight);
  });
  await tall(H + extra + 8, () => crop('consola-96-bitacora-rechazo', tid('audit-card'), { pad: 6 }));
  await tid('rejection').getByRole('link').click();
  await expect(tid('case-plate')).toHaveText('ZZA199');
  await expect(tid('request-stage')).toBeVisible();
  await shot('simulador-70-veh199-rechazada');
  await crop('simulador-71-mensaje-de-rechazo', phone);
  await crop('simulador-72-estado-rechazada', tid('status-card'), { pad: 4 });
  await go('/consola');
  await shot('consola-97-cola-con-rechazada');
});

await context.close();
await browser.close();
await reset();
await api('/dev/ai/restore', { method: 'POST' });
console.log('\nDemo reiniciada. ' + done.length + ' capturas en ' + outDir);

if (problems.length) {
  console.error('\nProblemas:');
  for (const problem of problems) console.error('  - ' + problem);
  process.exit(1);
}
