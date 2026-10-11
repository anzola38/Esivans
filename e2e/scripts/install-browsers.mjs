import { spawnSync } from 'node:child_process';
import './env.mjs';

// Descarga solo Chromium, dentro de e2e/node_modules.
const result = spawnSync('npx', ['playwright', 'install', 'chromium'], {
  stdio: 'inherit',
  shell: true,
  env: process.env,
});
process.exit(result.status ?? 1);
