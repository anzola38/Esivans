import { BASE_URL } from '../../scripts/env.mjs';

/** Leaves the demo clean for the presenter, with the AI provider configured by AI_PROVIDER again. */
export default async function globalTeardown() {
  const restored = await fetch(BASE_URL + '/api/dev/ai/restore', { method: 'POST' });
  if (!restored.ok) throw new Error('POST /api/dev/ai/restore respondio ' + restored.status);
  const response = await fetch(BASE_URL + '/api/dev/reset', { method: 'POST' });
  if (!response.ok) throw new Error('POST /api/dev/reset respondio ' + response.status);
}
