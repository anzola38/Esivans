import { CASES, api, expect, openRequest, openSimulator, test } from './support/fixtures.mjs';

// The suite runs with the simulated AI pinned (see resetDemo): nothing here sends a message while
// Groq is active, so no test calls the real service.

const GROQ_OPTION = {
  key: 'groq',
  label: 'Groq',
  available: true,
  unavailable_reason: null,
  text_model: 'openai/gpt-oss-120b',
  vision_model: 'qwen/qwen3.8-27b',
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
    active_label: active === 'groq' ? 'Groq' : 'Simulada',
    configured: 'mock',
    pinned: false,
    options: [{ ...GROQ_OPTION, ...groq }, MOCK_OPTION],
  };
}

test.describe('Conmutador de IA del simulador', () => {
  test('muestra la IA activa y quién interpretó cada mensaje y leyó la foto', async ({ page }) => {
    const sim = await openSimulator(page);
    const control = page.getByTestId('ai-switch');
    await expect(control).toBeVisible();
    await expect(control.getByRole('button')).toHaveText(['Groq', 'Simulada']);
    await expect(page.getByTestId('ai-option-mock')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('ai-option-groq')).toHaveAttribute('aria-pressed', 'false');
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
    await expect(evidence.getByTestId('ai-source')).toHaveText('IA: simulada (lectura de ejemplo).');
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
});
