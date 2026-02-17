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
  const COLOR_MIX_WITH_TRANSPARENT =
    /color-mix\(\s*in\s+srgb\s*,\s*((?:#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)))\s+([0-9.]+)%\s*,\s*transparent\s*\)/gi;

  const parseHexColor = (hex: string): { r: number; g: number; b: number; a: number } | null => {
    const value = hex.replace('#', '');
    if (![3, 4, 6, 8].includes(value.length)) return null;

    if (value.length === 3 || value.length === 4) {
      const r = parseInt(value[0] + value[0], 16);
      const g = parseInt(value[1] + value[1], 16);
      const b = parseInt(value[2] + value[2], 16);
      const a = value.length === 4 ? parseInt(value[3] + value[3], 16) / 255 : 1;
      return { r, g, b, a };
    }

    const r = parseInt(value.slice(0, 2), 16);
    const g = parseInt(value.slice(2, 4), 16);
    const b = parseInt(value.slice(4, 6), 16);
    const a = value.length === 8 ? parseInt(value.slice(6, 8), 16) / 255 : 1;
    return { r, g, b, a };
  };

  const parseRgbColor = (colorFn: string): { r: number; g: number; b: number; a: number } | null => {
    const match = colorFn.trim().match(/^rgba?\((.*)\)$/i);
    if (!match) return null;

    const args = match[1].trim();
    if (!args) return null;

    // Handle both comma and space/slash syntaxes.
    let parts: string[] = [];
    if (args.includes(',')) {
      parts = args.split(',').map((part) => part.trim());
    } else {
      parts = args.replace(/\s*\/\s*/, ' / ').split(/\s+/).filter(Boolean);
    }

    if (parts.length < 3) return null;

    const parseChannel = (value: string): number | null => {
      const normalized = value.trim();
      if (normalized.endsWith('%')) {
        const numeric = Number.parseFloat(normalized.slice(0, -1));
        if (!Number.isFinite(numeric)) return null;
        return Math.max(0, Math.min(255, Math.round((numeric / 100) * 255)));
      }
      const numeric = Number.parseFloat(normalized);
      if (!Number.isFinite(numeric)) return null;
      return Math.max(0, Math.min(255, Math.round(numeric)));
    };

    const parseAlpha = (value: string): number | null => {
      const normalized = value.trim();
      if (normalized.endsWith('%')) {
        const numeric = Number.parseFloat(normalized.slice(0, -1));
        if (!Number.isFinite(numeric)) return null;
        return Math.max(0, Math.min(1, numeric / 100));
      }
      const numeric = Number.parseFloat(normalized);
      if (!Number.isFinite(numeric)) return null;
      return Math.max(0, Math.min(1, numeric));
    };

    const r = parseChannel(parts[0]);
    const g = parseChannel(parts[1]);
    const b = parseChannel(parts[2]);
    if (r === null || g === null || b === null) return null;

    let a = 1;
    if (parts.length >= 4) {
      if (parts[3] === '/') {
        if (parts.length < 5) return null;
        const alpha = parseAlpha(parts[4]);
        if (alpha === null) return null;
        a = alpha;
      } else {
        const alpha = parseAlpha(parts[3]);
        if (alpha === null) return null;
        a = alpha;
      }
    }

    return { r, g, b, a };
  };

  const parseColor = (input: string): { r: number; g: number; b: number; a: number } | null => {
    const color = input.trim();
    if (color.startsWith('#')) return parseHexColor(color);
    if (/^rgba?\(/i.test(color)) return parseRgbColor(color);
    return null;
  };

  const formatAlpha = (alpha: number): string => {
    const rounded = Math.max(0, Math.min(1, alpha));
    // Avoid long float tails while preserving visible precision for subtle layers.
    return Number(rounded.toFixed(4)).toString();
  };

  return {
    postcssPlugin: 'strip-oklab-supports',
    AtRule: {
      supports(atRule) {
        if (atRule.params.includes('in lab') || atRule.params.includes('in oklab')) {
          atRule.remove();
        }
      },
    },
    Declaration(decl) {
      if (!decl.value.includes('color-mix(')) return;

      const rewritten = decl.value.replace(
        COLOR_MIX_WITH_TRANSPARENT,
        (fullMatch, colorToken: string, percentToken: string) => {
          const color = parseColor(colorToken);
          const percent = Number.parseFloat(percentToken);
          if (!color || !Number.isFinite(percent)) return fullMatch;

          const alpha = color.a * (percent / 100);
          return `rgba(${color.r}, ${color.g}, ${color.b}, ${formatAlpha(alpha)})`;
        },
      );

      decl.value = rewritten;
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
