import { DATE_TIME, api, expect, selectRole, test, todayText } from './support/fixtures.mjs';

const PRIORITY_RANK = { Alta: 0, Media: 1, Baja: 2 };

async function openAlerts(page, tab) {
  await page.goto('/alertas');
  await selectRole(page, 'coordinator');
  await page.getByRole('tab', { name: tab }).click();
  await expect(page.getByTestId('alert-list')).toBeVisible();
}

/** Reads priority, points and vehicle of every row of the list, in screen order. */
async function listRows(page) {
  return page.getByTestId('alert-list').locator('.item').evaluateAll((rows) =>
    rows.map((row) => ({
      vehicle: row.getAttribute('data-vehicle'),
      rules: row.getAttribute('data-rules'),
      priority: row.querySelector('app-priority-chip')?.textContent?.trim(),
      points: Number(/\d+/.exec(row.querySelector('.item__points')?.textContent ?? '')?.[0]),
    })),
  );
}

function expectSortedByPriority(rows) {
  for (let i = 1; i < rows.length; i += 1) {
    const previous = rows[i - 1];
    const current = rows[i];
    const order = PRIORITY_RANK[previous.priority] - PRIORITY_RANK[current.priority];
    expect(order, previous.vehicle + ' va antes que ' + current.vehicle).toBeLessThanOrEqual(0);
    if (order === 0) expect(previous.points).toBeGreaterThanOrEqual(current.points);
  }
}

/** Registers a review result on the selected alert and returns the closed-review block. */
async function registerResult(page, result, comment) {
  const review = page.getByTestId('review');
  await review.getByRole('radio', { name: result }).click();
  await expect(review.getByRole('radio', { name: result })).toHaveAttribute('aria-checked', 'true');
  if (comment !== undefined) await review.getByRole('textbox', { name: 'Comentario' }).fill(comment);
  await review.getByRole('button', { name: 'Registrar resultado' }).click();
  return page.getByTestId('review-closed');
}

