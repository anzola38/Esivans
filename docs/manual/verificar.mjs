// Ejecuta en la demo en marcha los procedimientos que describe el manual, con los mismos clics y los
// mismos nombres de botones, y guarda el texto de la pantalla despues de cada paso para compararlo con el manual.
//
//   OUT=<carpeta> node docs/manual/verificar.mjs
//
// Usa la IA simulada (no llama a servicios externos), empieza y termina con "Reiniciar demo" y no modifica
// nada del producto. Cada paso que no encuentra su boton o su texto queda anotado como FALLA en el resumen.
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

const log = [];
let n = 0;
const clean = (text) => (text ?? '').replace(/[  ]/g, ' ');

const ai = await (await fetch(BASE_URL + '/api/dev/ai')).json();
if (ai.active !== 'mock') throw new Error('La IA no esta en Simulada: no se ejecuta la verificacion.');

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  locale: 'es-CO',
  timezoneId: 'America/Bogota',
  permissions: ['clipboard-read', 'clipboard-write'],
});
const page = await context.newPage();
page.setDefaultTimeout(8000);
const toasts = [];
await page.exposeFunction('__toast', (text) => toasts.push(clean(text)));
await page.addInitScript(() => {
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === 1 && (node.matches?.('.ui-toast') || node.querySelector?.('.ui-toast'))) {
          const toast = node.matches('.ui-toast') ? node : node.querySelector('.ui-toast');
          setTimeout(() => window.__toast(toast.innerText.replace(/\n+/g, ' | ')), 60);
        }
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
});

async function snap(name) {
  n += 1;
  await page.waitForTimeout(350);
  const text = await page.evaluate(() => {
    const dialog = document.querySelector('.ui-modal__dialog');
    return (dialog ? '[VENTANA]\n' + dialog.innerText + '\n[FONDO]\n' : '') + document.body.innerText;
  });
  const file = String(n).padStart(3, '0') + '-' + name + '.txt';
  writeFileSync(resolve(out, file), clean(text) + '\n\n[AVISOS]\n' + toasts.splice(0).join('\n'), 'utf8');
  return clean(text);
}

async function step(name, action) {
  try {
    await action();
    log.push('ok    ' + name);
  } catch (error) {
    log.push('FALLA ' + name + ' -> ' + error.message.split('\n')[0]);
    await snap('FALLA-' + name.replace(/[^a-z0-9]+/gi, '-').slice(0, 40)).catch(() => {});
    await page.keyboard.press('Escape').catch(() => {});
  }
}

function expectText(text, needle, label) {
  const ok = text.replace(/\s+/g, ' ').includes(needle);
  log.push((ok ? 'ok    ' : 'FALLA ') + 'texto: ' + (label ?? needle));
  return ok;
}

const button = (name) => page.getByRole('button', { name, exact: true });
const menu = (name) => page.getByRole('navigation', { name: 'Navegación principal' }).getByRole('link', { name });
const role = (label) => page.getByRole('combobox', { name: 'Rol' }).selectOption({ label });
const chat = page.locator('.ui-phone__body');

async function waitReply(before) {
  await page.waitForFunction(
    (count) => {
      const body = document.querySelector('.ui-phone__body');
      const outgoing = body.querySelectorAll('.ui-bubble--out').length;
      const bubbles = body.querySelectorAll('.ui-bubble');
      const last = bubbles[bubbles.length - 1];
      return outgoing > count && !document.querySelector('[data-testid=typing]') && last && !last.classList.contains('ui-bubble--out');
    },
    before,
    { timeout: 15000 },
  );
}
async function drive(action) {
  const before = await chat.locator('.ui-bubble--out').count();
  await action();
  await waitReply(before);
}
const guion = () => drive(() => button('Siguiente paso del guion').click());
const quick = (name) => drive(() => page.getByTestId('quick-replies').getByRole('button', { name, exact: true }).click());
const type = (text) =>
  drive(async () => {
    const input = page.getByRole('textbox', { name: 'Mensaje del conductor' });
    await input.fill(text);
    await input.press('Enter');
  });
const pickCase = (name) => page.getByRole('tablist', { name: 'Casos' }).getByRole('tab', { name, exact: true }).click();

// ---------- Capitulo 2: entrar, marco, reiniciar, roles, IA ----------

