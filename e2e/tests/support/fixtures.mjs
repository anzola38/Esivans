// Shared fixtures and helpers of the E2E suite.
//
// Every test starts from a freshly reset demo and fails if the browser logs a JavaScript error
// or receives an HTTP 4xx/5xx that the test did not declare with `guard.allow(...)`.
import { expect, test as base } from '@playwright/test';
import { BASE_URL } from '../../scripts/env.mjs';

export { expect };

export const API_URL = BASE_URL + '/api';
export const FOOTER = 'Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección';

export const SCREENS = [
  { path: '/simulador', title: 'Simulador del conductor' },
  { path: '/consola', title: 'Consola del técnico' },
  { path: '/alertas', title: 'Alertas del coordinador' },
  { path: '/tablero', title: 'Tablero del piloto' },
];

export const ROLES = {
  technician: { label: 'Técnico de Control y Monitoreo', user: 'Laura Mendoza' },
  coordinator: { label: 'Coordinador', user: 'Carlos Rivas' },
  finance: { label: 'Finanzas', user: 'Marta Salcedo' },
  support: { label: 'Soporte', user: 'Diego Paternina' },
};

export const CASES = {
  GREEN: { waId: '573005550901', plate: 'ZZA901', vehicle: 'VEH901', driver: 'Carlos Andrés Pérez' },
  VEH015: { waId: '573005550015', plate: 'ZZA015', vehicle: 'VEH015', driver: 'Jorge Iván Castaño' },
  VEH199: { waId: '573005550199', plate: 'ZZA199', vehicle: 'VEH199', driver: 'Wilson Darío Hoyos' },
  NO_FUEL: { waId: '573005550902', plate: 'ZZA902', vehicle: 'VEH902', driver: 'Luis Fernando Ortega' },
  UNREGISTERED: { waId: '573009990000', plate: null, vehicle: null, driver: 'Número no registrado' },
};

// ---------- Formats (es-CO) ----------

// Playwright normalises non-breaking spaces to plain spaces when it matches text.
/** dd/mm/aaaa, h:mm a. m. */
export const DATE_TIME = /^\d{2}\/\d{2}\/\d{4}, (?:[1-9]|1[0-2]):[0-5]\d\s[ap]\.\sm\.$/;
/** h:mm a. m. */
export const TIME = /^(?:[1-9]|1[0-2]):[0-5]\d\s[ap]\.\sm\.$/;
/** mm:ss of a countdown */
export const COUNTDOWN = /\b0\d:[0-5]\d\b/;

function bogotaParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Bogota',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

/** Today in Bogota as dd/mm/aaaa. */
export function todayText() {
  const p = bogotaParts();
  return p.day + '/' + p.month + '/' + p.year;
}

/** Prefix of the references the backend suggests today: TER-aammdd-. */
export function referencePrefix() {
  const p = bogotaParts();
  return 'TER-' + p.year.slice(2) + p.month + p.day + '-';
}

