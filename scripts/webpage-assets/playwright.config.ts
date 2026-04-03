import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: ['capture-screenshots.ts', 'record-videos.ts'],
  timeout: 120_000,
  use: {
    trace: 'off',
  },
});
