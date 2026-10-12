import { BASE_URL } from '../../scripts/env.mjs';

/** Fails fast, with a clear message, when the stack is not running. */
export default async function globalSetup() {
  let health;
  try {
    const response = await fetch(BASE_URL + '/api/health');
    health = await response.json();
  } catch (error) {
    throw new Error(
      'No hay respuesta en ' + BASE_URL + '/api/health. Levanta el stack con "docker compose up -d --build". ' + error,
    );
  }
  if (health.status !== 'ok' || health.database !== 'ok') {
    throw new Error('El backend no esta sano: ' + JSON.stringify(health));
  }
  if (!health.demo_mode) {
    throw new Error('Las pruebas necesitan DEMO_MODE=true (usan POST /api/dev/reset y el simulador).');
  }
}