await step('2.1 entrar por / abre el simulador', async () => {
  await page.goto(BASE_URL + '/');
  await page.locator('h1.topbar__title').waitFor();
  const text = await snap('entrar');
  expectText(text, 'Simulador del conductor');
  expectText(text, 'Técnico de Control y Monitoreo', 'rol inicial');
});
await step('2.4 Reiniciar demo (cabecera -> ventana -> Reiniciar demo)', async () => {
  await button('Reiniciar demo').click();
  const text = await snap('reiniciar-ventana');
  expectText(text, '¿Reiniciar la demo?');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancelar', exact: true }).waitFor();
  await page.getByRole('dialog').getByRole('button', { name: 'Reiniciar demo', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'detached' });
  await page.waitForTimeout(800);
  await snap('reiniciada');
});
await step('2.3 cambiar de rol: los cuatro roles', async () => {
  for (const label of ['Coordinador', 'Finanzas', 'Soporte', 'Técnico de Control y Monitoreo']) {
    await role(label);
    await snap('rol-' + label.split(' ')[0]);
  }
  const title = await page.locator('.role-picker').first().evaluate((el) => [...el.querySelectorAll('[title]')].map((x) => x.title).concat(el.title).join(' | '));
  log.push('info  title del selector de rol: ' + title);
});
await step('2.5 opciones de IA', async () => {
  const text = await page.getByTestId('case-card').innerText();
  writeFileSync(resolve(out, 'ia-ficha.txt'), clean(text), 'utf8');
  const states = await page.getByTestId('ai-switch').locator('button').evaluateAll((els) => els.map((el) => el.innerText.trim() + (el.disabled ? ' [apagada]' : '') + (el.classList.contains('is-active') ? ' [activa]' : '')));
  log.push('info  IA: ' + states.join(' / '));
});

// ---------- Capitulos 3, 5, 6 y 11: VEH901 ----------

await step('3.4 VEH901: hora simulada editable antes del primer mensaje', async () => {
  const clock = page.getByTestId('case-clock');
  log.push('info  hora simulada: ' + (await clock.inputValue()) + ' deshabilitada=' + (await clock.isDisabled()));
});
await step('3.4 VEH901: cuatro pasos del guion', async () => {
  for (let i = 1; i <= 4; i += 1) {
    log.push('info  linea del guion antes del paso ' + i + ': ' + clean(await page.getByTestId('case-card').innerText()).split(String.fromCharCode(10)).filter((line) => /^Paso \d/.test(line.trim())).join(''));
    await guion();
    await snap('veh901-paso-' + i);
  }
  const text = await snap('veh901-en-revision');
  expectText(text, 'Guion completo');
  expectText(text, 'Verde · 0 puntos');
  expectText(text, '$90.000');
  log.push('info  hora simulada tras el primer mensaje deshabilitada=' + (await page.getByTestId('case-clock').isDisabled()));
});
await step('3.9 VEH901: consulta de estado en revision', async () => {
  await type('¿ya me autorizaron?');
  await snap('veh901-consulta-en-revision');
});
await step('6.2 VEH901: Ver en la consola -> Aprobar en un clic', async () => {
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await button('Aprobar en un clic').waitFor();
  await snap('veh901-detalle');
  await page.locator('button.det__photo').click();
  await snap('veh901-foto-ampliada');
  await page.keyboard.press('Escape');
  await button('Aprobar en un clic').click();
  await button('Confirmar').waitFor();
  await snap('veh901-por-habilitar');
});
await step('6.6 VEH901: copiar valores', async () => {
  const copies = page.getByTestId('enablement').locator('button');
  const names = await copies.evaluateAll((els) => els.map((el) => (el.getAttribute('aria-label') || el.innerText).trim()));
  log.push('info  botones del panel de habilitacion: ' + names.join(' | '));
  await page.getByTestId('enablement').getByRole('button', { name: 'Copiar valor' }).click();
  await page.waitForTimeout(500);
  log.push('info  portapapeles tras Copiar valor: ' + JSON.stringify(await page.evaluate(() => navigator.clipboard.readText())));
  await button('Copiar todo').click();
  await page.waitForTimeout(500);
  log.push('info  portapapeles tras Copiar todo: ' + JSON.stringify(await page.evaluate(() => navigator.clipboard.readText())));
  await snap('veh901-copiar');
});
await step('3.9 VEH901: consulta de estado por habilitar', async () => {
  await menu('Simulador del conductor').click();
  await page.getByTestId('status-card').waitFor();
  await snap('veh901-simulador-por-habilitar');
  await type('¿ya me autorizaron?');
  await snap('veh901-consulta-por-habilitar');
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await button('Confirmar').waitFor();
});
await step('6.6 VEH901: Confirmar la habilitacion', async () => {
  await button('Confirmar').click();
  await page.getByTestId('authorization').waitFor();
  await snap('veh901-autorizada');
  await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
  await page.getByTestId('status-card').waitFor();
  await snap('veh901-mensaje-al-conductor');
  await type('Necesito tanquear');
  await snap('veh901-autorizacion-vigente');
});