test.describe('Alertas: tanqueos con alerta', () => {
  test('el resumen cuenta abiertas, prioridad alta y vencidas de la semilla', async ({ page }) => {
    await openAlerts(page, 'Tanqueos con alerta');
    await expect(page.getByTestId('alerts-summary')).toHaveText(/Abiertas: 11\s*Prioridad alta: 4\s*Vencidas: 2/);
    await expect(page.getByRole('tab', { name: 'Tanqueos con alerta' })).toContainText('4');
    await expect(page.getByRole('tab', { name: 'Vehículos' })).toContainText('7');
    await expect(page.getByRole('tab').locator('visible=true')).toHaveCount(4);
    await expect(page.getByTestId('filter-open')).toHaveText('Abiertas · 4');
    await expect(page.getByTestId('filter-reviewed')).toHaveText('Revisadas · 6');
    await expect(page.getByTestId('filter-all')).toHaveText('Todas · 10');
  });

  test('la lista va por prioridad y puntos, con plazo y marca de vencida', async ({ page }) => {
    await openAlerts(page, 'Tanqueos con alerta');
    const rows = await listRows(page);
    expect(rows.map((row) => row.vehicle)).toEqual(['VEH906', 'VEH199', 'VEH908', 'VEH904']);
    expect(rows.map((row) => row.priority)).toEqual(['Alta', 'Alta', 'Media', 'Media']);
    expect(rows.map((row) => row.points)).toEqual([5, 5, 3, 2]);
    expectSortedByPriority(rows);

    const list = page.getByTestId('alert-list');
    await expect(list.locator('[data-vehicle=VEH906]')).toContainText('Vencida');
    await expect(list.locator('[data-vehicle=VEH199]')).toContainText('48 horas');
    await expect(list.locator('[data-vehicle=VEH199]')).not.toContainText('Vencida');
    await expect(list.locator('[data-vehicle=VEH908]')).toContainText('En la semana');

    // La primera queda abierta: vencida, con su plazo y sus dos razones.
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH906');
    await expect(page.getByTestId('alert-priority')).toHaveText('Prioridad alta');
    await expect(page.getByTestId('alert-points')).toHaveText('5 puntos');
    const deadline = page.getByTestId('alert-deadline');
    await expect(deadline).toHaveClass(/is-late/);
    await expect(deadline).toContainText('Plazo: 48 horas.');
    await expect(deadline).toContainText(/Vencida hace \d+ (h|días)/);
    await expect(deadline).toContainText(/\(\d{2}\/\d{2}\/\d{4}, \d{1,2}:\d{2}\s[ap]\.\sm\.\)/);
    await expect(deadline).toContainText(/Generada el \d{2}\/\d{2}\/\d{4}/);
    const reasons = page.getByTestId('alert-reasons').locator('.reason');
    await expect(reasons).toHaveCount(2);
    await expect(reasons.nth(0)).toContainText('R05');
    await expect(reasons.nth(0)).toContainText('cargó 5,0 gal de combustible líquido con 12 km desde su carga anterior (típica 4,4 gal)');
    await expect(reasons.nth(0)).toContainText('+3');
    await expect(reasons.nth(1)).toContainText('R11');
    await expect(reasons.nth(1)).toContainText('tipo de venta: Recuperado');
    await expect(page.getByTestId('alert-detail')).toContainText('Reglas v1');
    await expect(page.getByTestId('alert-detail')).toContainText('Tanqueo con alerta');
    await expect(page.getByTestId('alert-detail')).toContainText('Carga anterior');

    // Libro único del vehículo de la alerta, con el tanqueo marcado.
    const ledger = page.getByTestId('ledger');
    await expect(ledger).toContainText('Libro único de tanqueos');
    await expect(ledger.locator('tbody tr')).toHaveCount(8);
    await expect(ledger.locator('tbody tr.is-selected')).toHaveCount(1);

    // Una alerta que no está vencida muestra cuánto falta.
    await list.locator('[data-vehicle=VEH199]').click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH199');
    await expect(page.getByTestId('alert-deadline')).not.toHaveClass(/is-late/);
    await expect(page.getByTestId('alert-deadline')).toContainText(/Plazo: 48 horas\.\s*Vence en \d+ h/);
    await list.locator('[data-vehicle=VEH908]').click();
    await expect(page.getByTestId('alert-deadline')).toContainText(/Plazo: en la semana\.\s*Vence en \d+ (h|días)/);
  });

  test('las revisadas muestran resultado, autor y fecha', async ({ page }) => {
    await openAlerts(page, 'Tanqueos con alerta');
    await page.getByTestId('filter-reviewed').click();
    const rows = await listRows(page);
    // Solo revisadas: la alerta abierta que estaba seleccionada no se cuela en este filtro.
    expect(rows.map((row) => row.vehicle)).toEqual(['VEH903', 'VEH199', 'VEH913', 'VEH907', 'VEH918', 'VEH905']);
    expectSortedByPriority(rows);
    await expect(page.getByTestId('alert-list')).not.toContainText('Vencida');
    await expect(page.getByTestId('alert-list').locator('.item.is-reviewed')).toHaveCount(6);
    await expect(page.getByTestId('alert-list').locator('.item').first()).toContainText('Confirmado');

    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH903');
    await expect(page.getByTestId('review-result')).toHaveText('Confirmado');
    await expect(page.getByTestId('review-author')).toHaveText('Andrés Molina');
    await expect(page.getByTestId('alert-deadline')).toContainText(/Revisada el \d{2}\/\d{2}\/\d{4}/);
    await expect(page.getByTestId('review-closed').getByTestId('next-action')).toContainText('Conversación con el conductor con la evidencia');
  });
});

