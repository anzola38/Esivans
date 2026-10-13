import {
  CASES,
  DATE_TIME,
  FOOTER,
  TIME,
  api,
  authorizeViaApi,
  expect,
  expectNoHorizontalOverflow,
  expectTrafficLightsWithText,
  findFormatViolations,
  findRawTokens,
  importSampleViaApi,
  seedCase,
  selectRole,
  test,
  todayText,
  visibleText,
} from './support/fixtures.mjs';

/** Loads every kind of data the presenter can reach: the five cases, decisions, the provider file and a review. */
async function seedFullDemo() {
  const green = await seedCase('GREEN');
  await authorizeViaApi(green.id);
  const yellow = await seedCase('VEH015');
  const red = await seedCase('VEH199');
  await authorizeViaApi(red.id, { action: 'adjust', amount: 20000, reason: 'Apoyo nocturno confirmado con el coordinador' });
  const noFuel = await seedCase('NO_FUEL');
  const unregistered = await seedCase('UNREGISTERED');
  const rejected = await api('/requests/' + unregistered.id + '/decision', {
    method: 'POST',
    body: { action: 'reject', reason: 'Número sin conductor asignado' },
  });
  expect(rejected.status).toBe(200);
  await importSampleViaApi();
  const alert = (await api('/alerts?status=open&kind=vehicle')).json.items[0];
  await api('/alerts/' + alert.id, {
    method: 'PATCH',
    role: 'coordinator',
    body: { review_result: 'confirmed', comment: 'Confirmada con mantenimiento.' },
  });
  return { green, yellow, red, noFuel, unregistered };
}

/** Checks one rendered view: layout, footer, traffic lights, raw values and es-CO formats. */
async function auditView(page, label) {
  await test.step(label, async () => {
    await page.evaluate(() => document.fonts.ready);
    await expectNoHorizontalOverflow(page, label);
    await expect.soft(page.getByTestId('footer'), label + ': pie').toHaveText(FOOTER);
    await expect.soft(page.getByTestId('footer'), label + ': pie a la vista').toBeInViewport();
    await expectTrafficLightsWithText(page);
    const text = await visibleText(page);
    expect.soft(findRawTokens(text), label + ': estados crudos o textos en inglés').toEqual([]);
    expect.soft(findFormatViolations(text), label + ': formatos es-CO').toEqual([]);

    // Nothing the presenter needs to click is cut off at the right edge of the window.
    const clipped = await page.evaluate(() => {
      const out = [];
      for (const node of document.querySelectorAll('button, a, input, select, textarea, .ui-badge')) {
        const rect = node.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;
        if (rect.right > window.innerWidth + 1 || rect.left < -1) {
          out.push(node.tagName.toLowerCase() + ' "' + (node.textContent ?? '').trim().slice(0, 40) + '"');
        }
      }
      return out;
    });
    expect.soft(clipped, label + ': elementos cortados por el borde').toEqual([]);
  });
}

