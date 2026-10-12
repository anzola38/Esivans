import { api, decisionEntries, expect, openRequest, seedCase, simulatorOf, test } from './support/fixtures.mjs';

const REASON = 'Sin servicio que respalde la carga';

test.describe('Rechazo con motivo', () => {
  test('rechazar exige motivo y cancelar no decide', async ({ page }) => {
    const request = await seedCase('VEH015');
    await openRequest(page, request.id);

    await page.getByRole('button', { name: 'Rechazar' }).click();
    const dialog = page.getByRole('dialog', { name: 'Rechazar la solicitud' });
    await dialog.getByRole('button', { name: 'Rechazar', exact: true }).click();
    await expect(page.getByTestId('reason-error')).toHaveText('Escribe el motivo (mínimo 5 caracteres): queda en la bitácora.');
    expect(await decisionEntries(request.id)).toHaveLength(0);

    const direct = await api('/requests/' + request.id + '/decision', { method: 'POST', body: { action: 'reject' } });
    expect(direct.status).toBe(422);
    expect(direct.json.code).toBe('reason_required');

    await dialog.getByRole('button', { name: 'Cancelar' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByTestId('detail-stage')).toHaveText('En revisión');
    await expect(page.getByRole('button', { name: 'Rechazar' })).toBeEnabled();
  });

  test('la solicitud queda Rechazada, el conductor recibe el motivo y no se puede decidir de nuevo', async ({ page }) => {
    const request = await seedCase('VEH015');
    await openRequest(page, request.id);

    await page.getByRole('button', { name: 'Rechazar' }).click();
    const dialog = page.getByRole('dialog', { name: 'Rechazar la solicitud' });
    await dialog.getByRole('textbox', { name: 'Motivo' }).fill(REASON);
    await dialog.getByRole('button', { name: 'Rechazar', exact: true }).click();

    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.ui-toast').last()).toContainText('Solicitud rechazada: el conductor recibió el motivo.');
    await expect(page.getByTestId('detail-stage')).toHaveText('Rechazada');
    await expect(page.getByTestId('detail-stage')).toHaveClass(/ui-badge--red/);
    await expect(page.getByTestId('rejection')).toContainText(
      'Rechazada por Laura Mendoza. Motivo: ' + REASON + '. El conductor ya recibió el motivo.',
    );
    await expect(page.getByTestId('detail-sla')).toHaveCount(0);

    // No hay cómo decidir de nuevo ni habilitar.
    await expect(page.getByRole('button', { name: /Aprobar/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Ajustar' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Rechazar' })).toHaveCount(0);
    await expect(page.getByTestId('enablement')).toHaveCount(0);
    await expect(page.getByTestId('authorization')).toHaveCount(0);

    // La API rechaza un segundo intento y dice quién decidió.
    const again = await api('/requests/' + request.id + '/decision', {
      method: 'POST',
      body: { action: 'approve', reason: 'Segundo intento de decisión' },
      role: 'coordinator',
    });
    expect(again.status).toBe(409);
    expect(again.json.code).toBe('already_decided');
    expect(again.json.detail).toContain('ya fue decidida por Laura Mendoza (rechazada)');
    const enable = await api('/requests/' + request.id + '/authorization', {
      method: 'POST',
      body: { reference: 'TER-NO-APLICA' },
    });
    expect(enable.status).toBe(409);
    expect(enable.json.code).toBe('not_approved');
    expect(await decisionEntries(request.id)).toHaveLength(1);

    // Bitácora
    const decision = page.getByTestId('audit-card').locator('[data-action="decision.reject"]');
    await expect(decision).toHaveCount(1);
    await expect(decision.locator('td').nth(1)).toContainText('Laura Mendoza');
    await expect(decision.locator('td').nth(2)).toHaveText('Laura Mendoza rechazó la solicitud. Motivo: ' + REASON);
    await expect(decision.locator('td').nth(4)).toContainText('Acción: Rechazar');

    // Cola
    await page.getByRole('link', { name: 'Volver a la cola' }).click();
    const row = page.getByTestId('queue-row-' + request.id);
    await expect(row.locator('td').nth(3)).toHaveText('Rechazada');
    await expect(row.locator('td').nth(6)).toHaveText('Cerrada');
    await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 0\s*Verde: 0\s*Amarillo: 0\s*Rojo: 0/);

    // El conductor recibe el motivo.
    await row.click();
    await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
    const sim = simulatorOf(page);
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA015');
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'rejection');
    await expect(sim.lastAssistantBubble).toContainText('Jorge, tu solicitud no fue autorizada. Motivo: ' + REASON + '.');
    await expect(sim.stage).toHaveText('Rechazada');
    await expect(sim.step('rejected')).toHaveAttribute('data-state', 'done');
    await expect(sim.step('rejected')).toContainText('Rechazada por Laura Mendoza: ' + REASON);
    await expect(sim.step('authorized')).toHaveCount(0);
    await expect(page.locator('.sim__result')).toHaveText(/Rechazada\.\s*Motivo: Sin servicio que respalde la carga/);
    await expect(page.getByTestId('pending')).toHaveCount(0);
  });
});
