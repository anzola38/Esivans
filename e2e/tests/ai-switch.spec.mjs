import {
  CASES,
  api,
  expect,
  expectNoHorizontalOverflow,
  openRequest,
  openSimulator,
  seedCase,
  test,
} from './support/fixtures.mjs';

// The suite runs with the simulated AI pinned (see resetDemo): nothing here sends a message while
// a Groq mode is active, so no test calls the real service.

const GROQ_OPTION = {
  key: 'groq',
  label: 'Groq',
  available: true,
  unavailable_reason: null,
  text_model: 'openai/gpt-oss-120b',
  vision_model: 'qwen/qwen3.8-27b',
};
// Mixed mode: Groq for the text; the photo is not sent and the sample reading is used.
const GROQ_TEXT_OPTION = {
  key: 'groq_text',
  label: 'Groq (texto)',
  available: true,
  unavailable_reason: null,
  text_model: 'openai/gpt-oss-120b',
  vision_model: null,
};
const MOCK_OPTION = {
  key: 'mock',
  label: 'Simulada',
  available: true,
  unavailable_reason: null,
  text_model: null,
  vision_model: null,
};

function aiState(active, groq = {}) {
  return {
    active,
    active_label: { groq: 'Groq', groq_text: 'Groq (texto)', mock: 'Simulada' }[active],
    configured: 'mock',
    pinned: false,
    options: [{ ...GROQ_OPTION, ...groq }, { ...GROQ_TEXT_OPTION, ...groq }, MOCK_OPTION],
  };
}

const MIXED_NOTE = 'Groq: gpt-oss-120b (mensajes). La foto no se envía: lectura de ejemplo.';
const MIXED_PHOTO = 'simulada (lectura de ejemplo; la foto no se envió a Groq)';

