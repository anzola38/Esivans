import {
  COUNTDOWN,
  DATE_TIME,
  api,
  countdownSeconds,
  expect,
  openRequest,
  referencePrefix,
  seedCase,
  simulatorOf,
  test,
  todayText,
} from './support/fixtures.mjs';

const CALCULATION = [
  ['Disponible', '25 % de nivel × 12,0 gal de capacidad', '3,00 gal'],
  ['Ruta pendiente', '6 servicios en EOM × 18 km típicos por servicio', '108 km'],
  ['Combustible para la ruta', '108 km ÷ 40,5 km/gal', '2,67 gal'],
  ['Reserva de ½ tanque', '½ × 12,0 gal', '6,00 gal'],
  ['Necesidad', 'mín(12,0; 2,67 + 6,00) gal', '8,67 gal'],
  ['A cargar', '8,67 − 3,00 gal', '5,67 gal'],
  ['Valor', '5,67 gal × $16.000 de referencia', '$90.667'],
  ['Redondeo', 'al múltiplo de $10.000 más cercano', '$90.000'],
  ['Tope del vehículo', '12,0 gal (capacidad registrada) × $16.000, hacia abajo al múltiplo de $10.000', '$190.000'],
  ['Valor sugerido', 'mín($90.000; $190.000)', '$90.000'],
];

