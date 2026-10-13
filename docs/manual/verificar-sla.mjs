// Comprueba en la demo en marcha dos comportamientos que exigen esperar o coincidir con otra persona:
//   1. A los 10 minutos reales, una solicitud incompleta pasa sola al tecnico (capitulos 3 y 4 del manual).
//   2. Si dos personas deciden la misma solicitud, solo se guarda la primera decision (capitulo 6).
//
//   OUT=<carpeta> node docs/manual/verificar-sla.mjs      (tarda unos 11 minutos)
//
// Usa la IA simulada, no modifica nada del producto y termina con "Reiniciar demo".
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE_URL } from '../../e2e/scripts/env.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, '../../e2e/package.json'));
const { chromium } = require('@playwright/test');

const out = resolve(process.env.OUT ?? resolve(here, 'verificacion'));
mkdirSync(out, { recursive: true });
const clean = (text) => (text ?? '').replace(/[  ]/g, ' ');
const log = [];

const ai = await (await fetch(BASE_URL + '/api/dev/ai')).json();
if (ai.active !== 'mock') throw new Error('La IA no esta en Simulada: no se ejecuta la verificacion.');

async function api(path, { method = 'GET', body, role = 'technician', user = 'Laura Mendoza' } = {}) {
  const response = await fetch(BASE_URL + '/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Demo-Role': role, 'X-Demo-User': encodeURIComponent(user) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: response.status, json: await response.json().catch(() => null) };
}

await api('/dev/reset', { method: 'POST' });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'es-CO', timezoneId: 'America/Bogota' });
const page = await context.newPage();
page.setDefaultTimeout(10000);
let n = 0;
async function snap(name) {
  n += 1;
  await page.waitForTimeout(400);
  const text = await page.evaluate(() => {
    const dialog = document.querySelector('.ui-modal__dialog');
    return (dialog ? '[VENTANA]\n' + dialog.innerText + '\n[FONDO]\n' : '') + document.body.innerText;
  });
  writeFileSync(resolve(out, 'sla-' + String(n).padStart(2, '0') + '-' + name + '.txt'), clean(text), 'utf8');
  return clean(text).replace(/\s+/g, ' ');
}
const check = (text, needle) => log.push((text.includes(needle) ? 'ok    ' : 'FALLA ') + needle);

// 1. Solicitud incompleta: un solo mensaje del conductor del VEH902 y nada mas.
await page.goto(BASE_URL + '/simulador');
await page.getByRole('tablist', { name: 'Casos' }).getByRole('tab', { name: 'VEH902', exact: true }).click();
await page.waitForTimeout(500);
await page.getByRole('button', { name: 'Siguiente paso del guion', exact: true }).click();
await page.waitForTimeout(4000);
check(await snap('inicio'), 'SLA de 10 minutos: quedan');
await page.getByRole('navigation', { name: 'Navegación principal' }).getByRole('link', { name: 'Consola del técnico' }).click();
await page.getByTestId('queue-table').waitFor();
const early = await snap('cola-con-asistente');
check(early, 'Sin evaluar');
check(early, 'Esperando evidencia');
check(early, 'Por decidir: 0');

// A los 7,5 minutos el plazo debe verse en ambar (quedan 3 minutos o menos).
await page.waitForTimeout(7.5 * 60 * 1000);
const amber = await snap('cola-menos-de-3-minutos');
log.push('info  SLA en ambar en la cola: ' + (await page.locator('.queue__sla.is-warn').count()));

// Pasados los 10 minutos.
await page.waitForTimeout(3.2 * 60 * 1000);
const late = await snap('cola-vencida');
check(late, 'Vencido hace');
check(late, 'En revisión');
check(late, 'Llegó sin: servicio o justificación, foto del tablero');
await page.getByTestId('queue-table').getByRole('link', { name: 'Revisar', exact: true }).first().click();
await page.getByTestId('audit-card').waitFor();
const detail = await snap('detalle-incompleta');
check(detail, 'SLA vencido hace');
check(detail, 'Pasó al técnico incompleta. Faltó:');
check(detail, 'Solicitud incompleta');
check(detail, 'Odómetro sin dato');
check(detail, 'SLA de 10 minutos cumplido: pasa al técnico');
const requestId = Number(new URL(page.url()).pathname.split('/').pop());

await page.getByRole('navigation', { name: 'Navegación principal' }).getByRole('link', { name: 'Simulador del conductor' }).click();
await page.getByTestId('status-card').waitFor();
const sim = await snap('simulador-tras-el-plazo');
check(sim, 'pasé tu solicitud al técnico de Control y Monitoreo con lo que hay para no hacerte esperar');
check(sim, 'Pasó al técnico por SLA de 10 min. Faltó:');
check(sim, 'SLA de 10 minutos vencido');

// 2. Dos personas deciden: el tecnico abre "Rechazar"; mientras tanto decide el coordinador.
await page.goto(BASE_URL + '/consola/' + requestId);
await page.getByRole('button', { name: 'Rechazar', exact: true }).click();
await page.getByRole('dialog').getByRole('button', { name: 'Sin servicio que respalde la carga', exact: true }).click();
const other = await api('/requests/' + requestId + '/decision', {
  method: 'POST', role: 'coordinator', user: 'Carlos Rivas', body: { action: 'reject', reason: 'Decisión del coordinador en la prueba' },
});
log.push('info  decision del coordinador por fuera de la pantalla: HTTP ' + other.status);
await page.getByRole('dialog').getByRole('button', { name: 'Rechazar', exact: true }).click();
const conflict = await snap('ya-decidida');
check(conflict, 'Esta solicitud ya fue decidida por Carlos Rivas (rechazada)');
await page.getByRole('dialog').getByRole('button', { name: 'Cancelar', exact: true }).click();
await page.waitForTimeout(3500);
check(await snap('detalle-tras-el-conflicto'), 'Rechazada por Carlos Rivas');

await browser.close();
await api('/dev/reset', { method: 'POST' });
void amber;
writeFileSync(resolve(out, 'sla-00-resumen.txt'), log.join('\n') + '\n', 'utf8');
console.log(log.join('\n'));
