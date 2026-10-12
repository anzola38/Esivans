import { api, authorizeViaApi, expect, importSampleViaApi, seedCase, test } from './support/fixtures.mjs';

// name, target (Meta) and baseline (Línea base), in screen order.
const INDICATORS = [
  ['attention_time', 'Tiempo de atención', 'Mediana de 3 min o menos y 9 de cada 10 en 10 min o menos', '2 semanas de marcas de tiempo de WhatsApp; referencia del caso: 3 a 20 min'],
  ['one_click', 'Resueltas en un clic', '60 % o más; sin intervención desde la etapa 3, con la autoaprobación', 'Hoy 0 %: todo es manual'],
  ['complete_first_try', 'Completas al primer intento', '90 % o más', 'Muestra de 100 conversaciones etiquetadas'],
  ['reconciliation', 'Conciliación con el proveedor', '100 % conciliado en 24 h; diferencia de 5 % o menos en el 95 % de los casos', 'Hoy no es medible: no hay registro de lo autorizado'],
  ['high_priority_alerts', 'Alertas de prioridad alta', 'Revisadas en 48 h; precisión de 50 % o más', 'Prueba con datos históricos: 1.682 tanqueos con alerta en 90 días, 53 de prioridad alta'],
  ['integrations', 'Integraciones', 'Flujo de 99,5 % o más', 'Se mide desde el día 1'],
  ['technician_load', 'Carga del técnico', 'Espera en pico menor a 5 min', 'Solicitudes por hora pico y espera en cola'],
  ['assistant_usage', 'Uso del asistente', '80 % o más de las solicitudes', 'Se mide desde el día 1'],
  ['continuity', 'Continuidad', 'Cero vehículos sin combustible por causa del sistema', 'Se mide desde el día 1'],
];
const STATUS_TEXT = /^\s*(Cumple la meta|Cerca de la meta|No cumple|Sin datos todavía)\s*$/;
const SOURCE_TEXT = /^\s*(Calculado con la demo|Valor ilustrativo)\s*$/;

const kpi = (page, key) => page.getByTestId('kpi-' + key);
const value = (page, key) => kpi(page, key).locator('.kpi__value');
const source = (page, key) => kpi(page, key).locator('.kpi__source');
const status = (page, key) => kpi(page, key).locator('.ui-badge');

async function openDashboard(page) {
  await page.goto('/tablero');
  await expect(page.getByTestId('indicators').locator('.kpi')).toHaveCount(9);
}

