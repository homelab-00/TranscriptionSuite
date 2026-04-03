import { test, _electron as electron } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

const DASHBOARD_PATH = path.resolve(__dirname, '../../dashboard');
const DEFAULT_OUTPUT = path.resolve(
  __dirname,
  '../../../TypeScript_Projects/TranscriptionSuite_Webpage/src/assets/screenshots'
);

const OUTPUT_DIR = process.env.SCREENSHOT_OUTPUT_DIR || DEFAULT_OUTPUT;

// Each screenshot: a name and a function describing how to navigate to that state.
const screenshots: Array<{
  name: string;
  navigate: (page: import('@playwright/test').Page) => Promise<void>;
}> = [
  {
    name: 'hero',
    navigate: async (page) => {
      // Session view is the default — just wait for it to load
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-longform',
    navigate: async (page) => {
      // Session view with transcription result — click Session tab
      await page.click('[data-testid="nav-session"], text=Session');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-live',
    navigate: async (page) => {
      // Session view — Live Mode section is visible by default
      await page.click('[data-testid="nav-session"], text=Session');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-notebook',
    navigate: async (page) => {
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-diarization',
    navigate: async (page) => {
      // Navigate to notebook, then open a note if one exists
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-multibackend',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-remote',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-crossplatform',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-lmstudio',
    navigate: async (page) => {
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
];

test('capture all landing page screenshots', async () => {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const electronApp = await electron.launch({
    args: [path.join(DASHBOARD_PATH, 'dist-electron/main.js')],
    cwd: DASHBOARD_PATH,
  });

  const page = await electronApp.firstWindow();
  await page.waitForLoadState('networkidle');
  // Give the app a moment to render fully
  await page.waitForTimeout(2000);

  for (const shot of screenshots) {
    await shot.navigate(page);
    await page.waitForTimeout(500); // settle time
    await page.screenshot({
      path: path.join(OUTPUT_DIR, `${shot.name}.png`),
      type: 'png',
    });
  }

  await electronApp.close();
});