test.describe('Alertas: vehículos', () => {
  test('VEH129 encabeza la lista con 8 puntos, prioridad alta y V01, V05 y V08', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    const rows = await listRows(page);
    expect(rows.map((row) => row.vehicle)).toEqual(['VEH129', 'VEH015', 'VEH215', 'VEH910', 'VEH199', 'VEH911', 'VEH160']);
    expectSortedByPriority(rows);
    expect(rows[0]).toMatchObject({ vehicle: 'VEH129', priority: 'Alta', points: 8, rules: 'V01 V05 V08' });
    expect(rows.find((row) => row.vehicle === 'VEH215')).toMatchObject({ priority: 'Media', points: 3, rules: 'V01' });
    await expect(page.getByTestId('alert-list').locator('[data-vehicle=VEH015]')).toContainText('Vencida');

    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH129');
    await expect(page.getByTestId('alert-points')).toHaveText('8 puntos');
    await expect(page.getByTestId('alert-priority')).toHaveText('Prioridad alta');
    await expect(page.getByTestId('alert-priority')).toHaveClass(/ui-badge--red/);
    await expect(page.getByTestId('alert-deadline')).toContainText(/Plazo: 48 horas\.\s*Vence en \d+ h/);

    const reasons = page.getByTestId('alert-reasons').locator('.reason');
    await expect(reasons).toHaveCount(3);
    const expected = [
      ['V01', 'Rendimiento bajo', 'Rinde 20,3 km/gal-eq frente a la mediana de su grupo, 52,7 (61 % menos); el límite es 39,5', '+3'],
      ['V05', 'Sin servicios en EOM', '102 tanqueos por $4,1 M sin un solo servicio en EOM en los 90 días', '+3'],
      ['V08', 'Muchas alertas', '26 % de sus tanqueos con al menos una alerta', '+2'],
    ];
    for (const [index, [code, name, text, points]] of expected.entries()) {
      await expect(reasons.nth(index).locator('.reason__code')).toHaveText(code);
      await expect(reasons.nth(index).locator('.reason__name')).toHaveText(name);
      await expect(reasons.nth(index).locator('.reason__text')).toHaveText(text);
      await expect(reasons.nth(index).locator('.reason__points')).toHaveText(points);
    }

    const efficiency = page.getByTestId('alert-efficiency');
    await expect(efficiency).toContainText('20,3');
    await expect(efficiency).toContainText('52,7');
    await expect(efficiency).toContainText('39,5');
    const stats = page.locator('.veh-evidence .stat');
    await expect(stats.nth(0)).toHaveText(/102\s*tanqueos en 90 días/);
    await expect(stats.nth(1)).toHaveText(/\$4\.128\.960\s*pagados en 90 días/);
    await expect(stats.nth(2)).toHaveText(/0\s*servicios en EOM/);
    await expect(stats.nth(3)).toHaveText(/26\s%\s*tanqueos con alerta/);

    // Detalle con el libro único.
    const ledger = page.getByTestId('ledger');
    await expect(ledger).toContainText('102 cargas · $4.128.960');
    await expect(ledger).toContainText('Terpel 102 cargas');
    await expect(ledger).toContainText('EOM 0 servicios en 90 días');
    await expect(ledger.locator('tbody tr')).toHaveCount(8);
    await ledger.getByRole('button', { name: 'Ver los 102 movimientos' }).click();
    await expect(ledger.locator('tbody tr')).toHaveCount(102);
    await ledger.getByRole('button', { name: 'Ver solo los últimos' }).click();
    await expect(ledger.locator('tbody tr')).toHaveCount(8);
  });

  test('VEH215 se marca por V01: rinde 24,0 frente a un límite de 31,4', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    await page.getByTestId('alert-list').locator('[data-vehicle=VEH215]').click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH215');
    await expect(page.getByTestId('alert-points')).toHaveText('3 puntos');
    await expect(page.getByTestId('alert-priority')).toHaveText('Prioridad media');
    const reasons = page.getByTestId('alert-reasons').locator('.reason');
    await expect(reasons).toHaveCount(1);
    await expect(reasons.locator('.reason__code')).toHaveText('V01');
    await expect(reasons.locator('.reason__name')).toHaveText('Rendimiento bajo');
    await expect(reasons.locator('.reason__text')).toHaveText(
      'Rinde 24,0 km/gal frente a la mediana de su grupo, 41,8 (43 % menos); el límite es 31,4',
    );
    await expect(reasons.locator('.reason__points')).toHaveText('+3');
    await expect(page.getByTestId('alert-efficiency')).toContainText('24,0');
    await expect(page.getByTestId('alert-efficiency')).toContainText('31,4');
    await expect(page.getByTestId('alert-deadline')).toContainText('Plazo: en la semana.');
    await expect(page.getByTestId('ledger').locator('tbody tr')).toHaveCount(8);
  });

  test('VEH160: el libro único suma Terpel y GoPass; GoPass solo calcularía 783 km por galón', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    await page.getByTestId('alert-list').locator('[data-vehicle=VEH160]').click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH160');
    await expect(page.getByTestId('alert-priority')).toHaveText('Prioridad baja');
    await expect(page.getByTestId('alert-reasons')).toContainText('V06');
    await expect(page.getByTestId('alert-reasons')).toContainText('Carga con Terpel y con GoPass: ningún proveedor ve todo su consumo');

    const comparison = page.getByTestId('ledger-comparison');
    await expect(comparison.locator('.compare__col--bad')).toHaveText(/GoPass solo calcularía\s*783 km por galón\s*4\.803 km ÷ 6,135 gal/);
    await expect(comparison.locator('.compare__col--good')).toHaveText(
      /Con el libro único\s*73,5 km\/gal-eq\s*suma 34 cargas de gas en Terpel \(313,6 m³\)/,
    );
    await expect(comparison.locator('.compare__text')).toHaveText(
      'GoPass solo calcula 4.803 km ÷ 6,135 gal = 783 km por galón, porque no ve sus 34 cargas de gas en Terpel (313,6 m³). En el libro único son 73,5 km por galón equivalente.',
    );

    const ledger = page.getByTestId('ledger');
    await expect(ledger).toContainText('41 cargas');
    await expect(ledger.locator('.prov--terpel')).toContainText('Terpel 39 cargas');
    await expect(ledger.locator('.prov--gopass')).toContainText('GoPass 2 cargas · $194.524');

    await page.getByTestId('ledger-provider-gopass').click();
    await expect(ledger.locator('tbody tr')).toHaveCount(2);
    for (const row of await ledger.locator('tbody tr').all()) await expect(row.locator('td').nth(1)).toHaveText('GoPass');
    await page.getByTestId('ledger-provider-terpel').click();
    await expect(ledger.locator('tbody tr')).toHaveCount(8);
    for (const row of await ledger.locator('tbody tr').all()) await expect(row.locator('td').nth(1)).toHaveText('Terpel');
    await ledger.getByRole('button', { name: 'Todos' }).click();
    await ledger.getByRole('button', { name: 'Ver los 41 movimientos' }).click();
    await expect(ledger.locator('tbody tr')).toHaveCount(41);
    await expect(ledger.locator('tbody tr').filter({ hasText: 'GoPass' })).toHaveCount(2);
    await expect(ledger.locator('tbody tr').filter({ hasText: 'Terpel' })).toHaveCount(39);
  });
});