test.describe('Tablero del piloto', () => {
  test('los 9 indicadores muestran valor, línea base, meta y estado con texto', async ({ page }) => {
    await openDashboard(page);
    const cards = page.getByTestId('indicators').locator('.kpi');
    await expect(cards.locator('.kpi__name')).toHaveText(INDICATORS.map(([, name]) => name));

    for (const [key, name, target, baseline] of INDICATORS) {
      const card = kpi(page, key);
      await expect(card.locator('.kpi__name')).toHaveText(name);
      await expect(card.locator('.kpi__ref dt')).toHaveText(['Meta', 'Línea base']);
      await expect(card.locator('.kpi__ref dd').nth(0)).toHaveText(target);
      await expect(card.locator('.kpi__ref dd').nth(1)).toHaveText(baseline);
      await expect(status(page, key)).toHaveText(STATUS_TEXT);
      await expect(source(page, key)).toHaveText(SOURCE_TEXT);
      await expect(value(page, key)).not.toHaveText('');
    }

    // Franja del piloto
    const pilot = page.locator('.pilot');
    await expect(pilot).toContainText('Piloto de 6 semanas');
    await expect(pilot).toContainText('Córdoba (CARIBE COR)');
    await expect(pilot).toContainText('59 vehículos');
    await expect(pilot).toContainText('66 tanqueos al día');
    await expect(pilot).toContainText('467 servicios al día');
  });

  test('recién reiniciada: valores ilustrativos donde no hay actividad y «Ampliar» como decisión', async ({ page }) => {
    await openDashboard(page);

    await expect(value(page, 'attention_time')).toHaveText('2,6 min');
    await expect(source(page, 'attention_time')).toHaveText('Valor ilustrativo');
    await expect(value(page, 'one_click')).toHaveText('64 %');
    await expect(source(page, 'one_click')).toHaveText('Valor ilustrativo');
    await expect(value(page, 'reconciliation')).toHaveText('Sin autorizaciones');
    await expect(status(page, 'reconciliation')).toHaveText('Sin datos todavía');
    await expect(value(page, 'high_priority_alerts')).toHaveText('Precisión 50 %');
    await expect(source(page, 'high_priority_alerts')).toHaveText('Calculado con la demo');
    await expect(status(page, 'high_priority_alerts')).toHaveText('Cerca de la meta');
    await expect(value(page, 'integrations')).toHaveText('99,7 %');
    await expect(source(page, 'integrations')).toHaveText('Valor ilustrativo');
    await expect(status(page, 'integrations')).toHaveText('Cumple la meta');
    await expect(value(page, 'technician_load')).toHaveText('3,4 min');
    await expect(source(page, 'technician_load')).toHaveText('Valor ilustrativo');
    await expect(value(page, 'continuity')).toHaveText('0 incidentes');
    await expect(source(page, 'continuity')).toHaveText('Valor ilustrativo');

    await expect(page.getByTestId('activity')).toHaveText(/Demo:\s*0\s*solicitudes ·\s*0\s*decisiones ·\s*8\s*alertas revisadas/);

    await expect(page.getByTestId('verdict-label')).toHaveText('Ampliar');
    await expect(page.getByTestId('verdict')).toContainText('Se cumplen los seis criterios de ampliación. (6 de 6)');
    await expect(page.getByTestId('option-expand')).toHaveClass(/is-active/);
    await expect(page.getByTestId('option-adjust')).not.toHaveClass(/is-active/);
    await expect(page.getByTestId('option-stop')).not.toHaveClass(/is-active/);
  });

  test('contexto: 66,7 horas de gestión al día frente a 10 con el MVP y 24 de turnos', async ({ page }) => {
    await openDashboard(page);
    await expect(page.getByText('De 66,7 a 10 horas de gestión al día')).toBeVisible();
    const chart = page.getByTestId('context-chart');
    await expect(chart.locator('.chart__value')).toHaveText(['66,7 h', '10 h']);
    await expect(chart.locator('.chart__label')).toHaveText([
      'Hoy: 200 solicitudes de 20 min',
      'Con el MVP: 3 min por solicitud',
    ]);
    await expect(chart.locator('.chart__ref-label')).toHaveText('24 h de turnos');
    // La barra de hoy es 6,67 veces la del MVP.
    const widths = await chart.locator('rect.chart__bar').evaluateAll((bars) => bars.map((bar) => Number(bar.getAttribute('width'))));
    expect(widths[0] / widths[1]).toBeCloseTo(6.67, 2);
    await expect(page.locator('.context__text')).toContainText(
      'Hoy, con 200 solicitudes al día de 20 minutos, la gestión suma 66,7 horas diarias frente a 24 horas de turnos; con 3 minutos por solicitud bajaría a 10 horas.',
    );
    await expect(page.locator('.context__text')).toContainText('Hoy son 2,8 veces las horas de turno disponibles.');
  });

  test('desviaciones abiertas por prioridad, regla y antigüedad', async ({ page }) => {
    await openDashboard(page);
    await expect(page.getByText('11 alertas sin revisar · 2 vencidas')).toBeVisible();
    const groups = page.getByTestId('open-deviations').locator('.dev__group');
    await expect(groups.locator('.dev__title')).toHaveText(['Por prioridad', 'Por regla', 'Por antigüedad']);

    const priority = groups.nth(0).locator('.tile');
    await expect(priority).toHaveText([/4\s*Alta · 48 h/, /6\s*Media · semana/, /1\s*Baja · semana/]);

    // Por regla: R05, R08 y V01 son las que más se repiten entre las abiertas.
    const rules = groups.nth(1).locator('.rule');
    const totals = await rules.evaluateAll((rows) =>
      rows.map((row) => [row.querySelector('.rule__code').textContent.trim(), Number(row.querySelector('.rule__total').textContent)]),
    );
    const open = (await api('/alerts?status=open')).json.items;
    const expected = {};
    for (const alert of open) for (const code of alert.rule_codes) expected[code] = (expected[code] ?? 0) + 1;
    expect(totals.length).toBeLessThanOrEqual(8);
    for (const [code, total] of totals) expect(total, code).toBe(expected[code]);
    expect(Object.fromEntries(totals)).toMatchObject({ V01: 3, R05: 2, R08: 1 });
    for (let i = 1; i < totals.length; i += 1) expect(totals[i - 1][1]).toBeGreaterThanOrEqual(totals[i][1]);

    const age = groups.nth(2).locator('.tile');
    await expect(age.locator('.tile__label')).toHaveText(['Menos de 48 h', '2 a 7 días', 'Más de 7 días']);
    const ages = await age.locator('.tile__value').evaluateAll((tiles) => tiles.map((tile) => Number(tile.textContent)));
    expect(ages.reduce((sum, n) => sum + n, 0)).toBe(11);
  });

  test('el recuadro de decisión trae los tres textos del informe', async ({ page }) => {
    await openDashboard(page);
    await expect(page.getByText('Decisión al cierre de las 6 semanas')).toBeVisible();
    await expect(page.locator('.verdict__eyebrow')).toHaveText('Con los valores de hoy aplicaría');
    await expect(page.getByTestId('option-expand')).toHaveText(
      /Ampliar\s*Mediana de 3 min o menos, 90\s% o más de solicitudes completas, 60\s% o más en un clic, 80\s% o más por el asistente, precisión de alertas de 50\s% o más y ningún vehículo sin combustible\./,
    );
    await expect(page.getByTestId('option-adjust')).toHaveText(
      /Ajustar\s*Cualquier otro resultado, como una mediana entre 3 y 6 min, precisión entre 30 y 50\s% o adopción entre 50 y 80\s%: se corrige y se extiende 4 semanas\./,
    );
    await expect(page.getByTestId('option-stop')).toHaveText(
      /Detener\s*Cualquier vehículo sin combustible atribuible al sistema, un tiempo peor que la línea base después de 4 semanas o una adopción menor al 50\s%\./,
    );
    await expect(page.locator('.criteria li')).toHaveText([
      'Mediana de 3 min o menos',
      /90\s% o más completas/,
      /60\s% o más en un clic/,
      /80\s% o más por el asistente/,
      /Precisión de 50\s% o más/,
      '0 vehículos sin combustible',
    ]);
    await expect(page.locator('.criteria li.is-ok')).toHaveCount(6);
  });

  test('los valores «calculados con la demo» cambian al completar un caso, sin recargar', async ({ page }) => {
    await openDashboard(page);
    await expect(source(page, 'attention_time')).toHaveText('Valor ilustrativo');
    await expect(value(page, 'one_click')).toHaveText('64 %');

    // Caso verde completo: aprobado en un clic y habilitado.
    const green = await seedCase('GREEN');
    await authorizeViaApi(green.id);

    await expect(source(page, 'attention_time')).toHaveText('Calculado con la demo');
    await expect(value(page, 'attention_time')).toHaveText(/^0(,\d)? min$/);
    await expect(value(page, 'attention_time')).not.toHaveText('2,6 min');
    await expect(source(page, 'one_click')).toHaveText('Calculado con la demo');
    await expect(value(page, 'one_click')).toHaveText('100 %');
    await expect(status(page, 'one_click')).toHaveText('Cumple la meta');
    await expect(source(page, 'technician_load')).toHaveText('Calculado con la demo');
    await expect(value(page, 'complete_first_try')).toHaveText('100 %');
    await expect(value(page, 'assistant_usage')).toHaveText('100 %');
    await expect(value(page, 'reconciliation')).toHaveText('0 %');
    await expect(status(page, 'reconciliation')).toHaveText('No cumple');
    await expect(page.getByTestId('activity')).toHaveText(/Demo:\s*1\s*solicitudes ·\s*1\s*decisiones/);
    await expect(page.getByTestId('verdict-label')).toHaveText('Ampliar');
    // Los ilustrativos no se mueven.
    await expect(value(page, 'integrations')).toHaveText('99,7 %');
    await expect(source(page, 'integrations')).toHaveText('Valor ilustrativo');
    await expect(value(page, 'continuity')).toHaveText('0 incidentes');

    // Al conciliar el archivo del proveedor, la conciliación llega a 100 %.
    await importSampleViaApi();
    await expect(value(page, 'reconciliation')).toHaveText('100 %');
    await expect(status(page, 'reconciliation')).toHaveText('Cumple la meta');
    await expect(page.getByText('16 alertas sin revisar · 2 vencidas')).toBeVisible();

    // Un segundo caso, ajustado con motivo: baja «en un clic» a 50 % y la decisión pasa a Ajustar.
    const red = await seedCase('VEH199');
    await authorizeViaApi(red.id, { action: 'adjust', amount: 20000, reason: 'Apoyo nocturno confirmado con el coordinador' });
    await expect(value(page, 'one_click')).toHaveText('50 %');
    await expect(status(page, 'one_click')).toHaveText('Cerca de la meta');
    await expect(page.getByTestId('activity')).toHaveText(/Demo:\s*2\s*solicitudes ·\s*2\s*decisiones/);
    await expect(page.getByTestId('verdict-label')).toHaveText('Ajustar');
    await expect(page.getByTestId('option-adjust')).toHaveClass(/is-active/);
    await expect(page.getByTestId('option-expand')).not.toHaveClass(/is-active/);
    await expect(page.getByTestId('verdict')).toContainText('Algún criterio de ampliación todavía no se cumple: se corrige y se extiende 4 semanas. (5 de 6)');
    await expect(page.locator('.criteria li.is-ok')).toHaveCount(5);
    await expect(page.locator('.criteria li:not(.is-ok)')).toHaveText(/60\s% o más en un clic/);
  });

  test('el contador de «cumplen la meta» coincide con las tarjetas', async ({ page }) => {
    await openDashboard(page);
    const met = await page.getByTestId('indicators').locator('.kpi .ui-badge').filter({ hasText: 'Cumple la meta' }).count();
    expect(met).toBe(7);
    await expect(page.getByTestId('met-count')).toHaveText(met + ' de 9 cumplen la meta');
  });

  test('revisar una alerta de prioridad alta mueve su indicador', async ({ page }) => {
    await openDashboard(page);
    await expect(value(page, 'high_priority_alerts')).toHaveText('Precisión 50 %');
    const alert = (await api('/alerts?status=open&kind=vehicle')).json.items[0];
    expect(alert.vehicle.code).toBe('VEH129');
    const reviewed = await api('/alerts/' + alert.id, {
      method: 'PATCH',
      role: 'coordinator',
      body: { review_result: 'confirmed', comment: 'Confirmada con mantenimiento.' },
    });
    expect(reviewed.status).toBe(200);
    // 5 confirmadas de 9 revisadas = 56 %. La precisión ya cumple, pero quedan 2 de prioridad alta vencidas.
    await expect(value(page, 'high_priority_alerts')).toHaveText('Precisión 56 %');
    await expect(status(page, 'high_priority_alerts')).toHaveText('Cerca de la meta');
    await expect(page.getByText('10 alertas sin revisar · 2 vencidas')).toBeVisible();
    await expect(page.getByTestId('activity')).toHaveText(/9\s*alertas revisadas/);

    // Al revisar las dos vencidas ya no queda ninguna fuera de plazo: cumple la meta.
    const overdue = (await api('/alerts?status=open&priority=high')).json.items.filter((item) => item.overdue);
    expect(overdue.map((item) => item.vehicle.code).sort()).toEqual(['VEH015', 'VEH906']);
    for (const item of overdue) {
      const done = await api('/alerts/' + item.id, {
        method: 'PATCH',
        role: 'coordinator',
        body: { review_result: 'confirmed', comment: 'Confirmada fuera de plazo.' },
      });
      expect(done.status).toBe(200);
    }
    await expect(value(page, 'high_priority_alerts')).toHaveText('Precisión 64 %');
    await expect(status(page, 'high_priority_alerts')).toHaveText('Cumple la meta');
    await expect(page.getByText('8 alertas sin revisar · 0 vencidas')).toBeVisible();
  });
});
