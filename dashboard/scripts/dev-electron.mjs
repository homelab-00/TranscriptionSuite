/**
 * Development script that:
 * 1. Starts Vite dev server
 * 2. Compiles Electron main/preload TypeScript
 * 3. Launches Electron once Vite is ready
 *
 * Usage: node scripts/dev-electron.mjs
 */

import { spawn } from 'child_process';

const VITE_PORT = 3000;

// 1. Start Vite dev server
const vite = spawn('npx', ['vite'], {
  stdio: ['ignore', 'pipe', 'pipe'],
  shell: true,
});

vite.stdout.on('data', (data) => process.stdout.write(`[vite] ${data}`));
vite.stderr.on('data', (data) => process.stderr.write(`[vite] ${data}`));

// 2. Compile Electron TS
const tsc = spawn('npx', ['tsc', '-p', 'electron/tsconfig.json'], {
  stdio: 'inherit',
  shell: true,
});

tsc.on('close', (code) => {
  if (code !== 0) {
    console.error('[electron] TypeScript compilation failed');
    vite.kill();
    process.exit(1);
  }

  console.log('[electron] TypeScript compiled, waiting for Vite...');

  // 3. Wait for Vite then launch Electron
  const waitAndLaunch = () => {
    fetch(`http://localhost:${VITE_PORT}/`)
      .then(() => {
        console.log('[electron] Vite ready, launching Electron...');
        const electron = spawn('npx', ['electron', '.'], {
          stdio: 'inherit',
          shell: true,
          env: { ...process.env, NODE_ENV: 'development' },
        });

        electron.on('close', () => {
          vite.kill();
          process.exit(0);
        });
      })
      .catch(() => {
        setTimeout(waitAndLaunch, 500);
      });
  };

  waitAndLaunch();
});

// Cleanup on exit
process.on('SIGINT', () => {
  vite.kill();
  process.exit(0);
});