test.describe('Alertas: registrar el resultado de la revisión', () => {
  test('resultado y comentario son obligatorios, en la pantalla y en la API', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    const review = page.getByTestId('review');
    await expect(review).toContainText('Registrar el resultado');
    await expect(review.getByRole('radio')).toHaveText([
      /Confirmado\s*La desviación es real/,
      /Justificado\s*Hay una causa válida/,
      /Error de dato\s*El dato venía mal/,
    ]);

    let patches = 0;
    page.on('request', (request) => {
      if (request.method() === 'PATCH') patches += 1;
    });

    // Sin resultado ni comentario
    await review.getByRole('button', { name: 'Registrar resultado' }).click();
    await expect(page.getByTestId('result-error')).toHaveText('Elige el resultado de la revisión.');
    await expect(page.getByTestId('comment-error')).toHaveText('El comentario es obligatorio.');

    // Con resultado pero con el comentario borrado
    await review.getByRole('radio', { name: 'Confirmado' }).click();
    await expect(review.getByRole('textbox', { name: 'Comentario' })).toHaveValue(
      'Se revisó la evidencia con el técnico y se confirma la desviación.',
    );
    await review.getByRole('textbox', { name: 'Comentario' }).fill('  ');
    await review.getByRole('button', { name: 'Registrar resultado' }).click();
    await expect(page.getByTestId('comment-error')).toHaveText('El comentario es obligatorio.');
    await expect(page.getByTestId('result-error')).toHaveCount(0);
    await expect(page.getByTestId('review-closed')).toHaveCount(0);
    expect(patches).toBe(0);

    const alerts = (await api('/alerts', { role: 'coordinator' })).json.items;
    const veh129 = alerts.find((alert) => alert.vehicle?.code === 'VEH129' && alert.kind === 'vehicle');
    expect(veh129.status).toBe('open');
    const noComment = await api('/alerts/' + veh129.id, {
      method: 'PATCH',
      role: 'coordinator',
      body: { review_result: 'confirmed' },
    });
    expect(noComment.status).toBe(422);
  });

  test('los tres resultados en alertas distintas, cada uno con autor, fecha y acción siguiente', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    const list = page.getByTestId('alert-list');

    // 1. Confirmado en el VEH129 (rendimiento bajo y uso indebido: dos acciones).
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH129');
    let closed = await registerResult(
      page,
      'Confirmado',
      'Rinde 61 % menos que su grupo y no tiene servicios en EOM: va a revisión mecánica.',
    );
    await expect(page.getByTestId('review-result')).toHaveText('Confirmado');
    await expect(page.getByTestId('review-author')).toHaveText('Carlos Rivas');
    await expect(closed.locator('.closed__who')).toContainText(todayText());
    await expect(closed.locator('.closed__who')).toHaveText(/Carlos Rivas\s*· \d{2}\/\d{2}\/\d{4}, \d{1,2}:\d{2}\s[ap]\.\sm\./);
    await expect(closed.locator('.closed__comment')).toHaveText(
      '“Rinde 61 % menos que su grupo y no tiene servicios en EOM: va a revisión mecánica.”',
    );
    const actions = closed.getByTestId('next-action');
    await expect(actions).toHaveCount(2);
    await expect(actions.nth(0)).toContainText('Acción que sigue · Confirmada: rendimiento bajo o caída reciente');
    await expect(actions.nth(0)).toContainText('Revisión mecánica del vehículo; mientras tanto, el valor sugerido usa su rendimiento real.');
    await expect(actions.nth(0)).toContainText('Responsable: Coordinador con mantenimiento.');
    await expect(actions.nth(1)).toContainText('Conversación con el conductor con la evidencia');
    await expect(page.locator('.ui-toast').last()).toContainText('Resultado "Confirmado" registrado en la bitácora.');
    await expect(page.getByTestId('alert-deadline')).toContainText('Revisada el ' + todayText());
    await expect(list.locator('[data-vehicle=VEH129]')).toContainText('Confirmado');
    await expect(page.getByTestId('alerts-summary')).toHaveText(/Abiertas: 10\s*Prioridad alta: 3\s*Vencidas: 2/);

    // 2. Justificado en el VEH215.
    await list.locator('[data-vehicle=VEH215]').click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH215');
    closed = await registerResult(page, 'Justificado');
    await expect(page.getByTestId('review-result')).toHaveText('Justificado');
    await expect(page.getByTestId('review-author')).toHaveText('Carlos Rivas');
    await expect(closed.locator('.closed__who')).toContainText(todayText());
    await expect(closed.locator('.closed__comment')).toHaveText(
      '“El coordinador de zona confirmó la causa: operación especial ya registrada.”',
    );
    await expect(closed.getByTestId('next-action')).toHaveCount(1);
    await expect(closed.getByTestId('next-action')).toContainText('Acción que sigue · Justificada');
    await expect(closed.getByTestId('next-action')).toContainText('Se registra la causa y, si se repite, una excepción con vigencia');
    await expect(closed.getByTestId('next-action')).toContainText('Responsable: Técnico.');

    // 3. Error de dato en el VEH910 (odómetro congelado).
    await list.locator('[data-vehicle=VEH910]').click();
    await expect(page.getByTestId('alert-vehicle')).toHaveText('VEH910');
    closed = await registerResult(page, 'Error de dato', 'El odómetro del proveedor llega repetido: se pide la corrección.');
    await expect(page.getByTestId('review-result')).toHaveText('Error de dato');
    await expect(page.getByTestId('review-author')).toHaveText('Carlos Rivas');
    await expect(closed.locator('.closed__who')).toContainText(todayText());
    await expect(closed.getByTestId('next-action')).toHaveCount(1);
    await expect(closed.getByTestId('next-action')).toContainText('Acción que sigue · Error de dato');
    await expect(closed.getByTestId('next-action')).toContainText('Se corrige en la fuente: odómetro, ficha técnica o asignación en EOM.');
    await expect(closed).toContainText('Ninguna alerta detiene el suministro');

    await expect(page.getByTestId('alerts-summary')).toHaveText(/Abiertas: 8\s*Prioridad alta: 3\s*Vencidas: 2/);
    await expect(page.getByTestId('filter-open')).toHaveText('Abiertas · 4');
    await expect(page.getByTestId('filter-reviewed')).toHaveText('Revisadas · 5');

    // Queda guardado en el servidor con autor, fecha y comentario.
    const alerts = (await api('/alerts?kind=vehicle', { role: 'coordinator' })).json.items;
    const byVehicle = (code) => alerts.find((alert) => alert.vehicle.code === code && alert.reviewed_by === 'Carlos Rivas');
    expect(byVehicle('VEH129')).toMatchObject({ status: 'reviewed', review_result: 'confirmed' });
    expect(byVehicle('VEH215')).toMatchObject({ status: 'reviewed', review_result: 'justified' });
    expect(byVehicle('VEH910')).toMatchObject({ status: 'reviewed', review_result: 'data_error' });
    const audit = (await api('/audit?action=alert.reviewed', { role: 'coordinator' })).json.items;
    expect(audit).toHaveLength(3);
    for (const entry of audit) expect(entry.actor).toBe('Carlos Rivas');

    // Y sobrevive a una recarga: la lista de revisadas las muestra con su resultado.
    await page.reload();
    await page.getByRole('tab', { name: 'Vehículos' }).click();
    await page.getByTestId('filter-reviewed').click();
    await expect(page.getByTestId('alert-list').locator('[data-vehicle=VEH129]')).toContainText('Confirmado');
    await expect(page.getByTestId('alert-list').locator('[data-vehicle=VEH215]')).toContainText('Justificado');
    await expect(page.getByTestId('alert-list').locator('[data-vehicle=VEH910]')).toContainText('Error de dato');
    await page.getByTestId('alert-list').locator('[data-vehicle=VEH215]').click();
    await expect(page.getByTestId('review-result')).toHaveText('Justificado');
    await expect(page.getByTestId('review-author')).toHaveText('Carlos Rivas');
    await expect(page.getByTestId('review-closed').locator('.closed__who')).toHaveText(new RegExp(todayText()));
  });

  test('un resultado ya registrado se puede corregir y queda cada cambio en la bitácora', async ({ page }) => {
    await openAlerts(page, 'Vehículos');
    await registerResult(page, 'Confirmado');
    await expect(page.getByTestId('review-result')).toHaveText('Confirmado');

    await page.getByTestId('review').getByRole('button', { name: 'Corregir' }).click();
    await expect(page.getByTestId('review').getByRole('radio', { name: 'Confirmado' })).toHaveAttribute('aria-checked', 'true');
    await registerResult(page, 'Justificado', 'Ruta de montaña con carga completa: causa válida.');
    await expect(page.getByTestId('review-result')).toHaveText('Justificado');
    await expect(page.getByTestId('review-closed').locator('.closed__comment')).toHaveText(
      '“Ruta de montaña con carga completa: causa válida.”',
    );

    const audit = (await api('/audit?action=alert.reviewed', { role: 'coordinator' })).json.items;
    expect(audit).toHaveLength(2);
    expect(audit[0].created_at >= audit[1].created_at).toBe(true);
  });
});

test('las fechas del libro único usan dd/mm/aaaa, h:mm a. m./p. m.', async ({ page }) => {
  await openAlerts(page, 'Vehículos');
  const cells = page.getByTestId('ledger').locator('tbody tr td:first-child');
  await expect(cells).toHaveCount(8);
  for (const cell of await cells.all()) await expect(cell).toHaveText(DATE_TIME);
});
