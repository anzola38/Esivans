import { COUNTDOWN, TIME, expect, openSimulator, test } from './support/fixtures.mjs';

const TIMELINE_LABELS = ['Recibida', 'Identificada', 'Esperando evidencia', 'Lista', 'En revisión', 'Autorizada'];

/** Assertions shared by the scripted and the hand-typed conversation: the result must be the same. */
async function expectGreenRequestInReview(page, sim) {
  await expect(sim.stage).toHaveText('En revisión');
  for (const status of ['received', 'identified', 'awaiting_evidence', 'ready']) {
    await expect(sim.step(status)).toHaveAttribute('data-state', 'done');
  }
  await expect(sim.step('in_review')).toHaveAttribute('data-state', 'current');
  await expect(sim.step('authorized')).toHaveAttribute('data-state', 'pending');
  await expect(sim.step('in_review')).toContainText('En la cola del técnico de Control y Monitoreo');

  const summary = page.locator('.sim__summary');
  await expect(summary).toContainText('Verde');
  await expect(summary).toContainText('0 puntos');
  await expect(summary).toContainText('Valor sugerido');
  await expect(summary).toContainText('$90.000');

  await expect(sim.pending).toContainText('Lo que falta');
  await expect(sim.pending.locator('li')).toHaveText(['Decisión del técnico de Control y Monitoreo']);
  await expect(sim.pending).toContainText('SLA de 10 minutos: quedan');
  await expect(sim.pending.locator('.sim__sla')).toHaveText(COUNTDOWN);
}

