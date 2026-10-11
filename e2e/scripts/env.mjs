// Chromium se guarda dentro de e2e/node_modules (no en el perfil del usuario),
// asi nada queda instalado de forma global en la maquina.
process.env.PLAYWRIGHT_BROWSERS_PATH = '0';

export const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8080';

export const VIEWPORTS = [
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1920x1080', width: 1920, height: 1080 },
];