test.describe('Consola: caso verde (VEH901)', () => {
  test('la cola arranca vacía y ofrece ir al simulador', async ({ page }) => {
    await page.goto('/consola');
    await expect(page.getByText('No hay solicitudes en la cola')).toBeVisible();
    await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 0\s*Verde: 0\s*Amarillo: 0\s*Rojo: 0/);
    await page.getByRole('link', { name: 'Ir al simulador' }).click();
    await expect(page).toHaveURL(/\/simulador$/);
  });

  test('la solicitud aparece en la cola en Verde, con $90.000 y el SLA en cuenta regresiva', async ({ page }) => {
    await page.goto('/consola');
    await expect(page.getByText('No hay solicitudes en la cola')).toBeVisible();

    // La cola se refresca sola: la solicitud llega sin recargar la página.
    const request = await seedCase('GREEN');
    const row = page.getByTestId('queue-row-' + request.id);
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute('data-plate', 'ZZA901');

    const cells = row.locator('td');
    await expect(cells.nth(0)).toHaveText(/^\s*Verde\s*· 0 puntos\s*$/);
    await expect(cells.nth(0).locator('app-traffic-light')).toHaveClass(/ui-badge--green/);
    await expect(cells.nth(1)).toContainText('ZZA901');
    await expect(cells.nth(1)).toContainText('VEH901 · Gasolina');
    await expect(cells.nth(2)).toHaveText('Carlos Andrés Pérez');
    await expect(cells.nth(3)).toHaveText('En revisión');
    await expect(cells.nth(4)).toHaveText('9:40 a. m.');
    await expect(cells.nth(5)).toHaveText(COUNTDOWN);
    await expect(cells.nth(7)).toHaveText(/^\s*\$90\.000\s*Sugerido\s*$/);
    await expect(cells.nth(8).getByRole('link', { name: 'Revisar' })).toBeVisible();

    await expect(page.getByTestId('queue-counts')).toHaveText(/Por decidir: 1\s*Verde: 1\s*Amarillo: 0\s*Rojo: 0/);
    await expect(page.getByText('1 solicitud hoy')).toBeVisible();

    // SLA de 10 minutos: empieza por debajo de 10:00 y baja segundo a segundo.
    const sla = cells.nth(6);
    await expect(sla).toHaveText(/^\s*0\d:[0-5]\d\s*$/);
    const first = countdownSeconds(await sla.textContent());
    expect(first).toBeGreaterThan(480);
    expect(first).toBeLessThanOrEqual(600);
    await expect.poll(async () => countdownSeconds(await sla.textContent())).toBeLessThan(first);

    await row.click();
    await expect(page).toHaveURL(new RegExp('/consola/' + request.id + '$'));
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');
  });

  test('el detalle muestra foto, lectura con confianza, libro único, «Sin alertas» y el cálculo en 10 pasos', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);

    // Cabecera
    await expect(page.getByTestId('detail-light')).toHaveText(/^\s*Verde\s*· 0 puntos\s*$/);
    await expect(page.getByTestId('detail-stage')).toHaveText('En revisión');
    await expect(page.getByTestId('detail-amount')).toHaveText('$90.000');
    await expect(page.locator('.det__value-label')).toHaveText('Valor sugerido');
    await expect(page.getByTestId('detail-sla')).toHaveText(/SLA: quedan 0\d:[0-5]\d/);
    const meta = page.locator('.det__meta');
    await expect(meta).toContainText('Solicitud n.º ' + request.id);
    await expect(meta).toContainText('Carlos Andrés Pérez');
    await expect(meta).toContainText('VEH901 · Gasolina');
    await expect(meta).toContainText('Pedida a las 9:40 a. m.');
    await expect(page.getByTestId('read-only')).toHaveCount(0);

    // Foto y lectura
    const evidence = page.getByTestId('evidence-card');
    await expect(evidence).toContainText('Leído por la IA');
    const photo = evidence.getByRole('img', { name: 'Foto del tablero enviada por el conductor' });
    await expect(photo).toHaveAttribute('src', '/api/media/media-veh901');
    await expect.poll(() => photo.evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(page.getByTestId('odometer')).toHaveText('48.352 km');
    const readings = evidence.locator('.det__read');
    await expect(readings.nth(0)).toContainText('Confianza 97 %');
    await expect(readings.nth(1)).toContainText('Nivel (25 %)');
    await expect(readings.nth(1)).toContainText('¼ de tanque');
    await expect(readings.nth(1)).toContainText('Confianza 92 %');
    await expect(evidence).toContainText('Fuente: foto del tablero. Confirmado por el conductor.');
    await expect(page.getByTestId('odometer-correction')).toHaveCount(0);

    // La foto se amplía en un diálogo y se cierra con Escape.
    await evidence.getByTitle('Ampliar la foto').click();
    await expect(page.getByRole('dialog', { name: 'Foto del tablero' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // Libro único
    const ledger = page.getByTestId('ledger-card');
    await expect(ledger).toContainText('Libro único de tanqueos');
    await expect(ledger).toContainText('Todos los proveedores y EOM');
    const facts = ledger.locator('.det__fact');
    await expect(facts.nth(0)).toContainText('Último tanqueo');
    await expect(facts.nth(0)).toContainText('$80.000 · 5 gal');
    await expect(facts.nth(0)).toContainText('Terpel · EDS Cereté Norte');
    await expect(facts.nth(0)).toContainText('Gasolina Corriente');
    await expect(facts.nth(1)).toContainText('142 km');
    await expect(facts.nth(1)).toContainText('desde el último tanqueo');
    await expect(facts.nth(2)).toContainText('Servicios de hoy en EOM');
    await expect(facts.nth(2)).toContainText(/6 pendientes de \d+/);
    await expect(facts.nth(2)).toContainText('Próximo: 10:30 a. m.');
    await expect(facts.nth(2)).toContainText('Montería → Planeta Rica');
    await expect(page.getByTestId('efficiency')).toContainText('Rendimiento frente a su grupo (Gasolina)');
    await expect(page.getByTestId('efficiency')).toContainText('En su rango');
    await expect(page.getByTestId('vehicle-flags')).toContainText('Sin banderas activas para este vehículo.');

    // Razones
    const reasons = page.getByTestId('reasons-card');
    await expect(reasons).toContainText('0 puntos · reglas v1');
    await expect(page.getByTestId('no-alerts')).toContainText('Sin alertas');
    await expect(page.getByTestId('no-alerts')).toContainText('se puede aprobar en un clic');
    await expect(reasons.locator('.det__reason')).toHaveCount(0);

    // Cálculo paso a paso
    const calc = page.getByTestId('calc-card');
    await expect(calc).toContainText('Tope: $190.000');
    const steps = calc.locator('ol.det__calc > li');
    await expect(steps).toHaveCount(10);
    for (const [index, [label, formula, result]] of CALCULATION.entries()) {
      const step = steps.nth(index);
      await expect(step.locator('.det__calc-n')).toHaveText(String(index + 1));
      await expect(step.locator('.det__calc-label')).toHaveText(label);
      await expect(step.locator('.det__calc-formula')).toHaveText(formula);
      await expect(step.locator('.det__calc-result')).toHaveText(result);
    }
    await expect(calc).toContainText(
      'Control cruzado. Consumo desde el último tanqueo: 142 km ÷ 40,5 km/gal = 3,51 gal. Cuadra con el nivel leído.',
    );

    // Bitácora antes de decidir
    const audit = page.getByTestId('audit-card');
    await expect(audit.locator('tbody tr')).toHaveCount(3);
    await expect(audit.locator('[data-action="request.received"]')).toContainText(
      'Solicitud de Carlos Andrés Pérez para VEH901 (ZZA901) recibida por WhatsApp',
    );
    await expect(audit.locator('[data-action="evidence.read"]')).toContainText('Foto del tablero leída: 48.352 km');
    await expect(audit.locator('[data-action="request.evaluated"]')).toContainText(
      'Semáforo verde con 0 puntos (sin reglas); valor sugerido $90.000; reglas v1',
    );

    // Acciones
    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Ajustar' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Rechazar' })).toBeEnabled();
  });

  test('aprobar en un clic, habilitar con valores precargados y avisar al conductor', async ({ page }) => {
    const request = await seedCase('GREEN');
    const reference = referencePrefix() + '0001';
    await openRequest(page, request.id);

    // Un clic: sin cuadro de motivo.
    await page.getByRole('button', { name: 'Aprobar en un clic' }).click();
    const enablement = page.getByTestId('enablement');
    await expect(enablement).toContainText('Habilitar en el portal del proveedor');
    await expect(page.getByTestId('decision-form')).toHaveCount(0);
    await expect(enablement).toContainText('Aprobada por Laura Mendoza');
    await expect(enablement).toContainText('Copia estos valores en el portal de Terpel para habilitar el chip');
    await expect(page.getByTestId('detail-stage')).toHaveText('Por habilitar');
    await expect(page.locator('.det__value-label')).toHaveText('Valor autorizado');
    await expect(page.getByTestId('detail-amount')).toHaveText('$90.000');
    await expect(page.getByRole('button', { name: 'Aprobar en un clic' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Rechazar' })).toHaveCount(0);

    // Valores precargados
    const fields = enablement.locator('.det__field');
    await expect(fields.nth(0)).toHaveText(/^\s*Proveedor\s*Terpel\s*$/);
    await expect(fields.nth(1)).toHaveText(/^\s*Vehículo\s*ZZA901\s*$/);
    await expect(fields.nth(2)).toHaveText(/^\s*Valor\s*\$90\.000\s*$/);
    await expect(fields.nth(3)).toHaveText(/^\s*Producto\s*Gasolina Corriente\s*$/);
    await expect(fields.nth(4)).toHaveText(/^\s*Vigencia\s*2 horas\s*$/);
    const referenceInput = page.getByRole('textbox', { name: 'Referencia del portal' });
    await expect(referenceInput).toHaveValue(reference);

    // Copiar: el valor va sin formato, listo para pegar en el portal.
    // Windows hands the clipboard back with CRLF line endings.
    const clipboard = async () => (await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n');
    await enablement.getByRole('button', { name: 'Copiar placa' }).click();
    await expect(page.locator('.ui-toast').last()).toContainText('Placa en el portapapeles.');
    expect(await clipboard()).toBe('ZZA901');
    await enablement.getByRole('button', { name: 'Copiar valor' }).click();
    await expect(page.locator('.ui-toast').last()).toContainText('Valor en el portapapeles.');
    expect(await clipboard()).toBe('90000');
    await enablement.getByRole('button', { name: 'Copiar todo' }).click();
    await expect(page.locator('.ui-toast').last()).toContainText('Datos de la habilitación en el portapapeles.');
    expect(await clipboard()).toBe(
      ['Proveedor: Terpel', 'Placa: ZZA901', 'Valor: 90000', 'Producto: Gasolina Corriente', 'Vigencia: 2 horas'].join('\n'),
    );

    // El simulador ya refleja que falta habilitar.
    const pending = await api('/dev/simulator/conversations/573005550901');
    expect(pending.json.request.stage_label).toBe('Por habilitar');

    // Confirmar la referencia
    await enablement.getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByTestId('detail-stage')).toHaveText('Autorizada');
    await expect(page.getByTestId('enablement')).toHaveCount(0);
    const authorization = page.getByTestId('authorization');
    await expect(authorization).toContainText('Autorizada: $90.000 de Gasolina Corriente.');
    await expect(authorization).toContainText('Referencia ' + reference + ' en Terpel (chip), habilitada por Laura Mendoza.');
    await expect(authorization).toContainText('Vigencia: 2 horas (hasta las 11:4');
    await expect(page.locator('.ui-toast').last()).toContainText(
      'Habilitación confirmada: el conductor recibió valor, producto, referencia y vigencia.',
    );
    await expect(page.getByTestId('detail-sla')).toHaveCount(0);

    // Bitácora: quién, qué y cuándo.
    const audit = page.getByTestId('audit-card');
    await expect(audit.locator('tbody tr')).toHaveCount(5);
    const decision = audit.locator('[data-action="decision.approve"]');
    await expect(decision.locator('td').nth(0)).toHaveText(DATE_TIME);
    await expect(decision.locator('td').nth(0)).toContainText(todayText());
    await expect(decision.locator('td').nth(1)).toHaveText(/^\s*Laura Mendoza\s*Técnico de Control y Monitoreo\s*$/);
    await expect(decision.locator('td').nth(2)).toHaveText('Laura Mendoza aprobó la solicitud por $90.000 en un clic');
    await expect(decision.locator('td').nth(3)).toContainText('Valor sugerido: $90.000');
    await expect(decision.locator('td').nth(3)).toContainText('Semáforo: Verde');
    await expect(decision.locator('td').nth(4)).toContainText('Acción: Aprobar');
    await expect(decision.locator('td').nth(4)).toContainText('Valor: $90.000');
    await expect(decision.locator('td').nth(4)).toContainText('En un clic: Sí');
    await expect(decision.locator('td').nth(5)).toHaveText('v1');
    const enabled = audit.locator('[data-action="authorization.enabled"]');
    await expect(enabled.locator('td').nth(0)).toHaveText(DATE_TIME);
    await expect(enabled.locator('td').nth(1)).toContainText('Laura Mendoza');
    await expect(enabled.locator('td').nth(2)).toHaveText(
      'Laura Mendoza habilitó el chip en Terpel: $90.000 de Gasolina Corriente, referencia ' + reference + ', vigente 2 horas',
    );
    await expect(enabled.locator('td').nth(4)).toContainText('Referencia: ' + reference);

    // La cola la muestra autorizada, sin SLA pendiente.
    await page.getByRole('link', { name: 'Volver a la cola' }).click();
    const row = page.getByTestId('queue-row-' + request.id);
    await expect(row.locator('td').nth(3)).toHaveText('Autorizada');
    await expect(row.locator('td').nth(6)).toHaveText('Cerrada');
    await expect(row.locator('td').nth(7)).toHaveText(/^\s*\$90\.000\s*Autorizado\s*$/);
    await expect(page.getByTestId('queue-counts')).toContainText('Por decidir: 0');
    await row.getByRole('link', { name: 'Ver' }).click();

    // De vuelta en el simulador: el conductor recibe valor, producto, referencia y vigencia.
    await page.getByRole('link', { name: 'Ver el mensaje al conductor' }).click();
    await expect(page).toHaveURL(/\/simulador\?wa=573005550901$/);
    const sim = simulatorOf(page);
    await expect(page.getByTestId('case-plate')).toHaveText('ZZA901');
    await expect(sim.lastAssistantBubble).toHaveAttribute('data-kind', 'authorization');
    await expect(sim.lastAssistantBubble).toContainText(
      'Autorizado, Carlos: $90.000 de Gasolina Corriente. Referencia: ' + reference + '. Vigencia: 2 horas (hasta las 11:4',
    );
    await expect(sim.lastAssistantBubble).toContainText('Tu chip ya está habilitado solo por ese valor.');
    await expect(sim.stage).toHaveText('Autorizada');
    await expect(sim.step('in_review')).toHaveAttribute('data-state', 'done');
    await expect(sim.step('authorized')).toHaveAttribute('data-state', 'done');
    await expect(sim.step('authorized')).toContainText('Chip habilitado por Laura Mendoza, referencia ' + reference);
    await expect(page.getByTestId('authorization-summary')).toContainText('$90.000 de Gasolina Corriente.');
    await expect(page.getByTestId('authorization-summary')).toContainText('Referencia ' + reference + '. Vigencia: 2 horas');
    await expect(page.locator('.sim__summary')).toContainText('Valor autorizado');
    await expect(page.getByTestId('pending')).toHaveCount(0);
  });

  test('la referencia del portal es obligatoria para confirmar la habilitación', async ({ page }) => {
    const request = await seedCase('GREEN');
    await openRequest(page, request.id);
    await page.getByRole('button', { name: 'Aprobar en un clic' }).click();

    const referenceInput = page.getByRole('textbox', { name: 'Referencia del portal' });
    await referenceInput.fill('');
    await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByText('Escribe la referencia que entrega el portal (3 a 60 caracteres).')).toBeVisible();
    await expect(page.getByTestId('detail-stage')).toHaveText('Por habilitar');
    expect((await api('/requests/' + request.id)).json.authorization).toBeNull();

    // Con una referencia escrita a mano se habilita con ese texto.
    await referenceInput.fill('PORTAL-778899');
    await page.getByTestId('enablement').getByRole('button', { name: 'Confirmar' }).click();
    await expect(page.getByTestId('authorization')).toContainText('Referencia PORTAL-778899 en Terpel');
    expect((await api('/requests/' + request.id)).json.authorization.reference).toBe('PORTAL-778899');
  });
});
