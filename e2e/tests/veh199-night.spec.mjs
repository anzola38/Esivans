import {
  api,
  authorizeViaApi,
  decisionEntries,
  expect,
  openRequest,
  openSimulator,
  referencePrefix,
  seedCase,
  selectRole,
  simulatorOf,
  test,
} from './support/fixtures.mjs';

const REASONS = [
  ['R05', 'Recarga sin recorrido', '+3 puntos', 'cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)'],
  ['R08', 'Sin servicios en EOM', '+2 puntos', 'sin servicios con desplazamiento 24 h antes ni después'],
  ['R09', 'Tanqueo nocturno sin servicio', '+2 puntos', 'tanqueo a las 23:14 sin servicios cercanos'],
];
const ADJUST_REASON = 'Apoyo nocturno confirmado con el coordinador';

test.describe('VEH199 a las 11:14 p. m.: rojo con 7 puntos', () => {
  test('la conversación ocurre a las 11:14 p. m. y termina en Rojo con 7 puntos', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('VEH199');
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA199');
    await expect(page.getByTestId('case-clock')).toHaveValue('23:14');
    await expect(page.locator('.ui-phone__status')).toContainText('11:14 p. m.');

    await sim.nextScriptStep();
    await expect(sim.driverBubbles.first()).toContainText('Necesito tanquear 6,7 m3 de gas');
    await expect(sim.chat.locator('.ui-bubble__time').first()).toHaveText('11:14 p. m.');
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('Hola, Wilson.');
    await expect(sim.lastAssistantBubble).toContainText('No veo servicios tuyos pendientes en EOM.');
    await sim.nextScriptStep();
    await sim.nextScriptStep();
    await expect(sim.lastAssistantBubble).toContainText('Leí en la foto 195.406 km y nivel de ¼ de tanque (25 %).');
    await sim.nextScriptStep();

    await expect(sim.stage).toHaveText('En revisión');
    const summary = page.locator('.sim__summary');
    await expect(summary).toContainText('Rojo');
    await expect(summary).toContainText('7 puntos');
    await expect(summary).toContainText('$10.000');
    await expect(sim.step('received').locator('.sim__tl-time')).toHaveText('11:14 p. m.');
  });

  test('la consola explica R05, R08 y R09, cada una con su razón exacta', async ({ page }) => {
    const request = await seedCase('VEH199');
    await page.goto('/consola');
    const row = page.getByTestId('queue-row-' + request.id);
    await expect(row.locator('td').nth(0)).toHaveText(/^\s*Rojo\s*· 7 puntos\s*R05, R08, R09\s*$/);
    await expect(row.locator('td').nth(0).locator('app-traffic-light')).toHaveClass(/ui-badge--red/);
    await expect(row.locator('td').nth(4)).toHaveText('11:14 p. m.');
    await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 1\s*Verde: 0\s*Amarillo: 0\s*Rojo: 1/);

    await row.click();
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA199');
    await expect(page.getByTestId('detail-light')).toHaveText(/^\s*Rojo\s*· 7 puntos\s*$/);
    await expect(page.getByTestId('detail-amount')).toHaveText('$10.000');
    await expect(page.locator('.det__meta')).toContainText('Pedida a las 11:14 p. m.');
    await expect(page.locator('.det__meta')).toContainText('VEH199 · Gas');

    const reasons = page.getByTestId('reasons-card').locator('.det__reason');
    await expect(reasons).toHaveCount(3);
    for (const [index, [code, name, points, text]] of REASONS.entries()) {
      const reason = reasons.nth(index);
      await expect(reason).toHaveAttribute('data-rule', code);
      await expect(reason.locator('.det__reason-code')).toHaveText(code);
      await expect(reason.locator('.det__reason-name')).toHaveText(name);
      await expect(reason.locator('.det__reason-points')).toHaveText(points);
      await expect(reason.locator('.det__reason-text')).toHaveText(text);
    }
    await expect(page.getByTestId('reasons-card')).toContainText('7 puntos · reglas v1');

    const ledger = page.getByTestId('ledger-card');
    await expect(ledger.locator('.det__fact').nth(0)).toContainText('$9.600 · 3 m³');
    await expect(ledger.locator('.det__fact').nth(1)).toContainText('22 km');
    await expect(ledger.locator('.det__fact').nth(2)).toContainText('Sin servicios hoy');
    await expect(page.getByTestId('vehicle-flags')).toContainText('96 % de sus tanqueos con al menos una alerta');

    const calc = page.getByTestId('calc-card');
    await expect(calc).toContainText('Tope: $40.000');
    await expect(calc.locator('ol.det__calc > li')).toHaveCount(10);
    await expect(calc.locator('ol.det__calc > li').last()).toContainText('$10.000');
    await expect(calc.locator('.det__calc-foot')).toHaveText('El conductor pidió 6,7 m³; el cálculo da 3,5 m³.');

    // Ninguna regla bloquea: el técnico puede aprobar, ajustar o rechazar, pero no en un clic.
    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Aprobar con motivo' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Ajustar' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Rechazar' })).toBeEnabled();
  });

  test('Ajustar exige motivo y respeta el tope del vehículo', async ({ page }) => {
    const request = await seedCase('VEH199');
    await openRequest(page, request.id);

    await page.getByRole('button', { name: 'Ajustar' }).click();
    const dialog = page.getByRole('dialog', { name: 'Ajustar el valor' });
    const amount = dialog.getByRole('spinbutton', { name: 'Valor a autorizar (pesos)' });
    await expect(amount).toHaveValue('10000');
    await expect(dialog).toContainText('Se autoriza $10.000. Sugerido: $10.000. Tope del vehículo: $40.000.');

    // Valor por encima del tope y sin motivo: dos validaciones.
    await amount.fill('500000');
    await dialog.getByRole('button', { name: 'Guardar ajuste' }).click();
    await expect(page.getByTestId('reason-error')).toHaveText('Escribe el motivo (mínimo 5 caracteres): queda en la bitácora.');
    await expect(page.getByTestId('amount-error')).toHaveText('No puede pasar del tope del vehículo ($40.000).');

    await amount.fill('0');
    await expect(page.getByTestId('amount-error')).toHaveText('Escribe un valor mayor que $0.');

    // Valor válido pero todavía sin motivo: no se guarda.
    await amount.fill('20000');
    await expect(page.getByTestId('amount-error')).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Guardar ajuste' }).click();
    await expect(page.getByTestId('reason-error')).toBeVisible();
    await expect(dialog).toBeVisible();
    expect(await decisionEntries(request.id)).toHaveLength(0);

    // La API también lo exige.
    const noReason = await api('/requests/' + request.id + '/decision', {
      method: 'POST',
      body: { action: 'adjust', amount: 20000 },
    });
    expect(noReason.status).toBe(422);
    expect(noReason.json.code).toBe('reason_required');
    const aboveCap = await api('/requests/' + request.id + '/decision', {
      method: 'POST',
      body: { action: 'adjust', amount: 500000, reason: 'Prueba del tope del vehículo' },
    });
    expect(aboveCap.status).toBe(422);
    expect(aboveCap.json.code).toBe('above_cap');
    expect(aboveCap.json.cap_amount).toBe(40000);

    // Cancelar deja la solicitud sin decidir.
    await dialog.getByRole('button', { name: 'Cancelar' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByTestId('detail-stage')).toHaveText('En revisión');
    await expect(page.getByTestId('detail-amount')).toHaveText('$10.000');
  });

  test('al ajustar se conserva el sugerido original en la bitácora y el conductor recibe el motivo', async ({ page }) => {
    const request = await seedCase('VEH199');
    const reference = referencePrefix() + '0001';
    await openRequest(page, request.id);

    await page.getByRole('button', { name: 'Ajustar' }).click();
    const dialog = page.getByRole('dialog', { name: 'Ajustar el valor' });
    await dialog.getByRole('spinbutton', { name: 'Valor a autorizar (pesos)' }).fill('20000');
    await expect(dialog).toContainText('Se autoriza $20.000. Sugerido: $10.000.');
    await dialog.getByRole('button', { name: ADJUST_REASON }).click();
    await dialog.getByRole('button', { name: 'Guardar ajuste' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // Panel de habilitación con el valor ajustado y el sugerido a la vista.
    const enablement = page.getByTestId('enablement');
    await expect(enablement).toContainText('Ajustada por Laura Mendoza (sugerido $10.000).');
    await expect(enablement.locator('.det__field').nth(2)).toHaveText(/^\s*Valor\s*\$20\.000\s*$/);
    await expect(enablement.locator('.det__field').nth(3)).toHaveText(/^\s*Producto\s*GNV\s*$/);
    await expect(page.getByTestId('detail-amount')).toHaveText('$20.000');
    await expect(page.locator('.det__value-label')).toHaveText('Valor autorizado');
    await expect(page.getByRole('textbox', { name: 'Referencia del portal' })).toHaveValue(reference);

    // Bitácora: el antes guarda el sugerido y el después el valor y el motivo.
    const decision = page.getByTestId('audit-card').locator('[data-action="decision.adjust"]');
    await expect(decision.locator('td').nth(1)).toContainText('Laura Mendoza');
    await expect(decision.locator('td').nth(2)).toHaveText(
      'Laura Mendoza ajustó la solicitud por $20.000 (sugerido $10.000). Motivo: ' + ADJUST_REASON,
    );
    await expect(decision.locator('td').nth(3)).toContainText('Valor sugerido: $10.000');
    await expect(decision.locator('td').nth(3)).toContainText('Semáforo: Rojo');
    await expect(decision.locator('td').nth(3)).toContainText('Puntos: 7');
    await expect(decision.locator('td').nth(4)).toContainText('Acción: Ajustar');
    await expect(decision.locator('td').nth(4)).toContainText('Valor: $20.000');
    await expect(decision.locator('td').nth(4)).toContainText('Motivo: ' + ADJUST_REASON);

    // El cálculo original sigue en pantalla y en la API.
    await expect(page.getByTestId('calc-card').locator('ol.det__calc > li').last()).toContainText('$10.000');
    const detail = (await api('/requests/' + request.id)).json;
    expect(detail.decision).toMatchObject({ action: 'adjust', amount: 20000, original_amount: 10000, reason: ADJUST_REASON });
    expect(detail.decision.original_calculation.amount).toBe(10000);
    expect(detail.suggested_amount).toBe(10000);

    // Habilitar
    await enablement.getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
    const authorization = page.getByTestId('authorization');
    await expect(authorization).toContainText('Autorizada: $20.000 de GNV.');
    await expect(authorization).toContainText('Referencia ' + reference);
    await expect(authorization).toContainText('Valor sugerido original: $10.000');
    await expect(authorization).toContainText('Motivo: ' + ADJUST_REASON);
    await expect(authorization).toContainText('hasta las 1:1');

    // Mensaje al conductor, con el motivo del ajuste.
    await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
    const sim = simulatorOf(page);
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA199');
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'authorization');
    await expect(sim.lastAssistantBubble).toContainText('Autorizado, Wilson: $20.000 de GNV. Referencia: ' + reference + '.');
    await expect(sim.lastAssistantBubble).toContainText('Vigencia: 2 horas (hasta las 1:1');
    await expect(sim.lastAssistantBubble).toContainText('El técnico ajustó el valor. Motivo: ' + ADJUST_REASON + '.');
    await expect(sim.stage).toHaveText('Autorizada');
    await expect(page.locator('.sim__summary')).toContainText('$20.000');
  });

  test('ya autorizado en rojo, el coordinador ve la alerta C03 con su razón y el plazo de 48 horas', async ({ page }) => {
    const request = await seedCase('VEH199');
    await openRequest(page, request.id);
    await expect(page.getByTestId('red-review-note')).toHaveText(
      'Por estar en rojo, esta autorización pasará a revisión del coordinador (plazo de 48 horas).',
    );
    expect((await api('/alerts')).json.items.filter((a) => a.rule_code === 'C03')).toHaveLength(0);

    await authorizeViaApi(request.id, { action: 'adjust', amount: 20000, reason: ADJUST_REASON });
    await page.reload();
    await expect(page.getByTestId('authorization')).toContainText('Autorizada: $20.000 de GNV.');
    await expect(page.getByTestId('red-review-note')).toHaveText(
      'Por estar en rojo, esta autorización pasó a revisión del coordinador (plazo de 48 horas).',
    );
    await expect(page.getByTestId('audit-card').locator('[data-action="alert.created"]')).toContainText(
      'Por estar en rojo, la autorización pasó a revisión del coordinador: alerta C03 de prioridad alta (plazo de 48 horas)',
    );

    await page.goto('/alertas');
    await selectRole(page, 'coordinator');
    await page.getByRole('tab', { name: 'Tanqueos con alerta' }).click();
    const row = page.getByTestId('alert-list').locator('.item[data-vehicle=VEH199][data-rules=C03]');
    await expect(row).toHaveCount(1);
    await row.click();
    const detail = page.getByTestId('alert-detail');
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH199');
    await expect(page.getByTestId('alert-priority')).toHaveText('Prioridad alta');
    await expect(page.getByTestId('alert-deadline')).toContainText('Plazo: 48 horas.');
    await expect(page.getByTestId('alert-reasons').locator('.reason__name')).toHaveText('Autorización de solicitud en rojo');
    await expect(page.getByTestId('alert-reasons').locator('.reason__text')).toHaveText(
      'El técnico Laura Mendoza autorizó $20.000 a VEH199 con el semáforo en rojo (7 puntos: R05, R08, R09). Motivo: "' +
        ADJUST_REASON +
        '". Valor sugerido: $10.000.',
    );
    await expect(page.getByTestId('alert-request')).toContainText('Valor autorizado');
    await expect(detail.locator('.tx-grid')).toHaveCount(1);
    await expect(page.getByTestId('review-save')).toBeEnabled();
  });
});