// ---------- VEH015 ----------

await step('3.5 VEH015: tres pasos del guion y respuesta rapida', async () => {
  await pickCase('VEH015');
  await page.waitForTimeout(400);
  for (let i = 1; i <= 3; i += 1) {
    await guion();
    await snap('veh015-paso-' + i);
  }
  await quick('Sí, es 34.086');
  const text = await snap('veh015-en-revision');
  expectText(text, 'Amarillo · 1 punto');
  expectText(text, '$50.000');
});
await step('6.3 VEH015: Aprobar con motivo', async () => {
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await button('Aprobar con motivo').waitFor();
  await snap('veh015-detalle');
  log.push('info  existe "Aprobar en un clic" en amarillo: ' + (await button('Aprobar en un clic').count()));
  await button('Aprobar con motivo').click();
  await snap('veh015-ventana');
  await page.getByRole('dialog').getByRole('button', { name: 'Aprobar', exact: true }).click();
  await snap('veh015-ventana-sin-motivo');
  await page.getByRole('dialog').getByRole('button', { name: 'Kilometraje corregido y confirmado por el conductor', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Aprobar', exact: true }).click();
  await button('Confirmar').waitFor();
  await snap('veh015-por-habilitar');
  await button('Confirmar').click();
  await page.getByTestId('authorization').waitFor();
  await snap('veh015-autorizada');
});

// ---------- VEH199 ----------

await step('3.6 VEH199: cuatro pasos del guion', async () => {
  await menu('Simulador del conductor').click();
  await pickCase('VEH199');
  await page.waitForTimeout(400);
  for (let i = 1; i <= 4; i += 1) {
    await guion();
    await snap('veh199-paso-' + i);
  }
  const text = await snap('veh199-en-revision');
  expectText(text, 'Rojo · 7 puntos');
  expectText(text, '$10.000');
});
await step('4 cola con una solicitud abierta y dos cerradas', async () => {
  await menu('Consola del técnico').click();
  await page.getByTestId('queue-table').waitFor();
  await snap('cola');
});
await step('6.4 VEH199: Ajustar con validaciones', async () => {
  await page.getByTestId('queue-table').getByRole('link', { name: 'Revisar', exact: true }).first().click();
  await button('Ajustar').waitFor();
  await snap('veh199-detalle');
  await button('Ajustar').click();
  await snap('veh199-ajustar-ventana');
  const amount = page.getByRole('dialog').getByRole('textbox').first();
  const field = page.getByRole('dialog').locator('input').first();
  for (const value of ['50000', '0', '20000.5']) {
    await field.fill(value);
    await page.getByRole('dialog').getByRole('button', { name: 'Guardar ajuste', exact: true }).click();
    await snap('veh199-ajustar-valor-' + value.replace('.', '_'));
  }
  void amount;
  await field.fill('20000');
  await page.getByRole('dialog').getByRole('button', { name: 'Apoyo nocturno confirmado con el coordinador', exact: true }).click();
  await snap('veh199-ajustar-lleno');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar ajuste', exact: true }).click();
  await button('Confirmar').waitFor();
  await snap('veh199-por-habilitar');
  await button('Confirmar').click();
  await page.getByTestId('authorization').waitFor();
  await snap('veh199-autorizada');
  await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
  await page.getByTestId('status-card').waitFor();
  await snap('veh199-mensaje-al-conductor');
});

// ---------- Roles de solo lectura en la consola ----------

await step('6.9 solo lectura con Finanzas y Soporte en el detalle', async () => {
  await menu('Consola del técnico').click();
  await page.getByTestId('queue-table').getByRole('link', { name: 'Ver', exact: true }).first().click();
  await page.getByTestId('audit-card').waitFor();
  for (const label of ['Finanzas', 'Soporte']) {
    await role(label);
    await snap('detalle-solo-lectura-' + label);
  }
});

// ---------- Capitulo 7: alertas ----------

await step('7.2 alertas con el rol Coordinador', async () => {
  await role('Coordinador');
  await menu('Alertas del coordinador').click();
  await page.getByTestId('alert-list').waitFor();
  await snap('alertas-tanqueos');
  await page.getByTestId('filter-reviewed').click();
  await snap('alertas-tanqueos-revisadas');
  await page.getByTestId('filter-all').click();
  await snap('alertas-tanqueos-todas');
  await page.getByTestId('filter-open').click();
});
await step('7.7 validacion: Registrar resultado sin opcion ni comentario', async () => {
  await page.getByTestId('alert-list').locator('li').nth(1).click();
  await button('Registrar resultado').click();
  await snap('alerta-validacion');
});
await step('7.7 VEH129: Confirmado + Registrar resultado', async () => {
  await page.getByRole('tab', { name: 'Vehículos' }).click();
  await page.waitForTimeout(500);
  await snap('alertas-vehiculos');
  await page.getByRole('radio', { name: 'Confirmado' }).click();
  await snap('veh129-confirmado-marcado');
  await button('Registrar resultado').click();
  await page.getByTestId('review-closed').waitFor();
  await snap('veh129-revisada');
});
await step('7.8 Corregir una alerta revisada', async () => {
  await button('Corregir').click();
  await snap('veh129-corregir');
  await button('Cancelar').click();
  await snap('veh129-corregir-cancelado');
});
await step('7.10 solo lectura en alertas con Finanzas y Tecnico', async () => {
  for (const label of ['Finanzas', 'Técnico de Control y Monitoreo']) {
    await role(label);
    await page.getByTestId('filter-open').click();
    await page.getByTestId('alert-list').locator('li').first().click();
    await snap('alerta-solo-lectura-' + label.split(' ')[0]);
  }
  await role('Coordinador');
});
await step('7.6 VEH160: libro unico con dos proveedores', async () => {
  await page.getByTestId('alert-list').getByText('VEH160').first().click();
  await snap('veh160');
  const more = page.getByRole('button', { name: /^Ver los \d+ movimientos$/ });
  log.push('info  boton de movimientos: ' + (await more.innerText().catch(() => 'no aparece')));
  await more.click();
  await snap('veh160-todos-los-movimientos');
  await button('Ver solo los últimos').click();
});

// ---------- Capitulo 8: conciliacion ----------

await step('8.3 Conciliacion: solo lectura con Soporte y Tecnico', async () => {
  await page.getByRole('tab', { name: 'Conciliación' }).click();
  await snap('conciliacion-antes');
  for (const label of ['Soporte', 'Técnico de Control y Monitoreo']) {
    await role(label);
    await snap('conciliacion-solo-lectura-' + label.split(' ')[0]);
  }
  await role('Finanzas');
  log.push('info  Finanzas puede cargar: ' + (await button('Cargar exporte de ejemplo de Terpel').isEnabled()));
  await role('Coordinador');
});
await step('8.3 Cargar exporte de ejemplo de Terpel', async () => {
  await button('Cargar exporte de ejemplo de Terpel').click();
  await page.getByTestId('import-summary').waitFor();
  const text = await snap('conciliacion-primera-carga');
  expectText(text, '$27.783');
});
await step('8.5 Revisar la alerta del VEH023', async () => {
  await button('Revisar la alerta').click();
  await page.getByTestId('alert-detail').waitFor();
  await snap('veh023-alerta');
  await page.getByRole('radio', { name: 'Confirmado' }).click();
  await button('Registrar resultado').click();
  await page.getByTestId('review-closed').waitFor();
  await page.getByRole('tab', { name: 'Conciliación' }).click();
  await snap('conciliacion-veh023-revisada');
});
await step('8.7 segunda carga del mismo archivo', async () => {
  await button('Cargar exporte de ejemplo de Terpel').click();
  await page.waitForTimeout(1500);
  await snap('conciliacion-segunda-carga');
});

// ---------- Capitulo 9: reglas ----------

await step('9 catalogo y solo lectura con el Tecnico', async () => {
  await page.getByRole('tab', { name: 'Reglas y umbrales' }).click();
  await page.getByTestId('rules-table').waitFor();
  await snap('reglas-coordinador');
  await role('Técnico de Control y Monitoreo');
  await snap('reglas-solo-lectura');
  await role('Coordinador');
});
await step('9.5 cambiar el umbral de R08 de 24 a 12', async () => {
  await page.getByTestId('rules-table').getByText('R08', { exact: true }).click();
  const field = page.getByTestId('param-window_h');
  await button('Guardar como versión 2').click();
  await snap('reglas-sin-cambios');
  await field.fill('12');
  await button('Guardar como versión 2').click();
  await snap('reglas-sin-motivo');
  await field.fill('abc');
  await button('Guardar como versión 2').click();
  await snap('reglas-valor-invalido');
  await button('Deshacer').click();
  await snap('reglas-deshacer');
  await field.fill('12');
  await page.getByRole('textbox', { name: 'Motivo del cambio' }).fill('Acordado con operaciones: ventana de 12 horas.');
  await button('Guardar como versión 2').click();
  await button('Guardar como versión 3').waitFor();
  await snap('reglas-version-2');
  await page.getByTestId('rules-table').getByText('R01', { exact: true }).click();
  await snap('reglas-r01');
});

// ---------- VEH902 y Sin registro ----------

await step('3.7 VEH902: guion completo (cerrada sin tanqueo)', async () => {
  await role('Técnico de Control y Monitoreo');
  await menu('Simulador del conductor').click();
  await pickCase('VEH902');
  await page.waitForTimeout(400);
  for (let i = 1; i <= 4; i += 1) {
    await guion();
    await snap('veh902-paso-' + i);
  }
  await guion();
  const text = await snap('veh902-cerrada');
  expectText(text, 'Cerrada sin tanqueo');
  await type('¿ya me autorizaron?');
  await snap('veh902-consulta-sin-solicitud');
});
await step('3.8 Sin registro: un paso y camara apagada', async () => {
  await pickCase('Sin registro');
  await page.waitForTimeout(400);
  log.push('info  camara apagada en Sin registro: ' + (await page.getByTestId('attach-photo').isDisabled()));
  await guion();
  await snap('sin-registro');
});
await step('6.11 Sin placa: aprobar no se puede; rechazar si', async () => {
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await button('Rechazar').waitFor();
  await snap('sin-placa-detalle');
  await button('Aprobar con motivo').click();
  await page.getByRole('dialog').getByRole('textbox').first().fill('Prueba de aprobación sin vehículo');
  await page.getByRole('dialog').getByRole('button', { name: 'Aprobar', exact: true }).click();
  await snap('sin-placa-aprobar');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancelar', exact: true }).click();
  await button('Rechazar').click();
  await snap('rechazar-ventana');
  await page.getByRole('dialog').getByRole('button', { name: 'Rechazar', exact: true }).click();
  await snap('rechazar-sin-motivo');
  await page.getByRole('dialog').getByRole('button', { name: 'Sin servicio que respalde la carga', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Rechazar', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'detached' });
  await snap('rechazada');
  await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
  await page.getByTestId('status-card').waitFor();
  await snap('rechazo-mensaje-al-conductor');
});
await step('4 cola final y 6.11 cerrada sin tanqueo', async () => {
  await menu('Consola del técnico').click();
  await page.getByTestId('queue-table').waitFor();
  await snap('cola-final');
  await page.getByTestId('queue-table').getByText('ZZA902').first().click();
  await page.getByTestId('audit-card').waitFor();
  await snap('veh902-detalle-cerrada');
});

// ---------- Capitulo 10: tablero ----------

await step('10 tablero despues de usar la demo', async () => {
  await menu('Tablero del piloto').click();
  await page.getByTestId('indicators').waitFor();
  await page.waitForTimeout(1200);
  await snap('tablero-despues');
  const titles = await page.getByTestId('indicators').locator('[title]').evaluateAll((els) => els.map((el) => el.title).filter(Boolean));
  writeFileSync(resolve(out, 'tablero-notas.txt'), clean(titles.join('\n')), 'utf8');
});

// ---------- Cierre: demo reiniciada ----------

await step('cierre: Reiniciar demo y estado inicial', async () => {
  await button('Reiniciar demo').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reiniciar demo', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'detached' });
  await page.waitForTimeout(1500);
  await snap('tablero-reiniciado');
  await role('Coordinador');
  await menu('Alertas del coordinador').click();
  await page.getByRole('tab', { name: 'Reglas y umbrales' }).waitFor();
  log.push('info  pestaña activa al volver a Alertas: ' + (await page.getByRole('tab', { selected: true }).innerText()).replace(/\s+/g, ' '));
  await page.getByRole('tab', { name: 'Tanqueos con alerta' }).click();
  await page.getByTestId('alert-list').waitFor();
  await snap('alertas-reiniciadas');
  await page.getByRole('tab', { name: 'Reglas y umbrales' }).click();
  await page.getByTestId('rules-table').waitFor();
  await snap('reglas-reiniciadas');
  await page.getByRole('tab', { name: 'Conciliación' }).click();
  await snap('conciliacion-reiniciada');
  await role('Técnico de Control y Monitoreo');
  await menu('Consola del técnico').click();
  await snap('cola-reiniciada');
});

await browser.close();
const after = await (await fetch(BASE_URL + '/api/dev/ai')).json();
log.push('info  IA al terminar: ' + after.active_label);
writeFileSync(resolve(out, '000-resumen.txt'), log.join('\n') + '\n', 'utf8');
console.log(log.join('\n'));