test.describe('Transversales con datos cargados', () => {
  test('las 4 pantallas: sin desborde horizontal, semáforo con texto, formatos es-CO y nada en inglés', async ({ page }) => {
    test.setTimeout(180_000);
    const requests = await seedFullDemo();

    // ---- Simulador: los cinco casos
    await page.goto('/simulador');
    for (const code of Object.keys(CASES)) {
      await page.getByTestId('case-' + code).click();
      await expect(page.getByTestId('case-driver')).toHaveText(CASES[code].driver);
      await expect(page.locator('.ui-phone__body .ui-bubble').first()).toBeVisible();
      await expect(page.getByTestId('request-stage')).toBeVisible();
      await auditView(page, 'simulador ' + code);
    }

    // ---- Consola: cola con los tres semáforos y estados
    await page.goto('/consola');
    await expect(page.getByTestId('queue-table').locator('tbody tr')).toHaveCount(5);
    await auditView(page, 'consola cola');
    const lights = await page.getByTestId('queue-table').locator('app-traffic-light').allTextContents();
    expect(lights.map((text) => /Verde|Amarillo|Rojo/.exec(text)?.[0]).sort()).toEqual(['Amarillo', 'Amarillo', 'Amarillo', 'Rojo', 'Verde']);
    for (const cell of await page.getByTestId('queue-table').locator('tbody tr td:nth-child(5)').all()) {
      await expect(cell).toHaveText(TIME);
    }

    // ---- Consola: detalle de cada solicitud, arriba y abajo (bitácora)
    for (const [name, request] of Object.entries(requests)) {
      await page.goto('/consola/' + request.id);
      await expect(page.getByTestId('detail-plate')).toBeVisible();
      await expect(page.getByTestId('audit-card').locator('tbody tr').first()).toBeVisible();
      await auditView(page, 'consola detalle ' + name);
      for (const cell of await page.getByTestId('audit-card').locator('tbody tr td:first-child').all()) {
        await expect(cell).toHaveText(DATE_TIME);
        await expect(cell).toContainText(todayText());
      }
      await page.getByTestId('audit-card').scrollIntoViewIfNeeded();
      await auditView(page, 'consola detalle ' + name + ' (bitácora)');
    }

    // ---- Consola: cuadro de decisión abierto
    await page.goto('/consola/' + requests.yellow.id);
    await page.getByRole('button', { name: 'Ajustar' }).click();
    await expect(page.getByRole('dialog', { name: 'Ajustar el valor' })).toBeVisible();
    await auditView(page, 'consola cuadro de ajuste');
    const dialogBox = await page.getByRole('dialog').boundingBox();
    const viewport = page.viewportSize();
    expect(dialogBox.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox.y).toBeGreaterThanOrEqual(0);
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(viewport.width);
    expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(viewport.height);
    await page.keyboard.press('Escape');

    // ---- Alertas: las cuatro pestañas, como coordinador
    await page.goto('/alertas');
    await selectRole(page, 'coordinator');
    await page.getByRole('tab', { name: 'Tanqueos con alerta' }).click();
    await page.getByTestId('filter-all').click();
    const refuelRows = page.getByTestId('alert-list').locator('.item');
    await expect(refuelRows).toHaveCount(16);
    await auditView(page, 'alertas tanqueos');
    await page.getByTestId('alert-list').locator('[data-vehicle=VEH023]').click();
    await expect(page.getByTestId('alert-overpaid')).toBeVisible();
    await auditView(page, 'alertas VEH023');
    await page.getByTestId('review').scrollIntoViewIfNeeded();
    await auditView(page, 'alertas VEH023 (revisión)');

    await page.getByRole('tab', { name: 'Vehículos' }).click();
    await page.getByTestId('filter-all').click();
    for (const vehicle of ['VEH129', 'VEH215', 'VEH160']) {
      await page.getByTestId('alert-list').locator('[data-vehicle=' + vehicle + ']').first().click();
      await expect(page.getByTestId('alert-vehicle')).toHaveText(vehicle);
      await expect(page.getByTestId('ledger').locator('tbody tr').first()).toBeVisible();
      await auditView(page, 'alertas ' + vehicle);
      await page.getByTestId('review').scrollIntoViewIfNeeded();
      await auditView(page, 'alertas ' + vehicle + ' (revisión)');
    }

    await page.getByRole('tab', { name: 'Conciliación' }).click();
    await expect(page.getByTestId('overpaid-amount')).toHaveText('$27.783');
    await auditView(page, 'alertas conciliación sin resumen');
    await page.getByRole('button', { name: 'Cargar exporte de ejemplo de Terpel' }).click();
    await expect(page.getByTestId('import-duplicates')).toHaveText('10');
    await auditView(page, 'alertas conciliación con resumen');

    await page.getByRole('tab', { name: 'Reglas y umbrales' }).click();
    await expect(page.getByTestId('rules-table').locator('tbody tr.is-clickable')).toHaveCount(25);
    await auditView(page, 'alertas reglas');
    await page.getByTestId('rule-row-R05').click();
    await auditView(page, 'alertas reglas R05');

    // ---- Tablero
    await page.goto('/tablero');
    await expect(page.getByTestId('indicators').locator('.kpi')).toHaveCount(9);
    await expect(page.getByTestId('kpi-attention_time').locator('.kpi__source')).toHaveText('Calculado con la demo');
    await auditView(page, 'tablero');
    await page.getByTestId('verdict').scrollIntoViewIfNeeded();
    await auditView(page, 'tablero (decisión)');
    for (const badge of await page.getByTestId('indicators').locator('.kpi .ui-badge').all()) {
      await expect(badge).toHaveText(/Cumple la meta|Cerca de la meta|No cumple|Sin datos todavía/);
    }

    // ---- Aviso de reinicio abierto (sin confirmar)
    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    await expect(page.getByRole('dialog', { name: '¿Reiniciar la demo?' })).toBeVisible();
    await auditView(page, 'aviso de reinicio');
  });

  test('las 4 pantallas recién reiniciadas tampoco se desbordan ni muestran valores crudos', async ({ page }) => {
    for (const path of ['/simulador', '/consola', '/alertas', '/tablero']) {
      await page.goto(path);
      await expect(page.locator('h1.topbar__title')).not.toHaveText('');
      await expect(page.locator('main.content')).not.toContainText('Cargando');
      await page.waitForLoadState('networkidle');
      await auditView(page, path + ' vacío');
    }
  });

  test('recargar (F5) en /consola/:id conserva la pantalla, antes y después de decidir', async ({ page }) => {
    const request = await seedCase('VEH199');
    await page.goto('/consola/' + request.id);
    await expect(page.getByTestId('detail-light')).toContainText('Rojo');

    await page.reload();
    await expect(page).toHaveURL(new RegExp('/consola/' + request.id + '$'));
    await expect(page.locator('h1.topbar__title')).toHaveText('Consola del técnico');
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA199');
    await expect(page.getByTestId('detail-light')).toContainText('7 puntos');
    await expect(page.locator('[data-rule=R09]')).toContainText('tanqueo a las 23:14 sin servicios cercanos');
    await expect(page.getByRole('button', { name: 'Ajustar' })).toBeEnabled();

    // Con la decisión tomada y la habilitación pendiente, F5 no pierde el panel.
    await page.getByRole('button', { name: 'Ajustar' }).click();
    await page.getByRole('spinbutton', { name: 'Valor a autorizar (pesos)' }).fill('20000');
    await page.getByRole('button', { name: 'Apoyo nocturno confirmado con el coordinador' }).click();
    await page.getByRole('button', { name: 'Guardar ajuste' }).click();
    await expect(page.getByTestId('enablement')).toContainText('$20.000');
    const reference = await page.getByRole('textbox', { name: 'Referencia del portal' }).inputValue();

    await page.reload();
    await expect(page.getByTestId('detail-stage')).toHaveText('Por habilitar');
    await expect(page.getByTestId('enablement')).toContainText('Ajustada por Laura Mendoza (sugerido $10.000).');
    await expect(page.getByRole('textbox', { name: 'Referencia del portal' })).toHaveValue(reference);
    await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');

    await page.reload();
    await expect(page.getByTestId('authorization')).toContainText('Autorizada: $20.000 de GNV.');
    await expect(page.getByTestId('audit-card').locator('[data-action="decision.adjust"]')).toHaveCount(1);
  });

  test('las rutas internas abren directo por URL (sin pasar por el menú)', async ({ page }) => {
    for (const [path, title] of [
      ['/consola', 'Consola del técnico'],
      ['/alertas', 'Alertas del coordinador'],
      ['/tablero', 'Tablero del piloto'],
      ['/simulador?wa=573005550199', 'Simulador del conductor'],
    ]) {
      const response = await page.goto(path);
      expect(response.status(), path).toBe(200);
      await expect(page.locator('h1.topbar__title')).toHaveText(title);
    }
    // El enlace con ?wa= abre el caso de ese número.
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA199');
  });

  test('la tipografía Lato carga en todas las pantallas', async ({ page }) => {
    for (const path of ['/simulador', '/consola', '/alertas', '/tablero']) {
      await page.goto(path);
      await page.evaluate(() => document.fonts.ready);
      expect(await page.evaluate(() => document.fonts.check('16px Lato')), path).toBe(true);
      expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily), path).toContain('Lato');
    }
  });
});