/** "09:41" -> 581 seconds. */
export function countdownSeconds(text) {
  const match = /(\d{2}):(\d{2})/.exec(text ?? '');
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

// ---------- API helpers (Node side: they do not go through the browser) ----------

export async function api(path, { method = 'GET', body, role = 'technician' } = {}) {
  const response = await fetch(API_URL + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-Role': role,
      'X-Demo-User': encodeURIComponent(ROLES[role].user),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* not JSON (the sample CSV) */
  }
  return { status: response.status, json, text };
}

export async function resetDemo() {
  const response = await api('/dev/reset', { method: 'POST' });
  expect(response.status, 'POST /api/dev/reset').toBe(200);
  return response.json;
}

export async function conversation(waId) {
  return (await api('/dev/simulator/conversations/' + waId)).json;
}

/** Sends one driver message through the simulator endpoint and waits for the assistant's answer. */
export async function sendDriverMessage(caseCode, step) {
  const waId = CASES[caseCode].waId;
  const before = ((await conversation(waId))?.messages ?? []).length;
  const sent = await api('/dev/simulator/messages', { method: 'POST', body: { case_code: caseCode, ...step } });
  expect(sent.status, 'POST /api/dev/simulator/messages').toBe(200);
  await expect
    .poll(
      async () => {
        const current = await conversation(waId);
        const last = current.messages.at(-1);
        return current.messages.length > before + 1 && !current.assistant_typing && last?.direction === 'outbound';
      },
      { message: 'el asistente responde al mensaje de ' + caseCode, intervals: [100, 150, 250] },
    )
    .toBe(true);
}

/** Runs the whole script of a demo case against the API. Returns the request it created. */
export async function seedCase(caseCode) {
  const cases = (await api('/dev/simulator/cases')).json.items;
  const script = cases.find((item) => item.code === caseCode).script;
  for (const step of script) await sendDriverMessage(caseCode, step);
  return (await conversation(CASES[caseCode].waId)).request;
}

/** Approves (or adjusts) and enables a seeded request through the API. Returns the detail. */
export async function authorizeViaApi(requestId, decision = { action: 'approve' }, role = 'technician') {
  const decided = await api('/requests/' + requestId + '/decision', { method: 'POST', body: decision, role });
  expect(decided.status, 'POST /decision').toBe(200);
  const enabled = await api('/requests/' + requestId + '/authorization', {
    method: 'POST',
    body: { reference: decided.json.enablement.suggested_reference },
    role,
  });
  expect(enabled.status, 'POST /authorization').toBe(200);
  return enabled.json;
}

export async function importSampleViaApi(role = 'coordinator') {
  const csv = (await api('/dev/samples/terpel')).text;
  const imported = await api('/integrations/terpel/imports', {
    method: 'POST',
    body: { filename: 'terpel_ejemplo.csv', content: csv },
    role,
  });
  expect(imported.status, 'POST /integrations/terpel/imports').toBe(200);
  return imported.json;
}

/** Decisions recorded in the audit log of a request (approve, adjust or reject). */
export async function decisionEntries(requestId) {
  const audit = (await api('/audit?request_id=' + requestId + '&action=decision')).json.items;
  return audit.filter((entry) => entry.action.startsWith('decision.'));
}

// ---------- Browser guard ----------

export const test = base.extend({
  /**
   * Auto fixture: resets the demo before the test and, after it, fails on JavaScript errors,
   * console errors and HTTP 4xx/5xx responses that were not allowed with `guard.allow(/.../)`.
   */
  guard: [
    async ({ page }, use) => {
      await resetDemo();
      const problems = [];
      const allowed = [];
      page.on('pageerror', (error) => problems.push('pageerror: ' + error.message));
      page.on('console', (message) => {
        // A failed request is reported once, by the response listener below.
        if (message.type() === 'error' && !message.text().startsWith('Failed to load resource')) {
          problems.push('console: ' + message.text());
        }
      });
      page.on('response', (response) => {
        if (response.status() >= 400) {
          const url = new URL(response.url());
          problems.push('http ' + response.status() + ' ' + response.request().method() + ' ' + url.pathname);
        }
      });
      const guard = {
        /** Declares an expected problem, e.g. guard.allow(/^http 404 GET \/api\/requests\/999$/). */
        allow: (pattern) => allowed.push(pattern),
        problems: () => problems.filter((problem) => !allowed.some((pattern) => pattern.test(problem))),
      };
      await use(guard);
      expect(guard.problems(), 'errores de JavaScript o respuestas HTTP inesperadas').toEqual([]);
    },
    { auto: true },
  ],
});

// ---------- Shell ----------

export async function selectRole(page, role) {
  await page.getByRole('combobox', { name: 'Rol' }).selectOption(role);
  await expect(page.locator('.role-picker__label')).toContainText(ROLES[role].user);
}

export async function openMenu(page, title) {
  await page.getByRole('navigation', { name: 'Navegación principal' }).getByRole('link', { name: title }).click();
  await expect(page.locator('h1.topbar__title')).toHaveText(title);
}

// ---------- Simulator ----------

export function simulatorOf(page) {
  const chat = page.locator('.ui-phone__body');
  const driverBubbles = chat.locator('.ui-bubble--out');
  const assistantBubbles = chat.locator('.ui-bubble:not(.ui-bubble--out):not(.sim__typing)');

  /** Waits until the driver has `count` messages and the assistant has answered the last one. */
  async function waitForReply(count) {
    await expect(driverBubbles).toHaveCount(count);
    await expect(page.getByTestId('typing')).toHaveCount(0);
    await expect(chat.locator('.ui-bubble').last()).not.toHaveClass(/ui-bubble--out/);
  }

  async function act(action) {
    const before = await driverBubbles.count();
    await action();
    await waitForReply(before + 1);
  }

  return {
    chat,
    driverBubbles,
    assistantBubbles,
    lastAssistantBubble: assistantBubbles.last(),
    stage: page.getByTestId('request-stage'),
    timeline: page.getByTestId('timeline'),
    pending: page.getByTestId('pending'),
    quickReplies: page.getByTestId('quick-replies'),
    step: (status) => page.getByTestId('timeline').locator('[data-status=' + status + ']'),
    waitForReply,
    /** Clicks "Siguiente paso del guion" and waits for the assistant. */
    nextScriptStep: () => act(() => page.getByRole('button', { name: 'Siguiente paso del guion' }).click()),
    /** Types in the chat box as the driver and sends with Enter. */
    type: (text) =>
      act(async () => {
        const input = page.getByRole('textbox', { name: 'Mensaje del conductor' });
        await input.fill(text);
        await input.press('Enter');
      }),
    attachPhoto: () =>
      act(() => page.getByRole('button', { name: 'Adjuntar la foto de ejemplo del tablero' }).click()),
    quickReply: (text) => act(() => page.getByTestId('quick-replies').getByRole('button', { name: text }).click()),
    async selectCase(code) {
      await page.getByTestId('case-' + code).click();
      await expect(page.getByTestId('case-' + code)).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByTestId('case-driver')).toHaveText(CASES[code].driver);
    },
  };
}

