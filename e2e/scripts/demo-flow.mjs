// Recorre el guion de la demo (hito H4) contra el stack real y guarda capturas de cada paso
// a 1366x768 y 1920x1080. Sale con codigo 1 si algo no cuadra.
//
//   node scripts/demo-flow.mjs                          -> capturas en ../docs/screenshots
//   BASE_URL=http://localhost:8080 OUT_DIR=screenshots node scripts/demo-flow.mjs
//   VIEWPORT=1366x768 node scripts/demo-flow.mjs        -> un solo tamano
//
// Empieza y termina con POST /api/dev/reset: la demo queda limpia.
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE_URL, VIEWPORTS } from './env.mjs';

const { chromium, expect } = await import('@playwright/test');

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, '..', process.env.OUT_DIR ?? '../docs/screenshots');
const FOOTER = 'Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección';
const only = process.env.VIEWPORT;

mkdirSync(outDir, { recursive: true });

const problems = [];
const browser = await chromium.launch();

async function reset() {
  const response = await fetch(BASE_URL + '/api/dev/reset', { method: 'POST' });
  if (!response.ok) throw new Error('POST /api/dev/reset respondio ' + response.status);
}

for (const viewport of VIEWPORTS.filter((v) => !only || v.name === only)) {
  console.log('\n== ' + viewport.name + ' ==');
  await reset();
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => problems.push(viewport.name + ' error de JavaScript: ' + error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('422')) {
      problems.push(viewport.name + ' consola: ' + message.text());
    }
  });

  let counter = 0;
  /** Captura + revision de desbordes, pie y tipografia. */
  async function shot(name) {
    counter += 1;
    // Los avisos emergentes tapan parte de la pantalla: se cierran antes de capturar.
    for (const close of await page.locator('.ui-toast button').all()) await close.click().catch(() => {});
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(350);
    const file = String(counter).padStart(2, '0') + '-' + name + '-' + viewport.name + '.png';
    await page.screenshot({ path: resolve(outDir, file) });
    const report = await page.evaluate(() => {
      const doc = document.documentElement;
      const content = document.querySelector('main.content');
      return {
        overflowX: doc.scrollWidth > doc.clientWidth,
        contentOverflowX: content ? content.scrollWidth > content.clientWidth : false,
        footer: document.querySelector('footer')?.textContent?.trim() ?? '',
        lato: document.fonts.check('16px Lato'),
      };
    });
    if (report.overflowX || report.contentOverflowX) problems.push(file + ': desborde horizontal');
    if (report.footer !== FOOTER) problems.push(file + ': pie distinto');
    if (!report.lato) problems.push(file + ': Lato sin cargar');
    console.log('  ' + file);
  }

  const chat = page.locator('.ui-phone__body');
  const lastAssistantBubble = chat.locator('.ui-bubble:not(.ui-bubble--out):not(.sim__typing)').last();

  /** Espera a que el conductor tenga `count` mensajes y el asistente haya respondido. */
  async function waitForReply(count) {
    await expect(chat.locator('.ui-bubble--out')).toHaveCount(count);
    await expect(page.getByTestId('typing')).toHaveCount(0);
    await expect(chat.locator('.ui-bubble').last()).not.toHaveClass(/ui-bubble--out/);
  }

  async function scriptStep() {
    const before = await chat.locator('.ui-bubble--out').count();
    await page.getByTestId('script-next').click();
    await waitForReply(before + 1);
  }

  async function scrollContent(position) {
    await page.evaluate((to) => {
      const main = document.querySelector('main.content');
      main.scrollTo({ top: to === 'bottom' ? main.scrollHeight : 0 });
    }, position);
  }

  // ---------- 1. Caso verde ----------
  await page.goto(BASE_URL + '/simulador', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('case-driver')).toHaveText('Carlos Andrés Pérez');
  await expect(page.getByTestId('case-plate')).toHaveText('ZZA901');
  await expect(page.getByTestId('case-clock')).toHaveValue('09:40');
  await shot('simulador-caso-verde-inicio');

  await scriptStep();
  await expect(chat).toContainText('Hola, Carlos');
  await expect(chat).toContainText('ZZA901');
  await expect(page.getByTestId('quick-replies')).toContainText('Sí, es para esa ruta');
  await shot('verde-saludo-y-servicio-eom');

  await scriptStep();
  await scriptStep();
  await expect(chat.locator('img.sim__photo')).toHaveCount(1);
  await expect(lastAssistantBubble).toContainText('48.352 km');
  await shot('verde-foto-y-lectura');

  await scriptStep();
  await expect(page.getByTestId('request-stage')).toHaveText('En revisión');
  await expect(page.locator('[data-testid=timeline] [data-status=in_review]')).toHaveAttribute('data-state', 'current');
  await shot('verde-solicitud-en-revision');

  await page.goto(BASE_URL + '/consola', { waitUntil: 'networkidle' });
  const greenRow = page.locator('[data-plate=ZZA901]');
  await expect(greenRow).toContainText('Verde');
  await expect(greenRow).toContainText('Carlos Andrés Pérez');
  await expect(greenRow).toContainText('$90.000');
  await shot('consola-cola-verde');

  await greenRow.click();
  await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');
  await expect(page.getByTestId('detail-light')).toContainText('Verde');
  await expect(page.getByTestId('detail-amount')).toHaveText('$90.000');
  await expect(page.getByTestId('no-alerts')).toContainText('Sin alertas');
  await expect(page.getByTestId('approve')).toHaveText(/Aprobar en un clic/);
  await expect(page.getByTestId('calc-card')).toContainText('Valor sugerido');
  await shot('verde-detalle');

  await page.getByTestId('approve').click();
  const enablement = page.getByTestId('enablement');
  await expect(enablement).toContainText('Habilitar en el portal del proveedor');
  for (const text of ['Terpel', 'ZZA901', '$90.000', 'Gasolina Corriente', '2 horas']) {
    await expect(enablement).toContainText(text);
  }
  await expect(page.getByTestId('reference-input')).toHaveValue(/^TER-/);
  await shot('verde-habilitar-en-el-portal');
  await page.getByTestId('copy-plate').click();
  await expect(page.locator('.ui-toast')).toContainText('Placa en el portapapeles');

  const reference = await page.getByTestId('reference-input').inputValue();
  await page.getByTestId('confirm-enablement').click();
  await expect(page.getByTestId('authorization')).toContainText(reference);
  await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
  await page.locator('.ui-toast').first().waitFor();
  await shot('verde-autorizada');

  const audit = page.getByTestId('audit-card');
  await expect(audit.locator('[data-action="decision.approve"]')).toContainText('Laura Mendoza');
  await expect(audit.locator('[data-action="decision.approve"]')).toContainText('en un clic');
  await expect(audit.locator('[data-action="authorization.enabled"]')).toContainText(reference);
  await expect(audit).toContainText('v1');
  await scrollContent('bottom');
  await shot('verde-bitacora');

  await scrollContent('top');
  await page.getByTestId('to-simulator').click();
  await expect(page.getByTestId('case-plate')).toHaveText('ZZA901');
  for (const text of ['$90.000', 'Gasolina Corriente', 'Referencia: ' + reference, 'Vigencia: 2 horas']) {
    await expect(lastAssistantBubble).toContainText(text);
  }
  await expect(page.locator('[data-testid=timeline] [data-status=authorized]')).toHaveAttribute('data-state', 'done');
  await expect(page.getByTestId('authorization-summary')).toContainText(reference);
  await shot('verde-conductor-recibe-autorizacion');

  // ---------- 2. VEH015: error de digitacion (R02) ----------
  await page.getByTestId('case-VEH015').click();
  await expect(page.getByTestId('case-plate')).toHaveText('ZZA015');
  await scriptStep();
  await scriptStep();
  await scriptStep();
  await expect(lastAssistantBubble).toContainText('24.086 km');
  await expect(lastAssistantBubble).toContainText('34.086 km');
  await shot('veh015-propone-34086');

  const before015 = await chat.locator('.ui-bubble--out').count();
  await page.getByTestId('quick-replies').getByRole('button', { name: 'Sí, es 34.086' }).click();
  await waitForReply(before015 + 1);
  await expect(page.getByTestId('request-stage')).toHaveText('En revisión');
  await shot('veh015-conductor-confirma');

  await page.getByTestId('open-console').click();
  await expect(page.getByTestId('detail-plate')).toHaveText('ZZA015');
  await expect(page.getByTestId('detail-light')).toContainText('Amarillo');
  await expect(page.locator('[data-rule=R02]')).toContainText('34.086 km');
  await expect(page.getByTestId('odometer')).toHaveText('34.086 km');
  await expect(page.getByTestId('odometer-correction')).toContainText('24.086 km');
  await expect(page.getByTestId('approve')).toHaveText(/Aprobar con motivo/);
  await shot('veh015-detalle-amarillo-r02');

  // Sin un clic: pide el motivo, y la API tambien lo exige.
  await page.getByTestId('approve').click();
  await page.getByTestId('decision-confirm').click();
  await expect(page.getByTestId('reason-error')).toBeVisible();
  await shot('veh015-motivo-obligatorio');
  const id015 = page.url().split('/').pop();
  const noReason = await page.request.post(BASE_URL + '/api/requests/' + id015 + '/decision', {
    data: { action: 'approve' },
  });
  if (noReason.status() !== 422) problems.push('VEH015: aprobar sin motivo respondio ' + noReason.status());
  await page.locator('.det__suggestion').first().click();
  await page.getByTestId('decision-confirm').click();
  await expect(page.getByTestId('enablement')).toContainText('$50.000');
  await page.getByTestId('confirm-enablement').click();
  await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');

  // ---------- 3. VEH199 a las 11:14 p. m. ----------
  await page.goto(BASE_URL + '/simulador', { waitUntil: 'networkidle' });
  await page.getByTestId('case-VEH199').click();
  await expect(page.getByTestId('case-clock')).toHaveValue('23:14');
  await scriptStep();
  await expect(chat.locator('.ui-bubble__time').first()).toHaveText('11:14 p. m.');
  await scriptStep();
  await scriptStep();
  await scriptStep();
  await expect(page.getByTestId('request-stage')).toHaveText('En revisión');
  await shot('veh199-conversacion-nocturna');

  await page.getByTestId('open-console').click();
  await expect(page.getByTestId('detail-plate')).toHaveText('ZZA199');
  await expect(page.getByTestId('detail-light')).toContainText('Rojo');
  await expect(page.getByTestId('detail-light')).toContainText('7 puntos');
  await expect(page.locator('[data-rule=R05]')).toContainText('6,7 m³ de GNV con 22 km');
  await expect(page.locator('[data-rule=R08]')).toContainText('sin servicios con desplazamiento 24 h');
  await expect(page.locator('[data-rule=R09]')).toContainText('23:14');
  await shot('veh199-detalle-rojo-7-puntos');

  // Solo lectura para los demas roles.
  await page.getByTestId('role-select').selectOption('support');
  await expect(page.getByTestId('read-only')).toBeVisible();
  await expect(page.getByTestId('approve')).toBeDisabled();
  await expect(page.getByTestId('adjust')).toBeDisabled();
  await shot('veh199-solo-lectura-soporte');
  await page.getByTestId('role-select').selectOption('technician');
  await expect(page.getByTestId('adjust')).toBeEnabled();

  // Ajustar: motivo obligatorio y tope validados en la interfaz y en la API.
  await page.getByTestId('adjust').click();
  await page.getByTestId('amount-input').fill('500000');
  await page.getByTestId('decision-confirm').click();
  await expect(page.getByTestId('reason-error')).toBeVisible();
  await expect(page.getByTestId('amount-error')).toContainText('$40.000');
  await shot('veh199-ajustar-validacion');
  const id199 = page.url().split('/').pop();
  const adjustNoReason = await page.request.post(BASE_URL + '/api/requests/' + id199 + '/decision', {
    data: { action: 'adjust', amount: 20000 },
  });
  if (adjustNoReason.status() !== 422) problems.push('VEH199: ajustar sin motivo respondio ' + adjustNoReason.status());

  await page.getByTestId('amount-input').fill('20000');
  await page.locator('.det__suggestion').first().click();
  await shot('veh199-ajustar-con-motivo');
  await page.getByTestId('decision-confirm').click();
  await expect(page.getByTestId('enablement')).toContainText('$20.000');
  await expect(page.getByTestId('detail-amount')).toHaveText('$20.000');
  await shot('veh199-habilitar-valor-ajustado');
  await page.getByTestId('confirm-enablement').click();
  await expect(page.getByTestId('authorization')).toContainText('$10.000');
  await expect(audit.locator('[data-action="decision.adjust"]')).toContainText('Apoyo nocturno');
  await scrollContent('bottom');
  await shot('veh199-bitacora-ajuste');

  await page.goto(BASE_URL + '/consola', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('queue-table').locator('tbody tr')).toHaveCount(3);
  await shot('consola-cola-al-final');

  // ---------- 4. Casos de borde: no necesita tanquear y numero no registrado ----------
  await page.goto(BASE_URL + '/simulador', { waitUntil: 'networkidle' });
  await page.getByTestId('case-NO_FUEL').click();
  await expect(page.getByTestId('case-plate')).toHaveText('ZZA902');
  await expect(chat.locator('.ui-bubble')).toHaveCount(0);
  for (let i = 0; i < 5; i += 1) await scriptStep();
  await expect(page.getByTestId('request-stage')).toHaveText('Cerrada sin tanqueo');
  await shot('extra-no-necesita-tanquear');

  await page.getByTestId('case-UNREGISTERED').click();
  await expect(page.getByTestId('case-driver')).toHaveText('Número no registrado');
  await expect(chat.locator('.ui-bubble')).toHaveCount(0);
  await expect(page.getByTestId('attach-photo')).toBeDisabled();
  await scriptStep();
  await expect(page.getByTestId('request-stage')).toHaveText('En revisión');
  await shot('extra-numero-no-registrado');
  await page.getByTestId('open-console').click();
  await expect(page.getByTestId('detail-plate')).toHaveText('Sin placa');
  await expect(page.getByTestId('detail-light')).toContainText('Amarillo');
  await shot('extra-numero-no-registrado-detalle');

  // ---------- 5. La cola con los tres semaforos por decidir ----------
  await page.goto(BASE_URL + '/consola', { waitUntil: 'networkidle' });
  await reset();
  const cases = (await (await fetch(BASE_URL + '/api/dev/simulator/cases')).json()).items;
  for (const code of ['VEH199', 'VEH015', 'GREEN']) {
    for (const step of cases.find((c) => c.code === code).script) {
      await fetch(BASE_URL + '/api/dev/simulator/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_code: code, ...step }),
      });
      await page.waitForTimeout(900);
    }
  }
  await page.goto(BASE_URL + '/consola', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('queue-table').locator('tbody tr')).toHaveCount(3);
  await expect(page.getByTestId('queue-counts')).toContainText('Por decidir: 3');
  const plates = await page.getByTestId('queue-table').locator('tbody tr').evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-plate')),
  );
  if (plates.join() !== 'ZZA199,ZZA015,ZZA901') problems.push('La cola no esta ordenada por espera: ' + plates.join());
  await shot('consola-cola-tres-semaforos');

  await context.close();
}

await browser.close();
await reset();
console.log('\nDemo reiniciada (POST /api/dev/reset).');

if (problems.length) {
  console.error('\nProblemas encontrados:');
  for (const problem of problems) console.error('  - ' + problem);
  process.exit(1);
}
console.log('Guion completo sin problemas. Capturas en ' + outDir);