test.describe('Simulador: caso verde (VEH901)', () => {
  test('la ficha del caso muestra conductor, placa, hora simulada y el guion', async ({ page }) => {
    const sim = await openSimulator(page);
    await expect(page.getByTestId('case-GREEN')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('case-GREEN')).toHaveText('VEH901');
    await expect(page.getByTestId('case-driver')).toHaveText('Carlos Andrés Pérez');
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA901');
    await expect(page.getByTestId('case-clock')).toHaveValue('09:40');
    await expect(page.getByTestId('case-clock')).toBeEnabled();
    await expect(page.getByTestId('case-card')).toContainText('VEH901 · Gasolina');
    await expect(page.locator('.sim__script li')).toHaveText([
      /«Hola, necesito tanquear»/,
      /«Sí, es para esa ruta»/,
      /Adjuntar la foto del tablero/,
      /«Sí, es correcto»/,
    ]);
    await expect(page.locator('.sim__next-hint')).toHaveText('Paso 1 de 4: «Hola, necesito tanquear»');

    await expect(sim.chat.locator('.ui-bubble')).toHaveCount(0);
    await expect(page.getByText('Aún no hay solicitud: empieza con el primer mensaje del conductor.')).toBeVisible();
    await expect(page.locator('.sim__tl-label')).toHaveText(TIMELINE_LABELS);
    await expect(page.getByRole('link', { name: 'Ir a la consola del técnico' })).toBeVisible();
  });

  test('con «Siguiente paso del guion» la solicitud avanza de Recibida a En revisión', async ({ page }) => {
    const sim = await openSimulator(page);

    // Paso 1: saludo por nombre, placa y servicio de EOM.
    await sim.nextScriptStep();
    await expect(sim.driverBubbles.first()).toContainText('Hola, necesito tanquear');
    await expect(sim.chat.locator('[data-kind=privacy_notice]')).toContainText('Ley 1581 de 2012');
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText(
      'Hola, Carlos. Soy el asistente de combustible de Esivans. Te tengo con el vehículo de placa ZZA901.',
    );
    await expect(sim.chat.locator('[data-kind=ask_service]')).toContainText(
      'Tu próximo servicio en EOM es a las 10:30 a. m. (Montería → Planeta Rica) y tienes 5 más pendientes hoy. ¿El tanqueo es para esa ruta?',
    );
    await expect(sim.quickReplies.getByRole('button')).toHaveText(['Sí, es para esa ruta', 'Es otro recorrido']);
    await expect(sim.chat.locator('.ui-bubble__time').first()).toHaveText('9:40 a. m.');
    await expect(page.getByTestId('case-clock')).toBeDisabled();
    await expect(sim.step('received')).toHaveAttribute('data-state', 'done');
    await expect(sim.step('received')).toContainText('Primer mensaje del conductor por WhatsApp');
    await expect(sim.step('identified')).toContainText('Conductor Carlos Andrés Pérez y vehículo ZZA901 identificados por el número');
    await expect(sim.step('awaiting_evidence')).toHaveAttribute('data-state', 'current');
    await expect(sim.step('in_review')).toHaveAttribute('data-state', 'pending');
    await expect(sim.stage).toHaveText('Esperando evidencia');
    await expect(sim.pending.locator('li')).toHaveText(['Confirmar el servicio de EOM o el motivo del recorrido']);
    await expect(page.locator('.sim__next-hint')).toHaveText('Paso 2 de 4: «Sí, es para esa ruta»');

    // Paso 2: confirma el servicio y el asistente pide la foto.
    await sim.nextScriptStep();
    await expect(sim.lastAssistantBubble).toContainText(
      'Envíame una foto del tablero donde se vean el kilometraje y el nivel de combustible.',
    );
    await expect(sim.pending.locator('li')).toHaveText(['Foto del tablero (kilometraje y nivel)']);
    await expect(sim.stage).toHaveText('Esperando evidencia');

    // Paso 3: foto y lectura de la IA.
    await sim.nextScriptStep();
    const photo = sim.chat.getByRole('img', { name: 'Foto del tablero enviada' });
    await expect(photo).toHaveCount(1);
    await expect(photo).toHaveAttribute('src', '/api/media/media-veh901');
    await expect.poll(() => photo.evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(sim.lastAssistantBubble).toContainText('Leí en la foto 48.352 km y nivel de ¼ de tanque (25 %). ¿Es correcto?');
    await expect(sim.quickReplies.getByRole('button')).toHaveText(['Sí, es correcto', 'No, corregir']);
    await expect(sim.pending.locator('li')).toHaveText(['Confirmar el kilometraje y el nivel leídos']);

    // Paso 4: confirmación y paso a la cola del técnico.
    await sim.nextScriptStep();
    await expect(sim.lastAssistantBubble).toContainText(
      'Gracias, Carlos. Tu solicitud está en revisión con el técnico de Control y Monitoreo.',
    );
    await expectGreenRequestInReview(page, sim);
    await expect(sim.driverBubbles).toHaveCount(4);
    await expect(sim.quickReplies).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Guion completo' })).toBeDisabled();
    await expect(page.locator('.sim__next-hint')).toHaveText('Continúa en la consola del técnico.');
    for (const time of await sim.chat.locator('.ui-bubble__time').all()) await expect(time).toHaveText(TIME);

    // El enlace lleva al detalle de esa solicitud en la consola.
    await page.getByRole('link', { name: 'Ver en la consola' }).click();
    await expect(page).toHaveURL(/\/consola\/1$/);
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');
    await expect(page.getByTestId('detail-light')).toContainText('Verde');
  });

  test('escribiendo a mano se llega al mismo resultado', async ({ page }) => {
    const sim = await openSimulator(page);
    const send = page.getByRole('button', { name: 'Enviar' });
    await expect(send).toBeDisabled();

    await sim.type('Hola, necesito tanquear');
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('Hola, Carlos.');
    await expect(sim.chat.locator('[data-kind=greeting]')).toContainText('ZZA901');
    await expect(page.getByRole('textbox', { name: 'Mensaje del conductor' })).toHaveValue('');

    // El botón de enviar también funciona, no solo Enter.
    const before = await sim.driverBubbles.count();
    await page.getByRole('textbox', { name: 'Mensaje del conductor' }).fill('Sí, es para esa ruta');
    await expect(send).toBeEnabled();
    await send.click();
    await sim.waitForReply(before + 1);
    await expect(sim.lastAssistantBubble).toContainText('Envíame una foto del tablero');

    await sim.attachPhoto();
    await expect(sim.chat.getByRole('img', { name: 'Foto del tablero enviada' })).toHaveCount(1);
    await expect(sim.lastAssistantBubble).toContainText('48.352 km');
    await expect(sim.lastAssistantBubble).toContainText('¼ de tanque');

    await sim.type('Sí, es correcto');
    await expectGreenRequestInReview(page, sim);
    // El guion se marca como completo aunque no se haya usado el botón.
    await expect(page.getByRole('button', { name: 'Guion completo' })).toBeDisabled();
    await expect(page.getByRole('link', { name: 'Ver en la consola' })).toHaveAttribute('href', '/consola/1');
  });

  test('las respuestas rápidas envían el texto del botón', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.nextScriptStep();
    await sim.quickReply('Sí, es para esa ruta');
    await expect(sim.driverBubbles.last()).toContainText('Sí, es para esa ruta');
    await sim.attachPhoto();
    await sim.quickReply('Sí, es correcto');
    await expectGreenRequestInReview(page, sim);
  });

  test('la conversación sobrevive a una recarga de la página', async ({ page }) => {
    const sim = await openSimulator(page);
    await sim.nextScriptStep();
    await sim.nextScriptStep();
    await page.reload();
    await expect(sim.driverBubbles).toHaveCount(2);
    await expect(sim.lastAssistantBubble).toContainText('Envíame una foto del tablero');
    await expect(sim.stage).toHaveText('Esperando evidencia');
    await expect(page.locator('.sim__next-hint')).toHaveText('Paso 3 de 4: Adjuntar la foto del tablero');
  });
});
