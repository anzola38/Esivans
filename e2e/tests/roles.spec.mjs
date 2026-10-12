import { ROLES, api, decisionEntries, expect, openRequest, seedCase, selectRole, test } from './support/fixtures.mjs';

const READ_ONLY_CONSOLE = (label) =>
  'Solo lectura: con el rol ' +
  label +
  ' puedes consultar la solicitud, pero la decisión y la habilitación son del técnico de Control y Monitoreo o del coordinador.';

test.describe('Roles: consola del técnico', () => {
  for (const role of ['support', 'finance']) {
    test(ROLES[role].label + ' ve la solicitud en solo lectura, sin poder decidir', async ({ page }) => {
      const request = await seedCase('GREEN');
      await page.goto('/consola');
      await selectRole(page, role);

      // La cola se puede consultar.
      await expect(page.getByTestId('queue-row-' + request.id)).toContainText('ZZA901');
      await page.getByTestId('queue-row-' + request.id).click();
      await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');

      await expect(page.getByTestId('read-only')).toHaveText(READ_ONLY_CONSOLE(ROLES[role].label));
      await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Ajustar' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Rechazar' })).toBeDisabled();

      // Lo demás sigue a la vista: evidencia, cálculo y bitácora.
      await expect(page.getByTestId('odometer')).toHaveText('48.352 km');
      await expect(page.getByTestId('calc-card').locator('ol.det__calc > li')).toHaveCount(10);
      await expect(page.getByTestId('audit-card').locator('tbody tr')).toHaveCount(3);

      // La API responde 403 y deja el intento en la bitácora.
      const forbidden = await api('/requests/' + request.id + '/decision', { method: 'POST', role, body: { action: 'approve' } });
      expect(forbidden.status).toBe(403);
      expect(forbidden.json.code).toBe('forbidden');
      expect(forbidden.json.allowed_roles).toEqual(expect.arrayContaining(['technician', 'coordinator']));
      expect(await decisionEntries(request.id)).toHaveLength(0);
      const denied = (await api('/audit?action=access.denied')).json.items;
      expect(denied).toHaveLength(1);
      expect(denied[0].actor).toBe(ROLES[role].user);
    });
  }

  test('soporte tampoco puede confirmar una habilitación pendiente', async ({ page }) => {
    const request = await seedCase('GREEN');
    const decided = await api('/requests/' + request.id + '/decision', { method: 'POST', body: { action: 'approve' } });
    expect(decided.status).toBe(200);

    await openRequest(page, request.id);
    await selectRole(page, 'support');
    await expect(page.getByTestId('read-only')).toBeVisible();
    await expect(page.getByTestId('enablement')).toContainText('$90.000');
    await expect(page.getByRole('textbox', { name: 'Referencia del portal' })).toBeDisabled();
    await expect(page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' })).toBeDisabled();

    const forbidden = await api('/requests/' + request.id + '/authorization', {
      method: 'POST',
      role: 'support',
      body: { reference: 'TER-SIN-PERMISO' },
    });
    expect(forbidden.status).toBe(403);
    expect((await api('/requests/' + request.id)).json.authorization).toBeNull();
  });

  test('el coordinador sí puede decidir y la bitácora lo registra con su nombre', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);
    await selectRole(page, 'coordinator');
    await expect(page.getByTestId('read-only')).toHaveCount(0);
    await page.getByRole('button', { name: 'Aprobar en un clic' }).click();
    await expect(page.getByTestId('enablement')).toContainText('Aprobada por Carlos Rivas');
    const decision = page.getByTestId('audit-card').locator('[data-action="decision.approve"]');
    await expect(decision.locator('td').nth(1)).toHaveText(/^\s*Carlos Rivas\s*Coordinador\s*$/);
  });

  test('al volver a Técnico las acciones se habilitan sin recargar', async ({ page }) => {
    const request = await seedCase('VEH199');
    await openRequest(page, request.id);
    await selectRole(page, 'support');
    await expect(page.getByRole('button', { name: 'Ajustar' })).toBeDisabled();
    await selectRole(page, 'technician');
    await expect(page.getByTestId('read-only')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Aprobar con motivo' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Ajustar' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Rechazar' })).toBeEnabled();
  });
});

