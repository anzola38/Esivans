import { api, expect, openSimulator, seedCase, selectRole, test, todayText } from './support/fixtures.mjs';

const CODES = [
  ...Array.from({ length: 14 }, (_, i) => 'R' + String(i + 1).padStart(2, '0')),
  ...Array.from({ length: 8 }, (_, i) => 'V' + String(i + 1).padStart(2, '0')),
];
const CHANGE_REASON = 'Ajuste acordado con operación tras la muestra etiquetada';

async function openRules(page, role = 'coordinator') {
  await page.goto('/alertas');
  await selectRole(page, role);
  await page.getByRole('tab', { name: 'Reglas y umbrales' }).click();
  await expect(page.getByTestId('rules-table')).toBeVisible();
}

test.describe('Reglas y umbrales', () => {
  test('el catálogo trae R01 a R14 y V01 a V08, con umbral, tratamiento, puntos y versión', async ({ page }) => {
    await openRules(page);
    const table = page.getByTestId('rules-table');
    await expect(table.locator('tbody tr.is-clickable')).toHaveCount(24);
    for (const code of CODES) {
      await expect(page.getByTestId('rule-row-' + code).locator('td').first()).toHaveText(code);
      await expect(page.getByTestId('rule-row-' + code).locator('td').nth(4)).toHaveText('v1');
    }
    await expect(table.locator('tr.rules__group')).toHaveText([
      /Antes de autorizar/,
      /Al conciliar/,
      /Por vehículo/,
    ]);
    await expect(page.getByTestId('rules-version')).toHaveText('v1');
    await expect(page.locator('.rules__footer')).toContainText('Catálogo vigente: v1 · 24 reglas');

    const r05 = page.getByTestId('rule-row-R05').locator('td');
    await expect(r05.nth(1)).toContainText('Recarga sin recorrido');
    await expect(r05.nth(1)).toContainText('Menos de 30 km desde la carga del mismo combustible y 50 % o más de su carga típica');
    await expect(r05.nth(2)).toHaveText('Revisión');
    await expect(r05.nth(3)).toHaveText('3');
    await expect(r05.nth(5)).toContainText('100 %');
    await expect(r05.nth(5)).toContainText('1 de 1');
    const r02 = page.getByTestId('rule-row-R02').locator('td');
    await expect(r02.nth(1)).toContainText('Odómetro con error de digitación');
    await expect(r02.nth(2)).toHaveText('Automática');
    await expect(r02.nth(5)).toHaveText('Sin revisar');
    await expect(page.getByTestId('rule-row-V01').locator('td').nth(1)).toContainText('Menos del 75 % de la mediana de su grupo');
    await expect(page.getByTestId('rule-row-R09').locator('td').nth(1)).toContainText('Entre las 22 y las 4 h sin servicio en ±3 h');

    // La regla R08 queda abierta por defecto, con su historial inicial.
    const detail = page.getByTestId('rule-detail');
    await expect(detail.locator('.rule__name')).toHaveText('Sin servicios en EOM');
    await expect(detail.locator('.rule__text')).toHaveText('Sin servicios con desplazamiento en ±24 h');
    await expect(page.getByTestId('rule-version')).toHaveText('v1');
    await expect(page.getByTestId('param-window_h')).toHaveValue('24');
    await expect(page.getByTestId('rule-points')).toHaveValue('2');
    const history = page.getByTestId('rule-history').locator('li');
    await expect(history).toHaveCount(1);
    await expect(history).toContainText('v1');
    await expect(history).toContainText('Ventana (± horas): 24 · 2 puntos');
    await expect(history).toContainText('Vigente');
    await expect(history).toContainText('Calibración inicial (análisis de 90 días)');
  });

  test('el coordinador cambia un umbral: nace la versión 2 y el historial conserva la 1', async ({ page }) => {
    await openRules(page);
    await page.getByTestId('rule-row-R08').click();
    await expect(page.getByTestId('rules-readonly')).toHaveCount(0);
    const save = page.getByRole('button', { name: 'Guardar como versión 2' });
    await expect(save).toBeEnabled();

    // Sin cambios no hay nada que guardar.
    await save.click();
    await expect(page.getByTestId('rule-error')).toHaveText('Cambia al menos un valor frente a la versión vigente.');

    // Con cambio pero sin motivo.
    await page.getByTestId('param-window_h').fill('12');
    await save.click();
    await expect(page.getByTestId('rule-error')).toHaveText('El motivo del cambio es obligatorio.');
    expect((await api('/rules')).json.rules_version).toBe('v1');

    // Un valor que no es número.
    await page.getByTestId('param-window_h').fill('doce');
    await save.click();
    await expect(page.getByTestId('rule-error')).toHaveText('Revisa los valores: números de 0 en adelante y puntos enteros de 0 a 5.');

    await page.getByTestId('param-window_h').fill('12');
    await page.getByRole('textbox', { name: 'Motivo del cambio' }).fill(CHANGE_REASON);
    await save.click();

    await expect(page.locator('.ui-toast').last()).toContainText('R08 quedó en la versión 2. La anterior se conserva en el historial.');
    await expect(page.getByTestId('rule-version')).toHaveText('v2');
    await expect(page.getByTestId('rules-version')).toHaveText('v2');
    await expect(page.getByTestId('rule-row-R08').locator('td').nth(4)).toHaveText('v2');
    await expect(page.getByTestId('rule-row-R08').locator('td').nth(1)).toContainText('Ventana (± horas): 12');
    await expect(page.getByTestId('rule-row-R09').locator('td').nth(4)).toHaveText('v1');
    await expect(page.getByRole('button', { name: 'Guardar como versión 3' })).toBeVisible();
    await expect(page.getByTestId('param-window_h')).toHaveValue('12');
    await expect(page.getByRole('textbox', { name: 'Motivo del cambio' })).toHaveValue('');

    const history = page.getByTestId('rule-history').locator('li');
    await expect(history).toHaveCount(2);
    await expect(history.nth(0)).toContainText('v2');
    await expect(history.nth(0)).toContainText('Ventana (± horas): 12 · 2 puntos');
    await expect(history.nth(0)).toContainText('Vigente');
    await expect(history.nth(0)).toContainText('Carlos Rivas');
    await expect(history.nth(0)).toContainText(todayText());
    await expect(history.nth(0)).toContainText(CHANGE_REASON);
    await expect(history.nth(1)).toContainText('v1');
    await expect(history.nth(1)).toContainText('Ventana (± horas): 24 · 2 puntos');
    await expect(history.nth(1)).not.toContainText('Vigente');
    await expect(history.nth(1)).toContainText('Calibración inicial (análisis de 90 días)');

    // Persistió en el servidor y sigue ahí al recargar.
    const rule = (await api('/rules')).json.items.find((item) => item.code === 'R08');
    expect(rule.version).toBe(2);
    expect(rule.threshold).toEqual({ window_h: 12 });
    expect(rule.history.map((version) => version.version)).toEqual([2, 1]);
    const audit = (await api('/audit?action=rule.updated')).json.items;
    expect(audit).toHaveLength(1);
    expect(audit[0].actor).toBe('Carlos Rivas');

    await page.reload();
    await page.getByRole('tab', { name: 'Reglas y umbrales' }).click();
    await expect(page.getByTestId('rules-version')).toHaveText('v2');
    await expect(page.getByTestId('rule-history').locator('li')).toHaveCount(2);
  });

  test('cambiar puntos también versiona, y «Deshacer» devuelve el formulario a lo vigente', async ({ page }) => {
    await openRules(page);
    await page.getByTestId('rule-row-R13').click();
    await expect(page.getByTestId('rule-detail').locator('.rule__name')).toHaveText('Transacción de valor mínimo');
    await page.getByTestId('rule-points').fill('4');
    await page.getByTestId('param-amount_cop').fill('5000');
    await page.getByRole('button', { name: 'Deshacer' }).click();
    await expect(page.getByTestId('rule-points')).toHaveValue('1');
    await expect(page.getByTestId('param-amount_cop')).toHaveValue('2000');

    await page.getByTestId('rule-points').fill('9');
    await page.getByRole('textbox', { name: 'Motivo del cambio' }).fill('Prueba de límites de puntos');
    await page.getByRole('button', { name: 'Guardar como versión 2' }).click();
    await expect(page.getByTestId('rule-error')).toHaveText('Revisa los valores: números de 0 en adelante y puntos enteros de 0 a 5.');

    await page.getByTestId('rule-points').fill('2');
    await page.getByRole('button', { name: 'Guardar como versión 2' }).click();
    await expect(page.getByTestId('rule-version')).toHaveText('v2');
    await expect(page.getByTestId('rule-row-R13').locator('td').nth(3)).toHaveText('2');
    await expect(page.getByTestId('rule-history').locator('li').first()).toContainText('Valor mínimo ($): 2.000 · 2 puntos');
  });

  for (const role of ['technician', 'finance', 'support']) {
    test('con el rol ' + role + ' el catálogo es de consulta: formulario deshabilitado con su motivo', async ({ page }) => {
      await openRules(page, role);
      const label = { technician: 'Técnico de Control y Monitoreo', finance: 'Finanzas', support: 'Soporte' }[role];
      await expect(page.getByTestId('rules-readonly')).toHaveText(
        'Solo el Coordinador puede cambiar un umbral. Con el rol ' + label + ' el catálogo es de consulta.',
      );
      await expect(page.getByTestId('param-window_h')).toBeDisabled();
      await expect(page.getByTestId('rule-points')).toBeDisabled();
      await expect(page.getByRole('textbox', { name: 'Motivo del cambio' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Guardar como versión 2' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Deshacer' })).toBeDisabled();
      // Consultar sí puede: la tabla y el historial están completos.
      await expect(page.getByTestId('rules-table').locator('tbody tr.is-clickable')).toHaveCount(24);
      await expect(page.getByTestId('rule-history').locator('li')).toHaveCount(1);

      // La API tampoco lo deja, aunque se salte la pantalla.
      const forbidden = await api('/rules/R08', { method: 'PUT', role, body: { points: 3, reason: 'Prueba de permisos' } });
      expect(forbidden.status).toBe(403);
      expect(forbidden.json.code).toBe('forbidden');
      expect((await api('/rules')).json.rules_version).toBe('v1');
    });
  }

  test('al volver a Coordinador el formulario se habilita sin recargar', async ({ page }) => {
    await openRules(page, 'technician');
    await expect(page.getByRole('button', { name: 'Guardar como versión 2' })).toBeDisabled();
    await selectRole(page, 'coordinator');
    await expect(page.getByTestId('rules-readonly')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Guardar como versión 2' })).toBeEnabled();
    await expect(page.getByTestId('param-window_h')).toBeEnabled();
  });

  test('el umbral nuevo se usa de verdad: con R05 en 10 km el VEH199 ya no la activa', async ({ page }) => {
    await openRules(page);
    await page.getByTestId('rule-row-R05').click();
    await expect(page.getByTestId('param-min_km')).toHaveValue('30');
    await page.getByTestId('param-min_km').fill('10');
    await page.getByRole('textbox', { name: 'Motivo del cambio' }).fill('Prueba: 22 km ya cuenta como recorrido');
    await page.getByRole('button', { name: 'Guardar como versión 2' }).click();
    await expect(page.getByTestId('rules-version')).toHaveText('v2');

    const request = await seedCase('VEH199');
    expect(request.rule_codes).toEqual(['R08', 'R09']);
    expect(request.points).toBe(4);

    await page.goto('/consola/' + request.id);
    await expect(page.locator('[data-rule=R05]')).toHaveCount(0);
    await expect(page.locator('[data-rule=R08]')).toHaveCount(1);
    await expect(page.locator('[data-rule=R09]')).toHaveCount(1);
    await expect(page.getByTestId('reasons-card')).toContainText('4 puntos · reglas v2');
    await expect(page.getByTestId('audit-card').locator('[data-action="request.evaluated"]')).toContainText('reglas v2');
  });

  test('«Reiniciar demo» devuelve las reglas a la versión 1', async ({ page }) => {
    const changed = await api('/rules/R08', {
      method: 'PUT',
      role: 'coordinator',
      body: { threshold: { window_h: 12 }, reason: CHANGE_REASON },
    });
    expect(changed.json.rules_version).toBe('v2');

    await openRules(page);
    await expect(page.getByTestId('rules-version')).toHaveText('v2');
    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Reiniciar demo' }).click();
    await expect(page.getByTestId('rules-version')).toHaveText('v1');
    await expect(page.getByTestId('rule-row-R08').locator('td').nth(4)).toHaveText('v1');
    await expect(page.getByTestId('rule-history').locator('li')).toHaveCount(1);

    // Y el simulador vuelve a ofrecer los casos desde cero.
    const sim = await openSimulator(page);
    await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
  });
});
