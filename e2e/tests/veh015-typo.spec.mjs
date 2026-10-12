import { api, decisionEntries, expect, openRequest, openSimulator, seedCase, test } from './support/fixtures.mjs';

const REASON_REQUIRED = 'Escribe el motivo (mínimo 5 caracteres): queda en la bitácora.';

test.describe('VEH015: error de digitación en el kilometraje (R02)', () => {
  test('el asistente lee 24.086, propone 34.086 y pide confirmar', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('VEH015');
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA015');
    await expect(page.getByTestId('case-clock')).toHaveValue('14:20');
    await expect(page.locator('.sim__case-desc')).toContainText('La lectura da 24.086 km y su último registro es 33.948.');

    await sim.nextScriptStep();
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('Hola, Jorge.');
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('ZZA015');
    await expect(sim.chat.locator('.ui-bubble__time').first()).toHaveText('2:20 p. m.');
    await expect(sim.lastAssistantBubble).toContainText('No veo servicios tuyos pendientes en EOM.');
    await sim.nextScriptStep();
    await sim.nextScriptStep();

    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'confirm_correction');
    await expect(sim.lastAssistantBubble).toContainText(
      'En la foto leí 24.086 km y nivel de ¼ de tanque (25 %). Tu último registro es de 33.948 km, así que parece un error de un dígito (el 3 quedó como 2). ¿El kilometraje correcto es 34.086 km?',
    );
    await expect(sim.quickReplies.getByRole('button')).toHaveText(['Sí, es 34.086', 'No, corregir']);
    // Todavía no hay semáforo: falta la confirmación del conductor.
    await expect(sim.stage).toHaveText('Esperando evidencia');
    await expect(sim.pending.locator('li')).toHaveText(['Confirmar el kilometraje y el nivel leídos']);

    await sim.quickReply('Sí, es 34.086');
    await expect(sim.stage).toHaveText('En revisión');
    const summary = page.locator('.sim__summary');
    await expect(summary).toContainText('Amarillo');
    await expect(summary).toContainText('1 punto');
    await expect(summary).toContainText('$50.000');

    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA015');
    await expect(page.getByTestId('odometer')).toHaveText('34.086 km');
  });

  test('llega a la consola en Amarillo con R02 y 1 punto, sin aprobación en un clic', async ({ page }) => {
    const request = await seedCase('VEH015');
    await page.goto('/consola');
    const row = page.getByTestId('queue-row-' + request.id);
    await expect(row.locator('td').nth(0)).toHaveText(/^\s*Amarillo\s*· 1 punto\s*R02\s*$/);
    await expect(row.locator('td').nth(0).locator('app-traffic-light')).toHaveClass(/ui-badge--yellow/);
    await expect(row.locator('td').nth(4)).toHaveText('2:20 p. m.');
    await expect(row.locator('td').nth(7)).toContainText('$50.000');
    await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 1\s*Verde: 0\s*Amarillo: 1\s*Rojo: 0/);

    await row.getByRole('link', { name: 'Revisar' }).click();
    await expect(page.getByTestId('detail-light')).toHaveText(/^\s*Amarillo\s*· 1 punto\s*$/);
    await expect(page.getByTestId('detail-amount')).toHaveText('$50.000');

    const reason = page.locator('[data-rule=R02]');
    await expect(page.getByTestId('reasons-card').locator('.det__reason')).toHaveCount(1);
    await expect(reason.locator('.det__reason-code')).toHaveText('R02');
    await expect(reason.locator('.det__reason-name')).toHaveText('Odómetro con error de digitación');
    await expect(reason.locator('.det__reason-points')).toHaveText('+1 punto');
    await expect(reason.locator('.det__reason-text')).toHaveText(
      'leyó 24.086 km (dígito cambiado); última lectura válida: 33.948 km; valor corregido: 34.086 km',
    );
    await expect(page.getByTestId('reasons-card')).toContainText('1 punto · reglas v1');
    await expect(page.getByTestId('no-alerts')).toHaveCount(0);

    await expect(page.getByTestId('odometer')).toHaveText('34.086 km');
    await expect(page.getByTestId('odometer-correction')).toHaveText(
      'La foto se leyó como 24.086 km (dígito cambiado); corregido a 34.086 km.',
    );
    await expect(page.getByTestId('evidence-card')).toContainText('Confianza 78 %');
    const flags = page.getByTestId('vehicle-flags');
    await expect(flags).toContainText('V01');
    await expect(flags).toContainText('Rinde 26,3 km/gal-eq frente a la mediana de su grupo, 52,7 (50 % menos); el límite es 39,5');
    await expect(flags).toContainText('V05');
    await expect(page.getByTestId('ledger-card')).toContainText('El vehículo no aparece en EOM');
    await expect(page.getByTestId('ledger-card')).toContainText('Motivo dado: «Traslado no programado»');

    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Aprobar con motivo' })).toBeEnabled();
  });

  test('aprobar sin motivo muestra la validación y no decide; con motivo pasa', async ({ page }) => {
    const request = await seedCase('VEH015');
    await openRequest(page, request.id);

    await page.getByRole('button', { name: 'Aprobar con motivo' }).click();
    const dialog = page.getByRole('dialog', { name: 'Aprobar con motivo' });
    await expect(dialog).toContainText('Amarillo');
    await expect(dialog).toContainText('ZZA015 · valor sugerido $50.000');
    await expect(page.getByTestId('reason-error')).toHaveCount(0);

    // Sin motivo
    await dialog.getByRole('button', { name: 'Aprobar', exact: true }).click();
    await expect(page.getByTestId('reason-error')).toHaveText(REASON_REQUIRED);
    await expect(dialog).toBeVisible();
    // Un motivo de relleno tampoco pasa.
    await dialog.getByRole('textbox', { name: 'Motivo' }).fill('ok');
    await dialog.getByRole('button', { name: 'Aprobar', exact: true }).click();
    await expect(page.getByTestId('reason-error')).toHaveText(REASON_REQUIRED);
    expect(await decisionEntries(request.id)).toHaveLength(0);
    expect((await api('/requests/' + request.id)).json.decision).toBeNull();

    // La API también lo exige, no solo la pantalla.
    const direct = await api('/requests/' + request.id + '/decision', { method: 'POST', body: { action: 'approve' } });
    expect(direct.status).toBe(422);
    expect(direct.json.code).toBe('reason_required');
    expect(direct.json.detail).toBe('El semáforo no está en verde: para autorizar debes dejar el motivo.');

    // Con motivo (sugerencia de un clic)
    await dialog.getByRole('button', { name: 'Kilometraje corregido y confirmado por el conductor' }).click();
    await expect(dialog.getByRole('textbox', { name: 'Motivo' })).toHaveValue('Kilometraje corregido y confirmado por el conductor');
    await dialog.getByRole('button', { name: 'Aprobar', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    const enablement = page.getByTestId('enablement');
    await expect(enablement).toContainText('Aprobada por Laura Mendoza');
    await expect(enablement).toContainText('$50.000');
    await expect(enablement).toContainText('ZZA015');
    await expect(page.getByTestId('detail-stage')).toHaveText('Por habilitar');

    const decision = page.getByTestId('audit-card').locator('[data-action="decision.approve"]');
    await expect(decision.locator('td').nth(2)).toContainText('Laura Mendoza aprobó la solicitud por $50.000');
    await expect(decision.locator('td').nth(2)).toContainText('Kilometraje corregido y confirmado por el conductor');
    await expect(decision.locator('td').nth(3)).toContainText('Semáforo: Amarillo');
    await expect(decision.locator('td').nth(4)).toContainText('Motivo: Kilometraje corregido y confirmado por el conductor');
    await expect(decision.locator('td').nth(4)).toContainText('En un clic: No');

    const entries = await decisionEntries(request.id);
    expect(entries).toHaveLength(1);
    expect(entries[0].after).toMatchObject({ action: 'approve', amount: 50000, one_click: false });

    await enablement.getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
    await expect(page.getByTestId('authorization')).toContainText('Autorizada: $50.000 de Gasolina Corriente.');
    await expect(page.getByTestId('authorization')).toContainText('Motivo: Kilometraje corregido y confirmado por el conductor');
  });
});
