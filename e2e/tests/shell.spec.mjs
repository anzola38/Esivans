import {
  FOOTER,
  ROLES,
  SCREENS,
  expect,
  expectNoHorizontalOverflow,
  openMenu,
  seedCase,
  selectRole,
  test,
} from './support/fixtures.mjs';

const MENU = [
  { title: 'Simulador del conductor', hint: 'Chat con el asistente', path: '/simulador' },
  { title: 'Consola del técnico', hint: 'Cola, semáforo y decisión', path: '/consola' },
  { title: 'Alertas del coordinador', hint: 'Revisión y conciliación', path: '/alertas' },
  { title: 'Tablero del piloto', hint: 'Indicadores y metas', path: '/tablero' },
];

test.describe('Shell: rutas, menú y pie', () => {
  test('la ruta por defecto es el simulador', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/simulador$/);
    await expect(page.locator('h1.topbar__title')).toHaveText('Simulador del conductor');
  });

  test('una ruta desconocida vuelve al simulador sin romper la pantalla', async ({ page }) => {
    await page.goto('/esta-ruta-no-existe/123');
    await expect(page).toHaveURL(/\/simulador$/);
    await expect(page.locator('h1.topbar__title')).toHaveText('Simulador del conductor');
    await expect(page.getByTestId('footer')).toHaveText(FOOTER);
  });

  for (const screen of SCREENS) {
    test('carga ' + screen.path + ' con título, menú activo y pie exacto', async ({ page }) => {
      await page.goto(screen.path);
      await expect(page.locator('h1.topbar__title')).toHaveText(screen.title);
      await expect(page.getByTestId('footer')).toHaveText(FOOTER);
      await expect(page.getByTestId('footer')).toBeInViewport();

      const links = page.getByRole('navigation', { name: 'Navegación principal' }).getByRole('link');
      await expect(links).toHaveCount(4);
      await expect(page.locator('.nav-item__title')).toHaveText(MENU.map((item) => item.title));
      await expect(page.locator('.nav-item__hint')).toHaveText(MENU.map((item) => item.hint));
      await expect(page.locator('.nav-item.is-active')).toHaveCount(1);
      await expect(page.locator('.nav-item.is-active .nav-item__title')).toHaveText(screen.title);

      await expect(page.locator('.sidebar__name')).toHaveText('Suministro de combustible');
      await expect(page.locator('.sidebar__org')).toHaveText('Transportes Esivans S.A.S.');
      await expectNoHorizontalOverflow(page, screen.path);
    });
  }

  test('el menú lleva a las 4 pantallas y cada una conserva el pie', async ({ page }) => {
    await page.goto('/simulador');
    for (const item of [MENU[1], MENU[2], MENU[3], MENU[0]]) {
      await openMenu(page, item.title);
      await expect(page).toHaveURL(new RegExp(item.path + '$'));
      await expect(page.getByTestId('footer')).toHaveText(FOOTER);
    }
  });

  test('el pie es el mismo en el detalle de una solicitud y en la guía de estilo', async ({ page }) => {
    const request = await seedCase('GREEN');
    await page.goto('/consola/' + request.id);
    await expect(page.getByTestId('detail-plate')).toHaveText('ZZA901');
    await expect(page.getByTestId('footer')).toHaveText(FOOTER);

    await page.goto('/guia-estilo');
    await expect(page.locator('h1.topbar__title')).toHaveText('Guía de estilo');
    await expect(page.getByTestId('footer')).toHaveText(FOOTER);
  });

  test('una solicitud que no existe muestra el aviso y el enlace a la cola', async ({ page, guard }) => {
    guard.allow(/^http 404 GET \/api\/requests\/999$/);
    await page.goto('/consola/999');
    await expect(page.getByText('No existe esa solicitud')).toBeVisible();
    await expect(page.getByTestId('footer')).toHaveText(FOOTER);
    await page.getByRole('link', { name: 'Volver a la cola' }).click();
    await expect(page).toHaveURL(/\/consola$/);
    await expect(page.getByText('No hay solicitudes en la cola')).toBeVisible();
  });
});

