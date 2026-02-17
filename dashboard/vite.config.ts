import fs from 'fs';
import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const packageJsonPath = path.resolve(__dirname, 'package.json');
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8')) as { version?: string };
const appVersion = packageJson.version ?? '0.0.0';

/**
 * PostCSS plugin: strip Tailwind v4's @supports blocks that upgrade colors
 * from sRGB fallbacks to oklab color-mix / oklab gradient interpolation.
 *
 * Tailwind v4 emits two progressive-enhancement @supports wrappers:
 *   @supports (color: color-mix(in lab, red, red))           — opacity modifiers
 *   @supports (background-image: linear-gradient(in lab …))  — gradient interpolation
 *
 * Removing them forces the browser to use the sRGB fallback values that
 * Tailwind v4 already generates, matching Tailwind v3's color rendering.
 */
function stripOklabSupports(): import('postcss').Plugin {
  return {
    postcssPlugin: 'strip-oklab-supports',
    AtRule: {
      supports(atRule) {
        if (atRule.params.includes('in lab')) {
          atRule.remove();
        }
      },
    },
  };
}
stripOklabSupports.postcss = true as const;

export default defineConfig({
  // Use relative paths so Electron can load from file:// protocol
  base: './',
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
  },
  plugins: [react(), tailwindcss()],
  css: {
    postcss: {
      plugins: [stripOklabSupports()],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
