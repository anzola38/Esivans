import { api, authorizeViaApi, expect, referencePrefix, seedCase, selectRole, test } from './support/fixtures.mjs';

async function openReconciliation(page) {
  await page.goto('/alertas');
  await selectRole(page, 'coordinator');
  await page.getByRole('tab', { name: 'Conciliación' }).click();
  await expect(page.getByRole('button', { name: 'Cargar exporte de ejemplo de Terpel' })).toBeEnabled();
}

async function loadSample(page) {
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/integrations/terpel/imports')),
    page.getByRole('button', { name: 'Cargar exporte de ejemplo de Terpel' }).click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(page.getByTestId('import-summary')).toBeVisible();
  return response.json();
}

async function expectSummary(page, { rows, imported, duplicates, rejected, alerts }) {
  await expect(page.getByTestId('import-rows')).toHaveText(String(rows));
  await expect(page.getByTestId('import-imported')).toHaveText(String(imported));
  await expect(page.getByTestId('import-duplicates')).toHaveText(String(duplicates));
  await expect(page.getByTestId('import-rejected')).toHaveText(String(rejected));
  await expect(page.getByTestId('import-alerts')).toHaveText(String(alerts));
}

test.describe('Conciliación con el archivo del proveedor', () => {
  test('antes de cargar no hay resumen ni desviaciones', async ({ page }) => {
    await openReconciliation(page);
    await expect(page.getByText('Aún no se ha cargado el archivo de hoy')).toBeVisible();
    await expect(page.getByText('Sin desviaciones todavía')).toBeVisible();
    await expect(page.getByTestId('import-summary')).toHaveCount(0);
    await expect(page.getByTestId('overpaid-card')).toHaveCount(0);
  });

  test('cargar el exporte de ejemplo: resumen de filas y alerta del VEH023', async ({ page }) => {
    await openReconciliation(page);
    await loadSample(page);

    await expectSummary(page, { rows: 10, imported: 10, duplicates: 0, rejected: 0, alerts: 5 });
    await expect(page.locator('.import__message')).toHaveText(
      '10 transacciones nuevas en el libro único, 0 duplicadas sin cargar, 0 rechazadas y 5 alertas.',
    );
    await expect(page.locator('.ui-toast').last()).toContainText('Archivo de Terpel cargado');

    // Filas del archivo, una por una.
    const lines = page.getByTestId('import-lines').locator('tbody tr');
    await expect(lines).toHaveCount(10);
    await expect(lines.filter({ hasText: 'Cargada' })).toHaveCount(10);
    const veh023 = lines.filter({ hasText: 'VEH023' });
    await expect(veh023).toHaveCount(1);
    await expect(veh023).toContainText('TER-900102');
    await expect(veh023).toContainText('C01');
    await expect(lines.filter({ hasText: 'Sin alerta' })).toHaveCount(5);
    await expect(page.getByTestId('matched')).toHaveCount(0);

    // VEH023: cargó Extra cuando su ficha pide Corriente.
    const card = page.getByTestId('overpaid-card');
    await expect(page.getByTestId('overpaid-vehicle')).toHaveText('VEH023');
    await expect(card.locator('.hero__head')).toContainText('ZZA023');
    await expect(card.locator('.hero__head')).toContainText('C01');
    await expect(page.getByTestId('overpaid-amount')).toHaveText('$27.783');
    await expect(card.locator('.hero__label')).toHaveText('pagados de más');
    await expect(card.locator('.price--bad')).toHaveText(/Cargó\s*Gasolina Extra\s*\$21\.250 por galón/);
    await expect(card.locator('.price--good')).toHaveText(/Su ficha pide\s*Gasolina Corriente\s*\$16\.330 por galón/);
    await expect(page.getByTestId('overpaid-math')).toContainText('5,647 galones × $4.920 de diferencia = $27.783.');
    await expect(page.getByTestId('overpaid-math')).toContainText('Precio de la Corriente: misma estación, mismo día.');
    await expect(page.getByTestId('overpaid-math')).toContainText('EDS Montería Centro');
    await expect(card).toContainText('Plazo: en la semana · sin revisar');

    // Las otras cuatro desviaciones del archivo.
    const others = page.getByTestId('deviations').locator('.dev');
    await expect(others).toHaveCount(4);
    for (const [vehicle, code] of [['VEH907', 'R13'], ['VEH918', 'R11'], ['VEH912', 'R12'], ['VEH904', 'R14']]) {
      await expect(others.filter({ hasText: vehicle })).toContainText(code);
    }

    // El resumen de alertas sube en 5 y la pestaña muestra su contador.
    await expect(page.getByTestId('alerts-summary')).toContainText('Abiertas: 16');
    await expect(page.getByRole('tab', { name: 'Conciliación' })).toContainText('5');

    // «Revisar la alerta» abre el detalle del VEH023 con el tanqueo del archivo en el libro único.
    await card.getByRole('button', { name: 'Revisar la alerta' }).click();
    await expect(page.getByRole('tab', { name: 'Tanqueos con alerta' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH023');
    const overpaid = page.getByTestId('alert-overpaid');
    await expect(overpaid.locator('.overpaid__value')).toHaveText('$27.783');
    await expect(overpaid).toContainText('Cargó Gasolina Extra a $21.250 por galón; su ficha pide Gasolina Corriente, que estaba a $16.330');
    await expect(overpaid).toContainText('$4.920 de diferencia × 5,647 galones.');
    await expect(page.getByTestId('alert-reasons')).toContainText('C01');
    const fileRow = page.getByTestId('ledger').locator('tbody tr.is-selected');
    await expect(fileRow).toHaveCount(1);
    await expect(fileRow).toContainText('Archivo');
    await expect(fileRow).toContainText('Gasolina Extra');
    await expect(fileRow).toContainText('5,647 gal');
    await expect(fileRow).toContainText('$119.999');
  });

  test('una segunda carga del mismo archivo no duplica nada', async ({ page }) => {
    await openReconciliation(page);
    await loadSample(page);
    await expectSummary(page, { rows: 10, imported: 10, duplicates: 0, rejected: 0, alerts: 5 });
    const alertsBefore = (await api('/alerts', { role: 'coordinator' })).json.counts.total;
    const ledgerBefore = (await api('/vehicles/VEH023/ledger')).json.entries.length;

    await loadSample(page);
    await expectSummary(page, { rows: 10, imported: 0, duplicates: 10, rejected: 0, alerts: 0 });
    await expect(page.locator('.import__message')).toHaveText(
      '0 transacciones nuevas en el libro único, 10 duplicadas sin cargar, 0 rechazadas y 0 alertas.',
    );
    const lines = page.getByTestId('import-lines').locator('tbody tr');
    await expect(lines).toHaveCount(10);
    await expect(lines.filter({ hasText: 'Duplicada' })).toHaveCount(10);
    await expect(lines.filter({ hasText: 'Cargada' })).toHaveCount(0);

    // Ni alertas ni movimientos nuevos; el VEH023 sigue una sola vez.
    await expect(page.getByTestId('overpaid-amount')).toHaveText('$27.783');
    await expect(page.getByTestId('deviations').locator('.dev')).toHaveCount(4);
    await expect(page.getByTestId('alerts-summary')).toContainText('Abiertas: 16');
    expect((await api('/alerts', { role: 'coordinator' })).json.counts.total).toBe(alertsBefore);
    expect(alertsBefore).toBe(24);
    expect((await api('/vehicles/VEH023/ledger')).json.entries.length).toBe(ledgerBefore);
  });

  test('las autorizaciones de la demo se concilian con lo que registró el proveedor', async ({ page }) => {
    const request = await seedCase('GREEN');
    await authorizeViaApi(request.id);
    const reference = referencePrefix() + '0001';

    await openReconciliation(page);
    await loadSample(page);
    await expectSummary(page, { rows: 11, imported: 11, duplicates: 0, rejected: 0, alerts: 5 });

    const matched = page.getByTestId('matched').locator('tbody tr');
    await expect(matched).toHaveCount(1);
    await expect(matched.locator('td')).toHaveText(['VEH901', reference, '$90.000', '$90.000', 'Cuadra']);

    // La autorización queda conciliada y el tablero lo refleja.
    expect((await api('/requests/' + request.id)).json.authorization.reconciled).toBe(true);
    const dashboard = (await api('/dashboard')).json;
    const reconciliation = dashboard.indicators.find((indicator) => indicator.key === 'reconciliation');
    expect(reconciliation.current_value).toBe(1);
    expect(reconciliation.status).toBe('met');
  });

  test('el resumen de la carga sigue visible al ir a otra pestaña y volver', async ({ page }) => {
    await openReconciliation(page);
    await loadSample(page);
    await page.getByRole('tab', { name: 'Vehículos' }).click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH129');
    await page.getByRole('tab', { name: 'Conciliación' }).click();
    await expectSummary(page, { rows: 10, imported: 10, duplicates: 0, rejected: 0, alerts: 5 });
    await expect(page.getByTestId('overpaid-vehicle')).toHaveText('VEH023');
  });
});