test.describe('Shell: selector de rol', () => {
  test('ofrece los 4 roles y arranca como técnico', async ({ page }) => {
    await page.goto('/simulador');
    const select = page.getByRole('combobox', { name: 'Rol' });
    await expect(select.locator('option')).toHaveText([
      'Técnico de Control y Monitoreo',
      'Coordinador',
      'Finanzas',
      'Soporte',
    ]);
    await expect(select).toHaveValue('technician');
    await expect(page.locator('.role-picker__label')).toHaveText('Rol simulado · Laura Mendoza');
  });

  for (const role of ['coordinator', 'finance', 'support']) {
    test('el rol ' + role + ' se conserva al recargar y al cambiar de pantalla', async ({ page }) => {
      await page.goto('/simulador');
      await selectRole(page, role);
      await page.reload();
      await expect(page.getByRole('combobox', { name: 'Rol' })).toHaveValue(role);
      await expect(page.locator('.role-picker__label')).toHaveText('Rol simulado · ' + ROLES[role].user);

      await openMenu(page, 'Tablero del piloto');
      await expect(page.getByRole('combobox', { name: 'Rol' })).toHaveValue(role);
    });
  }

  test('las llamadas a /api llevan el rol y el usuario elegidos', async ({ page }) => {
    await page.goto('/simulador');
    await selectRole(page, 'coordinator');
    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/api/requests')),
      openMenu(page, 'Consola del técnico'),
    ]);
    expect(request.headers()['x-demo-role']).toBe('coordinator');
    expect(decodeURIComponent(request.headers()['x-demo-user'])).toBe('Carlos Rivas');
  });
});

test.describe('Shell: Reiniciar demo', () => {
  test('pide confirmación y cancelar no borra nada', async ({ page }) => {
    await seedCase('GREEN');
    await page.goto('/consola');
    await expect(page.getByTestId('queue-table').locator('tbody tr')).toHaveCount(1);

    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    const dialog = page.getByRole('dialog', { name: '¿Reiniciar la demo?' });
    await expect(dialog).toContainText('Se vuelve a cargar la semilla de datos ilustrativos.');
    await expect(dialog).toContainText('se reemplazan por el estado inicial');
    await dialog.getByRole('button', { name: 'Cancelar' }).click();

    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByTestId('queue-table').locator('tbody tr')).toHaveCount(1);
    await expect(page.getByTestId('queue-counts')).toContainText('Por decidir: 1');
  });

  test('al confirmar llama a POST /api/dev/reset y la cola queda vacía', async ({ page }) => {
    await seedCase('GREEN');
    await page.goto('/consola');
    await expect(page.locator('[data-plate=ZZA901]')).toContainText('Verde');

    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    const dialog = page.getByRole('dialog', { name: '¿Reiniciar la demo?' });
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith('/api/dev/reset') && r.request().method() === 'POST'),
      dialog.getByRole('button', { name: 'Reiniciar demo' }).click(),
    ]);
    expect(response.status()).toBe(200);

    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.ui-toast')).toContainText('Demo reiniciada');
    await expect(page.getByText('No hay solicitudes en la cola')).toBeVisible();
    await expect(page.getByTestId('queue-table')).toHaveCount(0);
    await expect(page.getByTestId('queue-counts')).toContainText('Por decidir: 0');
    await expect(page.getByText('0 solicitudes hoy')).toBeVisible();
    await expect(page.locator('h1.topbar__title')).toHaveText('Consola del técnico');
  });

  test('desde el simulador borra la conversación en curso', async ({ page }) => {
    await seedCase('GREEN');
    await page.goto('/simulador');
    await expect(page.getByTestId('request-stage')).toHaveText('En revisión');

    await page.getByRole('button', { name: 'Reiniciar demo' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Reiniciar demo' }).click();

    await expect(page.locator('.ui-toast')).toContainText('Demo reiniciada');
    await expect(page.locator('.ui-phone__body .ui-bubble')).toHaveCount(0);
    await expect(page.getByText('Aún no hay solicitud: empieza con el primer mensaje del conductor.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Siguiente paso del guion' })).toBeEnabled();
  });
});