test.describe('Roles: alertas y conciliación', () => {
  test('solo el coordinador registra el resultado de una alerta', async ({ page }) => {
    await page.goto('/alertas');
    await page.getByRole('tab', { name: 'Vehículos' }).click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH129');
    const review = page.getByTestId('review');

    for (const role of ['technician', 'finance', 'support']) {
      await selectRole(page, role);
      await expect(page.getByTestId('review-readonly')).toHaveText(
        'Con el rol ' + ROLES[role].label + ' solo puedes consultar. El resultado lo registra el Coordinador.',
      );
      for (const option of await review.getByRole('radio').all()) await expect(option).toBeDisabled();
      await expect(review.getByRole('textbox', { name: 'Comentario' })).toBeDisabled();
      await expect(review.getByRole('button', { name: 'Registrar resultado' })).toBeDisabled();
      // La evidencia y el libro único sí se consultan.
      await expect(page.getByTestId('alert-points')).toHaveText('8 puntos');
      await expect(page.getByTestId('ledger').locator('tbody tr')).toHaveCount(8);
    }

    await selectRole(page, 'coordinator');
    await expect(page.getByTestId('review-readonly')).toHaveCount(0);
    await expect(review.getByRole('radio', { name: 'Confirmado' })).toBeEnabled();
    await expect(review.getByRole('button', { name: 'Registrar resultado' })).toBeEnabled();

    // Finanzas y soporte tampoco pueden por la API.
    const alert = (await api('/alerts?kind=vehicle')).json.items[0];
    for (const role of ['finance', 'support']) {
      const forbidden = await api('/alerts/' + alert.id, {
        method: 'PATCH',
        role,
        body: { review_result: 'confirmed', comment: 'Intento sin permiso' },
      });
      expect(forbidden.status, role).toBe(403);
    }
    expect((await api('/alerts?kind=vehicle')).json.items[0].status).toBe('open');
  });

  test('un resultado ya registrado no se puede corregir sin ser coordinador', async ({ page }) => {
    await page.goto('/alertas');
    await selectRole(page, 'finance');
    await page.getByTestId('filter-reviewed').click();
    await expect(page.getByTestId('review-closed')).toBeVisible();
    await expect(page.getByTestId('review').getByRole('button', { name: 'Corregir' })).toHaveCount(0);
    await selectRole(page, 'coordinator');
    await expect(page.getByTestId('review').getByRole('button', { name: 'Corregir' })).toBeVisible();
  });

  test('el archivo del proveedor lo cargan coordinador y finanzas; técnico y soporte solo consultan', async ({ page }) => {
    await page.goto('/alertas');
    await page.getByRole('tab', { name: 'Conciliación' }).click();
    const load = page.getByRole('button', { name: 'Cargar exporte de ejemplo de Terpel' });

    for (const role of ['technician', 'support']) {
      await selectRole(page, role);
      await expect(load).toBeDisabled();
      await expect(page.getByTestId('import-readonly')).toHaveText(
        'Con el rol ' + ROLES[role].label + ' solo puedes consultar. El archivo lo carga Coordinador o Finanzas.',
      );
    }
    const forbidden = await api('/integrations/terpel/imports', {
      method: 'POST',
      role: 'support',
      body: { filename: 'terpel_ejemplo.csv', content: 'external_id\n' },
    });
    expect(forbidden.status).toBe(403);

    await selectRole(page, 'coordinator');
    await expect(load).toBeEnabled();
    await expect(page.getByTestId('import-readonly')).toHaveCount(0);

    // Finanzas carga el archivo y ve el resultado.
    await selectRole(page, 'finance');
    await expect(load).toBeEnabled();
    await load.click();
    await expect(page.getByTestId('import-imported')).toHaveText('10');
    await expect(page.getByTestId('overpaid-amount')).toHaveText('$27.783');
    const audit = (await api('/audit?action=import.executed')).json.items;
    expect(audit).toHaveLength(1);
    expect(audit[0].actor).toBe('Marta Salcedo');
  });

  test('todos los roles ven el tablero completo', async ({ page }) => {
    await page.goto('/tablero');
    for (const role of ['coordinator', 'finance', 'support', 'technician']) {
      await selectRole(page, role);
      await expect(page.getByTestId('indicators').locator('.kpi')).toHaveCount(9);
      await expect(page.getByTestId('verdict-label')).toHaveText('Ampliar');
    }
  });
});
