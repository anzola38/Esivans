import { expect, seedCase, test } from './support/fixtures.mjs';

// States the demo cannot reach by itself in a test run (a breached 10-minute SLA, the "Detener"
// outcome of the pilot). The real response of the API is fetched and only the fields named in each
// test are changed, so the rest of the screen still renders real data.

/** Rewrites the JSON of every response whose path is exactly `path`. */
async function rewrite(page, path, change) {
  await page.route(
    (url) => url.pathname === path,
    async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      change(body);
      await route.fulfill({ response, json: body });
    },
  );
}

/**
 * The mm:ss shown keeps moving between two refreshes of the screen. The mocked response always says
 * `from` seconds, so every poll restarts the count there: the text must show at least two different
 * values, none below `from`.
 */
async function expectTicking(locator, from) {
  const seen = new Set();
  await expect
    .poll(
      async () => {
        const match = /(\d{2}):(\d{2})/.exec((await locator.textContent()) ?? '');
        if (match) seen.add(Number(match[1]) * 60 + Number(match[2]));
        return seen.size;
      },
      { message: 'el contador cambia segundo a segundo', intervals: [250] },
    )
    .toBeGreaterThan(1);
  expect(Math.min(...seen)).toBeGreaterThanOrEqual(from);
  expect(Math.max(...seen)).toBeLessThan(from + 15);
}

test.describe('Consola: SLA de 10 minutos vencido', () => {
  test('la cola marca «Vencido hace mm:ss» y el contador sigue subiendo', async ({ page }) => {
    const request = await seedCase('GREEN');
    await rewrite(page, '/api/requests', (body) => {
      for (const item of body.items) {
        item.sla_remaining_seconds = -75;
        item.sla_breached = true;
      }
      body.counts.sla_breached = body.items.length;
    });

    await page.goto('/consola');
    const sla = page.getByTestId('queue-row-' + request.id).locator('td').nth(6);
    await expect(sla.locator('.queue__sla')).toHaveClass(/is-late/);
    await expect(sla).toHaveText(/^\s*Vencido hace 01:(1[5-9]|[2-5]\d)\s*$/);
    await expectTicking(sla, 75);
    // Vencida no bloquea: la solicitud se sigue pudiendo abrir y decidir.
    await expect(page.getByTestId('queue-row-' + request.id).getByRole('link', { name: 'Revisar' })).toBeVisible();
  });

  test('con 2 minutos de margen el SLA todavía cuenta hacia atrás y avisa con color', async ({ page }) => {
    const request = await seedCase('GREEN');
    await rewrite(page, '/api/requests', (body) => {
      for (const item of body.items) item.sla_remaining_seconds = 120;
    });

    await page.goto('/consola');
    const sla = page.getByTestId('queue-row-' + request.id).locator('td').nth(6);
    await expect(sla).toHaveText(/^\s*0[01]:[0-5]\d\s*$/);
    await expect(sla.locator('.queue__sla')).toHaveClass(/is-warn/);
    await expect(sla.locator('.queue__sla')).not.toHaveClass(/is-late/);
    await expect(sla).not.toContainText('Vencido');
  });

  test('el detalle muestra «SLA vencido hace mm:ss» y deja decidir', async ({ page }) => {
    const request = await seedCase('GREEN');
    await rewrite(page, '/api/requests/' + request.id, (body) => {
      body.sla_remaining_seconds = -130;
      body.sla_breached = true;
    });

    await page.goto('/consola/' + request.id);
    const sla = page.getByTestId('detail-sla');
    await expect(sla).toHaveClass(/is-late/);
    await expect(sla).toHaveText(/^\s*SLA vencido hace 02:(1\d|[2-5]\d)\s*$/);
    await expectTicking(sla, 130);
    await expect(page.getByTestId('approve')).toBeEnabled();
    await expect(page.getByTestId('approve')).toHaveText(/Aprobar en un clic/);
  });
});

