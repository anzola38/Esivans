import { expect, test } from '@playwright/test';

const FOOTER = 'Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección';

const SCREENS = [
  { path: '/simulador', title: 'Simulador del conductor' },
  { path: '/consola', title: 'Consola del técnico' },
  { path: '/alertas', title: 'Alertas del coordinador' },
  { path: '/tablero', title: 'Tablero del piloto' },
];

test('la ruta por defecto es el simulador', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/simulador$/);
});

for (const screen of SCREENS) {
  test('shell en ' + screen.path, async ({ page }) => {
    await page.goto(screen.path);
    await expect(page.locator('h1.topbar__title')).toHaveText(screen.title);
    await expect(page.getByTestId('footer')).toHaveText(FOOTER);
    await expect(page.locator('.nav-item')).toHaveCount(4);
    await expect(page.locator('.nav-item.is-active')).toContainText(screen.title);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  });
}

test('el rol se guarda y sobrevive a la recarga', async ({ page }) => {
  await page.goto('/simulador');
  await page.getByTestId('role-select').selectOption('coordinator');
  await page.reload();
  await expect(page.getByTestId('role-select')).toHaveValue('coordinator');
  await expect(page.locator('.role-picker__label')).toContainText('Carlos Rivas');
});

test('las llamadas a /api llevan el rol y el usuario de la demo', async ({ page }) => {
  await page.goto('/guia-estilo');
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes('/api/health')),
    page.getByRole('button', { name: 'Llamar a /api/health' }).click(),
  ]);
  expect(request.headers()['x-demo-role']).toBe('technician');
  expect(decodeURIComponent(request.headers()['x-demo-user'])).toBe('Laura Mendoza');
});

test('reiniciar demo pide confirmacion y llama a POST /api/dev/reset', async ({ page }) => {
  await page.goto('/simulador');
  await page.getByTestId('reset-demo').click();
  await expect(page.getByRole('dialog')).toContainText('Se vuelve a cargar la semilla');

  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith('/api/dev/reset') && r.method() === 'POST'),
    page.getByTestId('reset-demo-confirm').click(),
  ]);
  expect(request.method()).toBe('POST');

  // Con o sin backend, la pantalla sigue en pie y avisa con un toast.
  await expect(page.locator('.ui-toast')).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('h1.topbar__title')).toHaveText('Simulador del conductor');
});
