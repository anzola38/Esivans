import {
  api,
  decisionEntries,
  expect,
  openRequest,
  openSimulator,
  resetDemo,
  seedCase,
  simulatorOf,
  test,
} from './support/fixtures.mjs';

/** Runs the green case end to end through the interface and returns what the presenter saw. */
async function runGreenCase(page) {
  const sim = await openSimulator(page);
  await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
  for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
  await expect(sim.stage).toHaveText('En revisión');
  const chatInReview = await sim.chat.locator('.ui-bubble').allTextContents();

  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');
  const requestId = Number(page.url().split('/').pop());
  const seen = {
    requestId,
    light: (await page.getByTestId('detail-light').textContent()).replace(/\s+/g, ' ').trim(),
    amount: await page.getByTestId('detail-amount').textContent(),
    odometer: await page.getByTestId('odometer').textContent(),
    steps: await page.getByTestId('calc-card').locator('ol.det__calc > li').allTextContents(),
    chatInReview,
  };

  await page.getByRole('button', { name: 'Aprobar en un clic' }).click();
  seen.reference = await page.getByRole('textbox', { name: 'Referencia del portal' }).inputValue();
  await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
  seen.auditSummaries = await page.getByTestId('audit-card').locator('tbody tr td:nth-child(3)').allTextContents();

  await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
  const after = simulatorOf(page);
  await expect(after.lastAssistantBubble).toHaveAttribute('data-kind', 'authorization');
  // The validity hour moves with the wall clock (case time + elapsed): keep everything but the minute.
  seen.finalMessage = (await after.lastAssistantBubble.locator('span').first().textContent()).replace(
    /hasta las \d{1,2}:\d{2}/,
    'hasta las HH:MM',
  );
  seen.stage = await after.stage.textContent();
  seen.queue = (await api('/requests')).json.counts;
  return seen;
}