test.describe('Tablero: decisión al cierre con indicadores que la demo no produce', () => {
  const setIndicator = (body, key, value, display) => {
    const indicator = body.indicators.find((item) => item.key === key);
    indicator.current_value = value;
    indicator.current_display = display;
  };

  test('adopción del asistente por debajo de 50 %: aplica «Detener»', async ({ page }) => {
    await rewrite(page, '/api/dashboard', (body) => setIndicator(body, 'assistant_usage', 0.4, '40 %'));
    await page.goto('/tablero');

    await expect(page.getByTestId('kpi-assistant_usage').locator('.kpi__value')).toHaveText('40 %');
    await expect(page.getByTestId('verdict-label')).toHaveText('Detener');
    await expect(page.getByTestId('verdict')).toContainText('La adopción del asistente está por debajo del 50 %. (5 de 6)');
    await expect(page.getByTestId('option-stop')).toHaveClass(/is-active/);
    await expect(page.getByTestId('option-expand')).not.toHaveClass(/is-active/);
    await expect(page.getByTestId('option-adjust')).not.toHaveClass(/is-active/);
    await expect(page.locator('.criteria li:not(.is-ok)')).toHaveText(/80\s% o más por el asistente/);
  });

  test('un vehículo sin combustible por causa del sistema: aplica «Detener» aunque lo demás cumpla', async ({ page }) => {
    await rewrite(page, '/api/dashboard', (body) => setIndicator(body, 'continuity', 1, '1 incidente'));
    await page.goto('/tablero');

    await expect(page.getByTestId('kpi-continuity').locator('.kpi__value')).toHaveText('1 incidente');
    await expect(page.getByTestId('verdict-label')).toHaveText('Detener');
    await expect(page.getByTestId('verdict')).toContainText('Hay vehículos sin combustible atribuibles al sistema. (5 de 6)');
    await expect(page.getByTestId('option-stop')).toHaveClass(/is-active/);
    await expect(page.locator('.criteria li:not(.is-ok)')).toHaveText(/0 vehículos sin combustible/);
  });

  test('adopción entre 50 y 80 %: aplica «Ajustar», no «Detener»', async ({ page }) => {
    await rewrite(page, '/api/dashboard', (body) => setIndicator(body, 'assistant_usage', 0.5, '50 %'));
    await page.goto('/tablero');

    await expect(page.getByTestId('verdict-label')).toHaveText('Ajustar');
    await expect(page.getByTestId('option-adjust')).toHaveClass(/is-active/);
    await expect(page.getByTestId('option-stop')).not.toHaveClass(/is-active/);
    await expect(page.getByTestId('verdict')).toContainText('(5 de 6)');
  });

  test('cada criterio de ampliación en su borde exacto cuenta como cumplido', async ({ page }) => {
    await rewrite(page, '/api/dashboard', (body) => {
      setIndicator(body, 'attention_time', 3, '3,0 min');
      setIndicator(body, 'complete_first_try', 0.9, '90 %');
      setIndicator(body, 'one_click', 0.6, '60 %');
      setIndicator(body, 'assistant_usage', 0.8, '80 %');
      setIndicator(body, 'high_priority_alerts', 0.5, 'Precisión 50 %');
    });
    await page.goto('/tablero');

    await expect(page.locator('.criteria li.is-ok')).toHaveCount(6);
    await expect(page.getByTestId('verdict-label')).toHaveText('Ampliar');
  });

  test('una mediana de atención de 3,1 min ya no permite «Ampliar»', async ({ page }) => {
    await rewrite(page, '/api/dashboard', (body) => setIndicator(body, 'attention_time', 3.1, '3,1 min'));
    await page.goto('/tablero');

    await expect(page.getByTestId('verdict-label')).toHaveText('Ajustar');
    await expect(page.locator('.criteria li:not(.is-ok)')).toHaveText(/Mediana de 3 min o menos/);
  });
});