export async function openSimulator(page) {
  await page.goto('/simulador');
  await expect(page.getByTestId('case-driver')).toBeVisible();
  return simulatorOf(page);
}

// ---------- Console ----------

export async function openRequest(page, requestId) {
  await page.goto('/consola/' + requestId);
  await expect(page.getByTestId('detail-plate')).toBeVisible();
}

// ---------- Layout and text checks ----------

/** The document never needs a horizontal scrollbar, and neither does the routed content. */
export async function expectNoHorizontalOverflow(page, label) {
  const size = await page.evaluate(() => {
    const doc = document.documentElement;
    const content = document.querySelector('main.content');
    return {
      docScroll: doc.scrollWidth,
      docClient: doc.clientWidth,
      contentScroll: content ? content.scrollWidth : 0,
      contentClient: content ? content.clientWidth : 0,
    };
  });
  expect(size.docScroll, label + ': scrollWidth del documento').toBeLessThanOrEqual(size.docClient);
  expect(size.contentScroll, label + ': scrollWidth del contenido').toBeLessThanOrEqual(size.contentClient);
}

/** Text the presenter can read right now (rendered text, without hidden nodes). */
export async function visibleText(page) {
  return (await page.evaluate(() => document.body.innerText)).replace(/ /g, ' ');
}

// Raw backend values and English UI words that must never reach the screen.
// Words that are also Spanish (error, manual, no, chip) are left out on purpose.
const RAW_TOKENS = [
  'in_review', 'awaiting_evidence', 'pending_enablement', 'received', 'identified', 'ready', 'authorized',
  'rejected', 'cancelled', 'green', 'yellow', 'red', 'high', 'medium', 'low', 'open', 'reviewed', 'refuel',
  'vehicle', 'reconciliation', 'confirmed', 'justified', 'data_error', 'approve', 'adjust', 'reject',
  'technician', 'coordinator', 'finance', 'support', 'illustrative', 'met', 'at_risk', 'not_met', 'no_data',
  'gasoline', 'diesel_light', 'dual_fuel', 'cng', 'liquid', 'photo', 'seed', 'import', 'automatic',
  'review', 'before_authorization', 'changed_digit', 'null', 'undefined', 'NaN', 'true', 'false',
  'Invalid Date', 'object Object', 'Loading', 'Submit', 'Cancel', 'Save', 'Close', 'Search',
  'Request', 'Requests', 'Driver', 'Status', 'Amount', 'Reason', 'Approve', 'Reject', 'Settings', 'Dashboard',
  'Alerts', 'Rules', 'Queue', 'Back', 'Next', 'Yes', 'No data', 'Not found', 'Pending', 'Today',
];

/** Raw states (in_review, green...) and English words found in the visible text. */
export function findRawTokens(text) {
  return RAW_TOKENS.filter((token) => {
    // Case-sensitive on purpose: the backend values are lower case, the English labels capitalised.
    return new RegExp('(?<![\\p{L}\\p{N}_])' + token.replace(/ /g, '\\s') + '(?![\\p{L}\\p{N}_])', 'u').test(text);
  });
}

/** es-CO format violations found in the visible text. */
export function findFormatViolations(text) {
  const rules = [
    ['pesos sin separador de miles', /\$\s?\d{4,}/g],
    ['pesos con decimales', /\$\s?\d{1,3}(?:\.\d{3})+,\d+/g],
    ['miles con coma', /\b\d{1,3},\d{3},\d{3}\b/g],
    ['decimales con punto', /(?<![\d.,/:-])\d+\.\d{1,2}(?![\d.,])(?= ?(?:%|km|gal|m³|min|h\b|puntos|veces))/g],
    ['porcentaje sin espacio', /\d%/g],
    ['fecha ISO', /\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?/g],
    ['fecha que no es dd/mm/aaaa', /(?<![\d/])(?:\d\/\d{1,2}\/\d{2,4}|\d{2}\/\d\/\d{2,4}|\d{2}\/\d{2}\/\d{2})(?![\d/])/g],
    ['hora de 12 h en inglés', /\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)\b/g],
  ];
  const found = [];
  for (const [name, pattern] of rules) {
    for (const match of text.matchAll(pattern)) found.push(name + ': "' + match[0] + '"');
  }
  return found;
}

/** Every traffic light and every status dot carries a readable label, never the colour alone. */
export async function expectTrafficLightsWithText(page) {
  const lights = await page
    .locator('app-traffic-light')
    .evaluateAll((nodes) => nodes.map((node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim()));
  for (const text of lights) expect(text, 'semáforo con texto').toMatch(/^(Verde|Amarillo|Rojo|Sin evaluar)/);
  const dots = await page
    .locator('.ui-badge__dot')
    .evaluateAll((nodes) => nodes.map((node) => (node.parentElement?.textContent ?? '').replace(/\s+/g, ' ').trim()));
  for (const text of dots) expect(text.length, 'color acompañado de texto').toBeGreaterThan(2);
  return lights.length;
}
