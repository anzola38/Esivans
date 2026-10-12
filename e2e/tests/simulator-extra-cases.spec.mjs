import { api, expect, openSimulator, seedCase, test } from './support/fixtures.mjs';

test.describe('Simulador: casos extra', () => {
  test('los cinco casos están disponibles como chips', async ({ page }) => {
    await openSimulator(page);
    await expect(page.getByRole('tablist', { name: 'Casos' }).getByRole('tab')).toHaveText([
      'VEH901',
      'VEH015',
      'VEH199',
      'VEH902',
      'Sin registro',
    ]);
  });

  test('número no registrado: pasa al técnico con el motivo', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('UNREGISTERED');
    await expect(page.getByTestId('case-plate')).toHaveText('—');
    await expect(page.getByTestId('case-clock')).toHaveValue('08:15');
    await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Adjuntar la foto de ejemplo del tablero' })).toBeDisabled();

    await sim.nextScriptStep();
    await expect(sim.driverBubbles.first()).toContainText('Buenos días, necesito tanquear la van');
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'handoff');
    await expect(sim.lastAssistantBubble).toContainText(
      'No encuentro este número entre los conductores registrados. Ya pasé tu caso al técnico de Control y Monitoreo, que te escribe por este mismo chat. Ten a la mano la placa del vehículo.',
    );
    await expect(sim.chat.locator('[data-kind=greeting]')).toHaveCount(0);

    await expect(sim.stage).toHaveText('En revisión');
    await expect(sim.step('in_review')).toHaveAttribute('data-state', 'current');
    await expect(sim.step('in_review')).toContainText('Número no registrado: pasa al técnico para identificar al conductor');
    await expect(sim.pending.locator('li')).toHaveText([
      'Llegó sin: conductor no identificado',
      'Decisión del técnico de Control y Monitoreo',
    ]);
    await expect(page.locator('.sim__summary')).toContainText('Amarillo');

    // En la cola y en el detalle el técnico ve por qué llegó.
    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page.getByTestId('detail-plate')).toHaveText('Sin placa');
    await expect(page.getByTestId('detail-light')).toContainText('Amarillo');
    await expect(page.locator('.det__meta')).toContainText('Número no registrado (573009990000)');
    await expect(page.getByText('Pasó al técnico incompleta. Faltó: conductor no identificado.')).toBeVisible();
    const reason = page.getByTestId('reasons-card').locator('.det__reason');
    await expect(reason).toHaveCount(1);
    await expect(reason.locator('.det__reason-code')).toHaveText('Dato');
    await expect(reason.locator('.det__reason-name')).toHaveText('Número no registrado');
    await expect(reason.locator('.det__reason-points')).toHaveText('Inconsistencia');
    await expect(reason.locator('.det__reason-text')).toHaveText(
      'El número de WhatsApp no corresponde a un conductor con asignación vigente; el técnico identifica al conductor y decide.',
    );
    await expect(page.getByTestId('evidence-card')).toContainText('Sin foto del tablero');
    await expect(page.getByTestId('calc-card')).toContainText('Sin vehículo identificado: el técnico define el valor.');
    await expect(page.getByTestId('detail-amount')).toHaveText('—');
    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toHaveCount(0);

    await page.getByRole('link', { name: 'Volver a la cola' }).click();
    const row = page.getByTestId('queue-table').locator('tbody tr');
    await expect(row).toHaveCount(1);
    await expect(row.locator('td').nth(1)).toContainText('Sin placa');
    await expect(row.locator('td').nth(1)).toContainText('Vehículo sin identificar');
    await expect(row.locator('td').nth(2)).toContainText('Número no registrado');
    await expect(row.locator('td').nth(2)).toContainText('573009990000');
    await expect(row.locator('td').nth(3)).toContainText('Llegó sin: conductor no identificado');
    await expect(row.locator('td').nth(4)).toHaveText('8:15 a. m.');
  });

  test('el vehículo que no necesita tanquear se cierra sin pasar por el técnico', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('NO_FUEL');
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA902');
    await expect(page.getByTestId('case-clock')).toHaveValue('11:05');

    await sim.nextScriptStep();
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('Hola, Luis.');
    // Un solo servicio adicional: el asistente lo dice en singular.
    await expect(sim.chat.locator('[data-kind=ask_service]')).toContainText(
      'Tu próximo servicio en EOM es a las 12:00 p. m. (Planeta Rica → Sahagún) y tienes 1 más pendiente hoy. ¿El tanqueo es para esa ruta?',
    );
    await sim.nextScriptStep();
    await sim.nextScriptStep();
    await expect(sim.lastAssistantBubble).toContainText('Leí en la foto 61.512 km y nivel de ⅞ de tanque (88 %).');
    await sim.nextScriptStep();

    // El asistente explica que no hace falta y ofrece dos salidas.
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'not_needed');
    await expect(sim.lastAssistantBubble).toContainText(
      'Luis, con el nivel que leí (10,50 gal) te alcanza para tu ruta pendiente y la reserva de ½ tanque: por ahora no necesitas tanquear',
    );
    await expect(sim.quickReplies.getByRole('button')).toHaveText(['Entendido, gracias', 'Que lo revise el técnico']);
    await expect(sim.pending.locator('li')).toHaveText(['Confirmar que no necesita tanquear ahora']);

    await sim.nextScriptStep();
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'closed');
    await expect(sim.lastAssistantBubble).toContainText('Cuando bajes de ½ tanque me escribes y lo gestionamos de una.');
    await expect(sim.stage).toHaveText('Cerrada sin tanqueo');
    await expect(sim.step('cancelled')).toHaveAttribute('data-state', 'done');
    await expect(sim.step('cancelled')).toContainText('No necesita tanquear ahora; el conductor quedó informado');
    await expect(sim.step('in_review')).toHaveAttribute('data-state', 'skipped');
    await expect(sim.step('in_review')).toContainText('No aplica');
    await expect(page.locator('.sim__result')).toHaveText('Cerrada sin tanqueo: el vehículo no necesita cargar ahora.');
    await expect(page.locator('.sim__summary')).toContainText('$0');
    await expect(page.getByTestId('pending')).toHaveCount(0);

    // No llega a la cola de pendientes del técnico, pero queda registrada.
    const queue = (await api('/requests')).json;
    expect(queue.counts.in_review).toBe(0);
    expect(queue.items).toHaveLength(1);
    expect(queue.items[0].status).toBe('cancelled');

    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA902');
    await expect(page.getByTestId('detail-stage')).toHaveText('Cerrada sin tanqueo');
    await expect(page.getByText('Cerrada sin tanqueo: el vehículo no necesita cargar ahora y el conductor lo aceptó.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Aprobar/ })).toHaveCount(0);
    const steps = page.getByTestId('calc-card').locator('ol.det__calc > li');
    await expect(steps).toHaveCount(7);
    await expect(steps.nth(5)).toContainText('A cargar');
    await expect(steps.nth(5)).toContainText('-3,65 gal');
    await expect(steps.nth(6)).toContainText('A cargar es 0 o menos: no necesita tanquear ahora');
    await expect(steps.nth(6)).toContainText('$0');
  });

  test('cerrada sin tanqueo: las razones del detalle no dicen que el conductor pidió revisión', async ({ page }) => {
    test.fail(
      true,
      'Bug conocido del backend (requests/service.py): la razón "No necesita tanquear según el cálculo" se guarda al evaluar, ' +
        'antes de que el conductor responda, y siempre termina en "el conductor pidió que lo revise el técnico", ' +
        'aunque haya aceptado. No se corrige aquí porque exige reevaluar o reescribir la razón guardada.',
    );
    await seedCase('NO_FUEL');
    const request = (await api('/requests')).json.items[0];
    expect(request.status).toBe('cancelled');
    await page.goto('/consola/' + request.id);
    await expect(page.getByText('el conductor lo aceptó')).toBeVisible();
    await expect(page.getByTestId('reasons-card')).toContainText('No necesita tanquear según el cálculo');
    await expect(page.getByTestId('reasons-card')).not.toContainText('el conductor pidió que lo revise el técnico', { timeout: 2000 });
  });

  test('si el conductor insiste, la solicitud que no necesita tanquear pasa al técnico', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('NO_FUEL');
    for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
    await sim.quickReply('Que lo revise el técnico');

    await expect(sim.stage).toHaveText('En revisión');
    await expect(sim.step('in_review')).toHaveAttribute('data-state', 'current');
    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page.getByTestId('detail-light')).toContainText('Amarillo');
    await expect(page.getByTestId('reasons-card')).toContainText('No necesita tanquear según el cálculo');
    await expect(page.getByTestId('reasons-card')).toContainText('el conductor pidió que lo revise el técnico');
    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Rechazar' })).toBeEnabled();
  });

  test('cambiar de caso conserva cada conversación por separado', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.nextScriptStep();
    await expect(sim.driverBubbles).toHaveCount(1);

    await sim.selectCase('VEH199');
    await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
    await expect(page.getByTestId('case-clock')).toBeEnabled();
    await expect(page.getByText('Aún no hay solicitud: empieza con el primer mensaje del conductor.')).toBeVisible();

    await sim.selectCase('GREEN');
    await expect(sim.driverBubbles).toHaveCount(1);
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('Hola, Carlos.');
    await expect(page.getByTestId('case-clock')).toBeDisabled();
  });

  test('el reloj simulado decide si aplica R09: el VEH199 a las 2:00 p. m. no la activa', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.selectCase('VEH199');
    await page.getByTestId('case-clock').fill('14:00');
    await expect(page.locator('.ui-phone__status')).toContainText('2:00 p. m.');
    for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
    await expect(sim.chat.locator('.ui-bubble__time').first()).toHaveText('2:00 p. m.');
    await expect(sim.stage).toHaveText('En revisión');

    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page.locator('.det__meta')).toContainText('Pedida a las 2:00 p. m.');
    await expect(page.locator('[data-rule=R05]')).toHaveCount(1);
    await expect(page.locator('[data-rule=R08]')).toHaveCount(1);
    await expect(page.locator('[data-rule=R09]')).toHaveCount(0);
    await expect(page.getByTestId('detail-light')).toContainText('5 puntos');
  });
});