test.describe('Robustez de la demo', () => {
  test('el caso verde da exactamente el mismo resultado dos veces seguidas, con reinicio entre ambas', async ({ page }) => {
    test.setTimeout(120_000);
    const first = await runGreenCase(page);

    await resetDemo();
    expect((await api('/requests')).json.items).toHaveLength(0);
    const second = await runGreenCase(page);

    expect(second).toEqual(first);
    // Y el resultado es el del guion, no solo "igual las dos veces".
    expect(first.requestId).toBe(1);
    expect(first.light).toMatch(/^Verde\s*· 0 puntos$/);
    expect(first.amount.trim()).toBe('$90.000');
    expect(first.odometer.trim()).toBe('48.352 km');
    expect(first.steps).toHaveLength(10);
    expect(first.reference).toMatch(/^TER-\d{6}-0001$/);
    expect(first.finalMessage).toContain('Autorizado, Carlos: $90.000 de Gasolina Corriente. Referencia: ' + first.reference);
    expect(first.stage.trim()).toBe('Autorizada');
    expect(first.auditSummaries).toHaveLength(5);
    expect(first.queue).toMatchObject({ total: 1, in_review: 0 });
  });

  test('reiniciar con el botón, a mitad de un caso, deja repetirlo desde cero', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.nextScriptStep();
    await sim.nextScriptStep();

    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Reiniciar demo' }).click();
    await expect(page.locator('.ui-toast')).toContainText('Demo reiniciada');
    await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
    await expect(page.getByTestId('case-clock')).toBeEnabled();
    await expect(page.locator('.sim__next-hint')).toHaveText('Paso 1 de 4: «Hola, necesito tanquear»');

    for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
    await expect(sim.stage).toHaveText('En revisión');
    await expect(page.locator('.sim__summary')).toContainText('N.º 1');
    await expect(page.locator('.sim__summary')).toContainText('$90.000');
    expect((await api('/requests')).json.items).toHaveLength(1);
  });

  test('doble clic rápido en «Aprobar en un clic» registra una sola decisión', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);
    const posts = [];
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/decision')) posts.push(r.url());
    });

    await page.getByRole('button', { name: 'Aprobar en un clic' }).dblclick();

    await expect(page.getByTestId('enablement')).toContainText('Aprobada por Laura Mendoza');
    await expect(page.getByTestId('detail-stage')).toHaveText('Por habilitar');
    await expect(page.locator('.ui-toast--error')).toHaveCount(0);
    expect(posts).toHaveLength(1);
    const decisions = await decisionEntries(request.id);
    expect(decisions).toHaveLength(1);
    expect(decisions[0].after).toMatchObject({ action: 'approve', amount: 90000, one_click: true });
    await expect(page.getByTestId('audit-card').locator('[data-action="decision.approve"]')).toHaveCount(1);
  });

  test('dos clics en el mismo instante sobre «Aprobar en un clic» tampoco duplican la decisión', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);
    const posts = [];
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/decision')) posts.push(r.url());
    });

    // Two click events in the same task: the interface gets no chance to repaint in between.
    await page.getByRole('button', { name: 'Aprobar en un clic' }).evaluate((button) => {
      button.click();
      button.click();
    });

    await expect(page.getByTestId('enablement')).toContainText('Aprobada por Laura Mendoza');
    await expect(page.locator('.ui-toast--error')).toHaveCount(0);
    expect(posts).toHaveLength(1);
    expect(await decisionEntries(request.id)).toHaveLength(1);
  });

  test('doble clic en «Confirmar» habilita una sola vez', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);
    await page.getByRole('button', { name: 'Aprobar en un clic' }).click();
    await expect(page.getByTestId('enablement')).toBeVisible();

    await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).dblclick();

    await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
    await expect(page.locator('.ui-toast--error')).toHaveCount(0);
    const enabled = (await api('/audit?request_id=' + request.id + '&action=authorization')).json.items;
    expect(enabled).toHaveLength(1);
    const messages = (await api('/dev/simulator/conversations/573005550901')).json.messages;
    expect(messages.filter((message) => message.kind === 'authorization')).toHaveLength(1);
  });

  test('doble clic en «Siguiente paso del guion» envía un solo mensaje', async ({ page }) => {
    const sim = await openSimulator(page);
    await page.getByRole('button', { name: 'Siguiente paso del guion' }).dblclick();
    await sim.waitForReply(1);
    await expect(sim.chat.locator('[data-kind=ask_service]')).toHaveCount(1);
    await expect(page.locator('.sim__next-hint')).toHaveText('Paso 2 de 4: «Sí, es para esa ruta»');
    const messages = (await api('/dev/simulator/conversations/573005550901')).json.messages;
    expect(messages.filter((message) => message.direction === 'inbound')).toHaveLength(1);
  });

  test('doble clic en «Registrar resultado» deja una sola revisión en la bitácora', async ({ page }) => {
    await page.goto('/alertas');
    await page.getByRole('combobox', { name: 'Rol' }).selectOption('coordinator');
    await page.getByRole('tab', { name: 'Vehículos' }).click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH129');
    await page.getByTestId('review').getByRole('radio', { name: 'Confirmado' }).click();
    await page.getByTestId('review').getByRole('button', { name: 'Registrar resultado' }).dblclick();
    await expect(page.getByTestId('review-result')).toHaveText('Confirmado');
    expect((await api('/audit?action=alert.reviewed')).json.items).toHaveLength(1);
  });

  test('dos pestañas a la vez: la segunda ve que la solicitud ya fue decidida', async ({ page, context, guard }) => {
    const request = await seedCase('VEH015');
    await openRequest(page, request.id);
    const other = await context.newPage();
    await other.goto('/consola/' + request.id);
    await expect(other.getByRole('button', { name: 'Rechazar' })).toBeEnabled();

    // La primera pestaña rechaza.
    await page.getByRole('button', { name: 'Rechazar' }).click();
    await page.getByRole('textbox', { name: 'Motivo' }).fill('Sin servicio que respalde la carga');
    await page.getByRole('dialog').getByRole('button', { name: 'Rechazar', exact: true }).click();
    await expect(page.getByTestId('detail-stage')).toHaveText('Rechazada');

    // La segunda se actualiza sola y retira las acciones.
    await expect(other.getByTestId('detail-stage')).toHaveText('Rechazada');
    await expect(other.getByRole('button', { name: /Aprobar/ })).toHaveCount(0);
    await expect(other.getByTestId('rejection')).toContainText('Rechazada por Laura Mendoza');
    expect(await decisionEntries(request.id)).toHaveLength(1);
    expect(guard.problems()).toEqual([]);
    await other.close();
  });
});
