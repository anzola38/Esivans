import { BASE_URL } from '../../scripts/env.mjs';

/** Leaves the demo clean for the presenter. */
export default async function globalTeardown() {
  const response = await fetch(BASE_URL + '/api/dev/reset', { method: 'POST' });
  if (!response.ok) throw new Error('POST /api/dev/reset respondio ' + response.status);
}