test.describe('Conmutador de IA del simulador', () => {
  test('muestra la IA activa y quién interpretó cada mensaje y leyó la foto', async ({ page }) => {
    const sim = await openSimulator(page);
    const control = page.getByTestId('ai-switch');
    await expect(control).toBeVisible();
    await expect(control.getByRole('button')).toHaveText(['Groq', 'Groq (texto)', 'Simulada']);
    await expect(page.getByTestId('ai-option-mock')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-option-groq')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-option-groq_text')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-note')).toHaveText('Intérprete local y lecturas de ejemplo, sin internet.');
    await expect(page.getByTestId('ai-source')).toHaveCount(0);

    await sim.nextScriptStep();
    await expect(page.getByTestId('ai-source')).toHaveText(['IA: simulada (intérprete local)']);
    await sim.nextScriptStep();
    await expect(page.getByTestId('ai-source')).toHaveText(['IA: simulada (intérprete local)']); // only the last message
    await sim.nextScriptStep();
    await expect(page.getByTestId('ai-source')).toHaveText(['IA: simulada (lectura de ejemplo)']);
    await sim.nextScriptStep();
    // The photo keeps its source; the last message shows who interpreted it.
    await expect(page.getByTestId('ai-source')).toHaveText([
      'IA: simulada (lectura de ejemplo)',
      'IA: simulada (intérprete local)',
    ]);

    const request = (await api('/dev/simulator/conversations/' + CASES.GREEN.waId)).json.request;
    await openRequest(page, request.id);
    const evidence = page.getByTestId('evidence-card');
    await expect(evidence).toContainText('Leído por la IA');
    await expect(evidence.getByTestId('evidence-origin')).toHaveText('Leído por la IA');
    await expect(evidence.getByTestId('ai-source')).toHaveText('IA: simulada (lectura de ejemplo).');
  });

  test('las tres opciones explican qué hacen y caben en la ficha del caso', async ({ page }) => {
    await page.route('**/api/dev/ai', (route) => route.fulfill({ json: aiState('mock') }));
    await openSimulator(page);
    const control = page.getByTestId('ai-switch');
    await expect(control).toHaveAttribute('role', 'group');
    await expect(page.getByRole('group', { name: 'IA' }).getByRole('button')).toHaveCount(3);
    await expect(page.getByTestId('ai-option-groq')).toHaveAttribute(
      'title',
      'Groq interpreta los mensajes y lee la foto del tablero.',
    );
    await expect(page.getByTestId('ai-option-groq_text')).toHaveAttribute(
      'title',
      'Groq interpreta los mensajes. La foto no se envía a Groq: usa la lectura de ejemplo.',
    );
    await expect(page.getByTestId('ai-option-mock')).toHaveAttribute(
      'title',
      'Intérprete local y lecturas de ejemplo, sin internet.',
    );

    // The three buttons stay on one line, inside the case card, and nothing scrolls sideways.
    const row = await control.locator('xpath=ancestor::dl[1]').boundingBox();
    const box = await control.boundingBox();
    const tops = await control
      .getByRole('button')
      .evaluateAll((buttons) => buttons.map((button) => Math.round(button.getBoundingClientRect().top)));
    expect(new Set(tops).size, 'las tres opciones en una sola línea').toBe(1);
    expect(box.x).toBeGreaterThanOrEqual(row.x);
    expect(box.x + box.width).toBeLessThanOrEqual(row.x + row.width + 0.5);
    const clipped = await control.evaluate((element) => element.scrollWidth > element.clientWidth);
    expect(clipped, 'el conmutador no recorta sus opciones').toBe(false);
    await expectNoHorizontalOverflow(page, 'simulador con tres opciones de IA');
  });

  test('sin clave configurada, Groq aparece deshabilitado con su explicación', async ({ page }) => {
    const reason = 'Falta GROQ_API_KEY en el archivo .env: sin la clave solo funciona la IA simulada.';
    await page.route('**/api/dev/ai', (route) =>
      route.fulfill({ json: aiState('mock', { available: false, unavailable_reason: reason }) }),
    );
    await openSimulator(page);
    const groq = page.getByTestId('ai-option-groq');
    await expect(groq).toBeDisabled();
    await expect(groq).toHaveAttribute('title', reason);
    await expect(groq).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-option-mock')).toBeEnabled();
    await expect(page.getByTestId('ai-option-mock')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-note')).toHaveText('Groq deshabilitado. ' + reason);
    const mixed = page.getByTestId('ai-option-groq_text');
    await expect(mixed).toBeDisabled();
    await expect(mixed).toHaveAttribute('title', reason);
    await expect(mixed).toHaveAttribute('aria-pressed', 'false');
  });

  test('cambia a Groq (texto), a Groq y a Simulada enviando al backend el modo elegido', async ({ page }) => {
    // The backend is replaced here: no mode of Groq is really activated.
    let active = 'mock';
    const sent = [];
    await page.route('**/api/dev/ai', async (route) => {
      const request = route.request();
      if (request.method() === 'PUT') {
        sent.push(request.postDataJSON());
        active = request.postDataJSON().provider;
      }
      await route.fulfill({ json: aiState(active) });
    });
    await openSimulator(page);
    const groq = page.getByTestId('ai-option-groq');
    const mixed = page.getByTestId('ai-option-groq_text');
    const mock = page.getByTestId('ai-option-mock');
    await expect(mixed).toBeEnabled();
    await expect(mixed).toHaveText('Groq (texto)');

    await mixed.click();
    await expect(mixed).toHaveAttribute('aria-pressed', 'true');
    await expect(groq).toHaveAttribute('aria-pressed', 'false');
    await expect(mock).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-note')).toHaveText(MIXED_NOTE);

    await groq.click();
    await expect(groq).toHaveAttribute('aria-pressed', 'true');
    await expect(mixed).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-note')).toHaveText('Groq: gpt-oss-120b (mensajes) y qwen3.8-27b (foto).');

    await mixed.click();
    await expect(mixed).toHaveAttribute('aria-pressed', 'true');
    await mixed.click(); // already active: nothing is sent
    await mock.click();
    await expect(mock).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-note')).toHaveText('Intérprete local y lecturas de ejemplo, sin internet.');
    expect(sent).toEqual([
      { provider: 'groq_text' },
      { provider: 'groq' },
      { provider: 'groq_text' },
      { provider: 'mock' },
    ]);
  });

  test('en Groq (texto) la foto se rotula como lectura de ejemplo y el texto como Groq', async ({ page }) => {
    // The case runs with the simulated AI; only what the backend records in the mixed mode is put on
    // top of its answers, so nothing is sent to Groq.
    const request = await seedCase('GREEN');
    const photoSource = { kind: 'vision', provider: 'mock', model: null, status: 'ok', mode: 'groq_text' };
    await page.route('**/api/dev/ai', (route) => route.fulfill({ json: aiState('groq_text') }));
    await page.route('**/api/dev/simulator/conversations/' + CASES.GREEN.waId, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      for (const message of body.messages.filter((item) => item.direction === 'inbound')) {
        message.ai =
          message.type === 'image'
            ? { kind: 'vision', provider: 'mock', model: null, status: 'ok', label: MIXED_PHOTO }
            : { kind: 'text', provider: 'groq', model: 'openai/gpt-oss-120b', status: 'ok', label: 'Groq · gpt-oss-120b' };
      }
      await route.fulfill({ response, json: body });
    });
    await page.route('**/api/requests/' + request.id, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.evidence.ai_source = photoSource;
      body.evidence.ai_source_label = MIXED_PHOTO;
      await route.fulfill({ response, json: body });
    });

    await openSimulator(page);
    await expect(page.getByTestId('ai-option-groq_text')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-note')).toHaveText(MIXED_NOTE);
    await expect(page.getByTestId('ai-source')).toHaveText(['IA: ' + MIXED_PHOTO, 'IA: Groq · gpt-oss-120b']);
    await expect(page.getByTestId('ai-source').first()).not.toContainText('Groq ·');
    await expectNoHorizontalOverflow(page, 'simulador en Groq (texto)');

    await openRequest(page, request.id);
    const evidence = page.getByTestId('evidence-card');
    await expect(evidence.getByTestId('evidence-origin')).toHaveText('Lectura de ejemplo');
    await expect(evidence).not.toContainText('Leído por la IA');
    await expect(evidence.getByTestId('ai-source')).toHaveText('IA: ' + MIXED_PHOTO + '.');
    await expect(page.getByTestId('odometer')).toHaveText('48.352 km');
    await expectNoHorizontalOverflow(page, 'detalle en Groq (texto)');
  });

  test('cambia a Groq y vuelve a Simulada mostrando el estado que responde el backend', async ({ page }) => {
    // The backend is replaced here: the control is exercised without activating the real provider.
    let active = 'mock';
    const sent = [];
    await page.route('**/api/dev/ai', async (route) => {
      const request = route.request();
      if (request.method() === 'PUT') {
        sent.push(request.postDataJSON());
        active = request.postDataJSON().provider;
      }
      await route.fulfill({ json: aiState(active) });
    });
    await openSimulator(page);
    const groq = page.getByTestId('ai-option-groq');
    const mock = page.getByTestId('ai-option-mock');
    await expect(groq).toBeEnabled();
    await expect(mock).toHaveAttribute('aria-pressed', 'true');

    await groq.click();
    await expect(groq).toHaveAttribute('aria-pressed', 'true');
    await expect(mock).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('ai-note')).toHaveText('Groq: gpt-oss-120b (mensajes) y qwen3.8-27b (foto).');

    await mock.click();
    await expect(mock).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-note')).toHaveText('Intérprete local y lecturas de ejemplo, sin internet.');
    expect(sent).toEqual([{ provider: 'groq' }, { provider: 'mock' }]);

    await mock.click(); // already active: nothing is sent
    expect(sent).toHaveLength(2);
  });

  test('el cambio llega al backend sin reiniciar y «Reiniciar demo» vuelve al proveedor configurado', async ({ page }) => {
    const initial = (await api('/dev/ai')).json;
    test.skip(!initial.options[0].available, 'Este equipo no tiene GROQ_API_KEY: el cambio real a Groq no aplica.');
    expect(initial.active).toBe('mock');

    await openSimulator(page);
    await page.getByTestId('ai-option-groq').click();
    await expect(page.getByTestId('ai-option-groq')).toHaveAttribute('aria-pressed', 'true');
    let state = (await api('/dev/ai')).json;
    expect([state.active, state.pinned]).toEqual(['groq', false]);
    expect((await api('/health')).json.ai_provider).toBe('groq');

    await page.getByTestId('ai-option-mock').click();
    await expect(page.getByTestId('ai-option-mock')).toHaveAttribute('aria-pressed', 'true');
    state = (await api('/dev/ai')).json;
    expect(state.active).toBe('mock');
    expect((await api('/health')).json.ai_provider).toBe('mock');

    // The switch of the presenter is not pinned: the reset gives back what AI_PROVIDER says.
    // Groq is left selected (no message is sent) so the reset has something to give back, and the test
    // waits for the reset itself: the control alone could already show the expected option.
    await page.getByTestId('ai-option-groq').click();
    await expect(page.getByTestId('ai-option-groq')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('reset-demo').click();
    const resetDone = page.waitForResponse(
      (response) => response.url().endsWith('/api/dev/reset') && response.request().method() === 'POST',
    );
    await page.getByTestId('reset-demo-confirm').click();
    expect((await resetDone).status()).toBe(200);
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('ai-option-' + initial.configured)).toHaveAttribute('aria-pressed', 'true');
    state = (await api('/dev/ai')).json;
    expect(state.active).toBe(initial.configured);
    expect(JSON.stringify(state)).not.toMatch(/gsk_/);
  });

  test('Groq (texto) llega al backend sin reiniciar y «Reiniciar demo» vuelve al proveedor configurado', async ({ page }) => {
    const initial = (await api('/dev/ai')).json;
    expect(initial.options.map((option) => option.key)).toEqual(['groq', 'groq_text', 'mock']);
    const mixedOption = initial.options[1];
    expect([mixedOption.label, mixedOption.vision_model]).toEqual(['Groq (texto)', null]);
    test.skip(!mixedOption.available, 'Este equipo no tiene GROQ_API_KEY: el cambio real a Groq (texto) no aplica.');
    expect(initial.active).toBe('mock');

    // No message is sent while the mixed mode is active: nothing reaches Groq.
    await openSimulator(page);
    const mixed = page.getByTestId('ai-option-groq_text');
    await mixed.click();
    await expect(mixed).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-note')).toHaveText(MIXED_NOTE);
    let state = (await api('/dev/ai')).json;
    expect([state.active, state.active_label, state.pinned]).toEqual(['groq_text', 'Groq (texto)', false]);
    const health = (await api('/health')).json;
    expect(health.ai_provider).toBe('groq_text');
    expect([health.ai.text_model, health.ai.vision_model]).toEqual([mixedOption.text_model, null]);
    const entry = (await api('/audit?action=demo.ai_provider')).json.items[0];
    expect(entry.summary).toContain('cambió la IA de la demo a Groq (texto)');
    expect(entry.after).toEqual({ provider: 'groq_text' });

    await page.getByTestId('reset-demo').click();
    const resetDone = page.waitForResponse(
      (response) => response.url().endsWith('/api/dev/reset') && response.request().method() === 'POST',
    );
    await page.getByTestId('reset-demo-confirm').click();
    expect((await resetDone).status()).toBe(200);
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('ai-option-' + initial.configured)).toHaveAttribute('aria-pressed', 'true');
    state = (await api('/dev/ai')).json;
    expect(state.active).toBe(initial.configured);
    expect(JSON.stringify(state)).not.toMatch(/gsk_/);
  });
});
