import { test, _electron as electron } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

const DASHBOARD_PATH = path.resolve(__dirname, '../../dashboard');
const DEFAULT_OUTPUT = path.resolve(__dirname, 'output/videos');

const OUTPUT_DIR = process.env.VIDEO_OUTPUT_DIR || DEFAULT_OUTPUT;

async function recordSession(
  name: string,
  actions: (page: import('@playwright/test').Page) => Promise<void>
) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const electronApp = await electron.launch({
    args: [path.join(DASHBOARD_PATH, 'dist-electron/main.js')],
    cwd: DASHBOARD_PATH,
    recordVideo: {
      dir: OUTPUT_DIR,
      size: { width: 1280, height: 720 },
    },
  });

  const page = await electronApp.firstWindow();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  await actions(page);

  await page.close(); // triggers video save
  await electronApp.close();

  // Rename the auto-generated video file to our desired name
  const files = fs.readdirSync(OUTPUT_DIR).filter((f: string) => f.endsWith('.webm'));
  const newest = files
    .map((f: string) => ({ f, mtime: fs.statSync(path.join(OUTPUT_DIR, f)).mtimeMs }))
    .sort((a: { mtime: number }, b: { mtime: number }) => b.mtime - a.mtime)[0];

  if (newest) {
    const dest = path.join(OUTPUT_DIR, `${name}.webm`);
    fs.renameSync(path.join(OUTPUT_DIR, newest.f), dest);
  }
}

test('record app tour video', async () => {
  await recordSession('tour', async (page) => {
    // Session tab — already here by default
    await page.waitForTimeout(3000);

    // Click Notebook tab
    await page.click('[data-testid="nav-notebook"], text=Notebook');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Click Server tab
    await page.click('[data-testid="nav-server"], text=Server');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Back to Session
    await page.click('[data-testid="nav-session"], text=Session');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });
});

test('record quickstart video', async () => {
  await recordSession('quickstart', async (page) => {
    // Server tab
    await page.click('[data-testid="nav-server"], text=Server');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Session tab
    await page.click('[data-testid="nav-session"], text=Session');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
  });
});
