// The 3-minute script of the README, start to finish, only through the interface.
import {
  expect,
  expectNoHorizontalOverflow,
  openMenu,
  openSimulator,
  referencePrefix,
  selectRole,
  simulatorOf,
  test,
  todayText,
} from './support/fixtures.mjs';

test('guion completo de la demo: del mensaje del conductor al tablero', async ({ page }) => {
  test.setTimeout(180_000);
  const prefix = referencePrefix();

  // Antes de empezar: rol técnico y cola vacía.
  await page.goto('/');
  await expect(page.getByRole('combobox', { name: 'Rol' })).toHaveValue('technician');

  // ---------- Paso 1: caso verde en el simulador ----------
  const sim = await openSimulator(page);
  await expect(page.getByTestId('case-plate')).toHaveText('ZZA901');
  for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
  await expect(sim.chat).toContainText('Hola, Carlos.');
  await expect(sim.chat).toContainText('Leí en la foto 48.352 km y nivel de ¼ de tanque (25 %).');
  await expect(sim.stage).toHaveText('En revisión');
  await expectNoHorizontalOverflow(page, 'simulador caso verde');

  // ---------- Paso 2: consola, aprobar en un clic y habilitar ----------
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await expect(page.getByTestId('detail-light')).toContainText('Verde');
  await expect(page.getByTestId('detail-amount')).toHaveText('$90.000');
  await expect(page.getByTestId('no-alerts')).toContainText('Sin alertas');
  await expect(page.getByTestId('calc-card').locator('ol.det__calc > li')).toHaveCount(10);
  await expectNoHorizontalOverflow(page, 'consola detalle verde');

  await page.getByRole('button', { name: 'Aprobar en un clic' }).click();
  await expect(page.getByRole('textbox', { name: 'Referencia del portal' })).toHaveValue(prefix + '0001');
  await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
  const audit = page.getByTestId('audit-card');
  await audit.scrollIntoViewIfNeeded();
  await expect(audit.locator('[data-action="decision.approve"]')).toContainText('Laura Mendoza aprobó la solicitud por $90.000 en un clic');
  await expect(audit.locator('[data-action="decision.approve"]')).toContainText(todayText());
  await expect(audit.locator('[data-action="decision.approve"] td').last()).toHaveText('v1');

  await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
  await expect(simulatorOf(page).lastAssistantBubble).toContainText(
    'Autorizado, Carlos: $90.000 de Gasolina Corriente. Referencia: ' + prefix + '0001. Vigencia: 2 horas',
  );

  // ---------- Paso 3: VEH015, el asistente propone 34.086 ----------
  await sim.selectCase('VEH015');
  for (let step = 0; step < 3; step += 1) await sim.nextScriptStep();
  await expect(sim.lastAssistantBubble).toContainText('En la foto leí 24.086 km');
  await expect(sim.lastAssistantBubble).toContainText('Tu último registro es de 33.948 km');
  await expect(sim.lastAssistantBubble).toContainText('¿El kilometraje correcto es 34.086 km?');
  await sim.quickReply('Sí, es 34.086');
  await expect(sim.stage).toHaveText('En revisión');
  await expect(page.locator('.sim__summary')).toContainText('Amarillo');
  // En el guion el VEH015 queda en la cola sin decidir.

  // ---------- Paso 4: VEH199 a las 11:14 p. m., ajustar con motivo ----------
  await sim.selectCase('VEH199');
  await expect(page.getByTestId('case-clock')).toHaveValue('23:14');
  for (let step = 0; step < 4; step += 1) await sim.nextScriptStep();
  await expect(sim.chat.locator('.ui-bubble__time').first()).toHaveText('11:14 p. m.');
  await page.getByRole('link', { name: 'Ver en la consola' }).click();
  await expect(page.getByTestId('detail-light')).toHaveText(/Rojo\s*· 7 puntos/);
  await expect(page.locator('[data-rule=R05] .det__reason-text')).toHaveText(
    'cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)',
  );
  await expect(page.locator('[data-rule=R08] .det__reason-text')).toHaveText('sin servicios con desplazamiento 24 h antes ni después');
  await expect(page.locator('[data-rule=R09] .det__reason-text')).toHaveText('tanqueo a las 23:14 sin servicios cercanos');
  await expectNoHorizontalOverflow(page, 'consola detalle rojo');

  await page.getByRole('button', { name: 'Ajustar' }).click();
  await page.getByRole('spinbutton', { name: 'Valor a autorizar (pesos)' }).fill('20000');
  await page.getByRole('button', { name: 'Apoyo nocturno confirmado con el coordinador' }).click();
  await page.getByRole('button', { name: 'Guardar ajuste' }).click();
  await expect(page.getByTestId('enablement')).toContainText('(sugerido $10.000)');
  await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByTestId('authorization')).toContainText('Autorizada: $20.000 de GNV.');
  await expect(page.getByTestId('authorization')).toContainText('Valor sugerido original: $10.000');

  // La cola muestra los tres casos: dos autorizados y el VEH015 por decidir.
  await openMenu(page, 'Consola del técnico');
  const queue = page.getByTestId('queue-table').locator('tbody tr');
  await expect(queue).toHaveCount(3);
  await expect(queue.first()).toHaveAttribute('data-plate', 'ZZA015');
  await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 1\s*Verde: 0\s*Amarillo: 1\s*Rojo: 0/);
  await expectNoHorizontalOverflow(page, 'consola cola');

  // ---------- Paso 5: coordinador, conciliación y alertas ----------
  await selectRole(page, 'coordinator');
  await openMenu(page, 'Alertas del coordinador');
  await page.getByRole('tab', { name: 'Conciliación' }).click();
  await page.getByRole('button', { name: 'Cargar exporte de ejemplo de Terpel' }).click();
  // 10 filas de la plantilla más una por cada autorización de Terpel hecha en la demo.
  await expect(page.getByTestId('import-rows')).toHaveText('12');
  await expect(page.getByTestId('import-imported')).toHaveText('12');
  await expect(page.getByTestId('import-alerts')).toHaveText('5');
  const matched = page.getByTestId('matched').locator('tbody tr');
  await expect(matched).toHaveCount(2);
  await expect(matched.filter({ hasText: 'VEH901' })).toContainText('Cuadra');
  await expect(matched.filter({ hasText: 'VEH199' })).toContainText('Cuadra');
  await expect(page.getByTestId('overpaid-vehicle')).toHaveText('VEH023');
  await expect(page.getByTestId('overpaid-amount')).toHaveText('$27.783');
  await expect(page.getByTestId('overpaid-card')).toContainText('$21.250 por galón');
  await expect(page.getByTestId('overpaid-card')).toContainText('$16.330 por galón');
  await expect(page.getByTestId('overpaid-math')).toContainText('5,647 galones');
  await expectNoHorizontalOverflow(page, 'alertas conciliación');

  await page.getByRole('tab', { name: 'Vehículos' }).click();
  await expect(page.getByTestId('alert-list').locator('.item').first()).toHaveAttribute('data-vehicle', 'VEH129');
  await expect(page.getByTestId('alert-points')).toHaveText('8 puntos');
  await expect(page.getByTestId('alert-reasons')).toContainText('61 % menos');
  await expect(page.getByTestId('alert-reasons')).toContainText('102 tanqueos por $4,1 M sin un solo servicio en EOM');
  await page.getByTestId('review').getByRole('radio', { name: 'Confirmado' }).click();
  await page.getByTestId('review').getByRole('button', { name: 'Registrar resultado' }).click();
  await expect(page.getByTestId('review-result')).toHaveText('Confirmado');
  await expect(page.getByTestId('review-author')).toHaveText('Carlos Rivas');
  await expect(page.getByTestId('review-closed').locator('.closed__who')).toContainText(todayText());
  await expect(page.getByTestId('review-closed').getByTestId('next-action').first()).toContainText('Revisión mecánica del vehículo');
  await expectNoHorizontalOverflow(page, 'alertas vehículos');

  // ---------- Paso 6: tablero ----------
  await openMenu(page, 'Tablero del piloto');
  await expect(page.getByTestId('indicators').locator('.kpi')).toHaveCount(9);
  await expect(page.getByTestId('context-chart').locator('.chart__value')).toHaveText(['66,7 h', '10 h']);
  await expect(page.getByTestId('kpi-one_click').locator('.kpi__value')).toHaveText('50 %');
  await expect(page.getByTestId('kpi-reconciliation').locator('.kpi__value')).toHaveText('100 %');
  await expect(page.getByTestId('kpi-attention_time').locator('.kpi__source')).toHaveText('Calculado con la demo');
  // Como dice el README: tras el guion la decisión es Ajustar, porque no todo se aprobó en un clic.
  await expect(page.getByTestId('verdict-label')).toHaveText('Ajustar');
  await expect(page.getByTestId('activity')).toHaveText(/Demo:\s*3\s*solicitudes ·\s*2\s*decisiones ·\s*9\s*alertas revisadas/);
  await expectNoHorizontalOverflow(page, 'tablero');
});
