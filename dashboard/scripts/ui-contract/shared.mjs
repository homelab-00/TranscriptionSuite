import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
export const CONTRACT_DIR = path.join(PROJECT_ROOT, 'ui-contract');
export const GENERATED_DIR = path.join(CONTRACT_DIR, '.generated');
export const CONTRACT_PATH = path.join(CONTRACT_DIR, 'transcription-suite-ui.contract.yaml');
export const SCHEMA_PATH = path.join(CONTRACT_DIR, 'transcription-suite-ui.contract.schema.json');
export const BASELINE_PATH = path.join(CONTRACT_DIR, 'contract-baseline.json');

const KNOWN_SINGLE_CLASS_TOKENS = new Set([
  'absolute',
  'active',
  'animate-in',
  'animate-ping',
  'animate-pulse',
  'block',
  'border',
  'cursor-pointer',
  'custom-scrollbar',
  'fade-in',
  'fill-mode-forwards',
  'fixed',
  'flex',
  'flex-1',
  'grid',
  'group',
  'h-full',
  'hidden',
  'inline-block',
  'inline-flex',
  'inset-0',
  'italic',
  'justify-center',
  'mask-gradient-right',
  'min-h-0',
  'min-w-0',
  'overflow-hidden',
  'overflow-x-auto',
  'overflow-y-auto',
  'pointer-events-auto',
  'pointer-events-none',
  'relative',
  'select-all',
  'select-none',
  'selectable-text',
  'shadow',
  'shrink-0',
  'snap-mandatory',
  'snap-start',
  'snap-x',
  'sticky',
  'text-left',
  'text-right',
  'to-transparent',
  'transition',
  'transition-all',
  'transition-colors',
  'transition-opacity',
  'transition-shadow',
  'transition-transform',
  'truncate',
  'uppercase',
  'w-full',
  'whitespace-nowrap',
  'z-0',
  'z-10',
  'z-20',
  'z-50',
]);

const CLASS_PREFIX_RE =
  /^(?:!?-?(?:aria-|backdrop-|bg-|blur-|border-|bottom-|col-|cursor-|delay-|drop-shadow-|duration-|ease-|fill-|flex-|font-|from-|gap-|grid-|h-|hover:|inset-|items-|justify-|leading-|left-|line-clamp-|lg:|m-|max-|mb-|md:|min-|ml-|mr-|mt-|mx-|my-|opacity-|outline-|overflow-|p-|pb-|peer-|pl-|pr-|pt-|px-|py-|ring-|right-|rotate-|rounded|scale-|shadow|shrink-|size-|skew-|slide-|sm:|snap-|space-|stroke-|text-|to-|top-|tracking-|translate-|via-|w-|whitespace-|xl:|z-))/;

const COLOR_LITERAL_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^\n\r)]+\)|hsla?\([^\n\r)]+\)/g;
const CUBIC_BEZIER_RE = /cubic-bezier\([^\n\r)]+\)/g;
const KEYFRAME_RE = /@keyframes\s+([A-Za-z0-9_-]+)/g;
const ANIMATION_STRING_RE = /animation\s*:\s*['"`]([^'"`]+)['"`]/g;
const DURATION_TOKEN_RE = /(?:^|:)duration-(\d{2,4})$/;
const EASING_TOKEN_RE = /(?:^|:)ease-(?:\[[^\]]+\]|[a-z-]+)$/;
const Z_INDEX_TOKEN_RE = /(?:^|:)z-(?:\[[^\]]+\]|\d+)$/;

function toPosixPath(filePath) {
  return filePath.split(path.sep).join('/');
}

function uniqueSorted(values) {
  return Array.from(new Set(values)).sort((a, b) => {
    if (typeof a === 'number' && typeof b === 'number') {
      return a - b;
    }
    return String(a).localeCompare(String(b));
  });
}

export function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

async function walk(dir, predicate, acc = []) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await walk(fullPath, predicate, acc);
      continue;
    }
    if (predicate(fullPath)) {
      acc.push(fullPath);
    }
  }
  return acc;
}

export async function sourceFiles(root = PROJECT_ROOT) {
  const files = [
    path.join(root, 'index.html'),
    path.join(root, 'App.tsx'),
    path.join(root, 'index.tsx'),
    path.join(root, 'types.ts'),
    path.join(root, 'src', 'index.css'),
  ];
  const componentFiles = await walk(path.join(root, 'components'), (filePath) =>
    filePath.endsWith('.tsx'),
  );
  files.push(...componentFiles);
  return files;
}

async function readFiles(filePaths) {
  const result = new Map();
  for (const filePath of filePaths) {
    try {
      const content = await fs.readFile(filePath, 'utf8');
      result.set(filePath, content);
    } catch (error) {
      if (error.code !== 'ENOENT') {
        throw error;
      }
    }
  }
  return result;
}

function findBalancedBlock(source, openIndex, openChar = '{', closeChar = '}') {
  let depth = 0;
  let inSingle = false;
  let inDouble = false;
  let inTemplate = false;
  let escaped = false;

  for (let i = openIndex; i < source.length; i += 1) {
    const char = source[i];
    if (escaped) {
      escaped = false;
      continue;
    }

    if (char === '\\') {
      escaped = true;
      continue;
    }

    if (!inDouble && !inTemplate && char === "'") {
      inSingle = !inSingle;
      continue;
    }
    if (!inSingle && !inTemplate && char === '"') {
      inDouble = !inDouble;
      continue;
    }
    if (!inSingle && !inDouble && char === '`') {
      inTemplate = !inTemplate;
      continue;
    }

    if (inSingle || inDouble || inTemplate) {
      continue;
    }

    if (char === openChar) {
      depth += 1;
      continue;
    }
    if (char === closeChar) {
      depth -= 1;
      if (depth === 0) {
        return source.slice(openIndex, i + 1);
      }
    }
  }

  return '';
}

function extractTailwindConfig(indexHtml) {
  const marker = 'tailwind.config';
  const markerIdx = indexHtml.indexOf(marker);
  if (markerIdx === -1) {
    return null;
  }

  const equalsIdx = indexHtml.indexOf('=', markerIdx);
  const braceStart = indexHtml.indexOf('{', equalsIdx);
  if (braceStart === -1) {
    return null;
  }

  const objectText = findBalancedBlock(indexHtml, braceStart, '{', '}');
  if (!objectText) {
    return null;
  }

  const sandbox = { tailwind: {} };
  vm.runInNewContext(`tailwind.config = ${objectText};`, sandbox);
  return sandbox.tailwind.config;
}

function extractDarkModeFromHtml(indexHtml) {
  return /\<html[^>]*\bclass=(['"])[^'"]*\bdark\b[^'"]*\1/i.test(indexHtml) ? 'class' : null;
}

function parseCssFontFamily(value) {
  return value
    .split(',')
    .map((item) => item.trim().replace(/^['"]|['"]$/g, ''))
    .filter(Boolean);
}

function extractTailwindConfigFromCss(cssText, indexHtml = '') {
  const marker = '@theme';
  const markerIdx = cssText.indexOf(marker);
  if (markerIdx === -1) {
    return null;
  }

  const braceStart = cssText.indexOf('{', markerIdx);
  if (braceStart === -1) {
    return null;
  }

  const themeBlock = findBalancedBlock(cssText, braceStart, '{', '}');
  if (!themeBlock) {
    return null;
  }

  const vars = {};
  const varRe = /--([A-Za-z0-9-]+)\s*:\s*([^;]+);/g;
  let match;
  while ((match = varRe.exec(themeBlock)) !== null) {
    vars[match[1]] = match[2].trim();
  }

  const accent = {};
  const glass = {};
  const backdropBlur = {};

  for (const [key, value] of Object.entries(vars)) {
    if (key.startsWith('color-accent-')) {
      accent[key.slice('color-accent-'.length)] = value;
      continue;
    }
    if (key.startsWith('color-glass-')) {
      glass[key.slice('color-glass-'.length)] = value;
      continue;
    }
    if (key.startsWith('backdrop-blur-')) {
      backdropBlur[key.slice('backdrop-blur-'.length)] = value;
    }
  }

  return {
    darkMode: extractDarkModeFromHtml(indexHtml),
    theme: {
      extend: {
        fontFamily: {
          sans: vars['font-sans'] ? parseCssFontFamily(vars['font-sans']) : [],
        },
        colors: {
          accent,
          glass,
        },
        backdropBlur,
      },
    },
  };
}

function extractStyleTag(indexHtml) {
  const match = indexHtml.match(/<style>([\s\S]*?)<\/style>/i);
  return match ? match[1].trim() : '';
}

function extractCssBlock(styleText, selector) {
  const idx = styleText.indexOf(selector);
  if (idx === -1) {
    return '';
  }
  const braceStart = styleText.indexOf('{', idx);
  if (braceStart === -1) {
    return '';
  }
  const block = findBalancedBlock(styleText, braceStart, '{', '}');
  if (!block) {
    return '';
  }
  return `${selector} ${block}`.trim();
}

function extractQuotedStrings(content) {
  const matches = [];
  const re = /(['"`])((?:\\.|(?!\1)[\s\S])*)\1/g;
  let match;
  while ((match = re.exec(content)) !== null) {
    matches.push(match[2]);
  }
  return matches;
}

function normalizeToken(rawToken) {
  return rawToken
    .trim()
    .replace(/['"`]/g, '')
    .replace(/^[,;]+|[,;]+$/g, '')
    .replace(/^\(+|\)+$/g, '')
    .replace(/^\{+|\}+$/g, '')
    .trim();
}

function looksLikeUtilityToken(rawToken) {
  const token = normalizeToken(rawToken);
  if (!token) {
    return false;
  }
  if (token.includes('${')) {
    return false;
  }
  if (token.includes('://') || token.startsWith('www.')) {
    return false;
  }
  if (
    token.includes('.') &&
    !(token.includes('[') && token.includes(']')) &&
    !/-\d+\.\d+/.test(token)
  ) {
    return false;
  }
  if (/^[)\]}]/.test(token) || /[({]$/.test(token)) {
    return false;
  }
  if (token === ')[0]' || token === '[0]') {
    return false;
  }
  if (/^[0-9]+(?:\.[0-9]+)?$/.test(token)) {
    return false;
  }
  if (/^[A-Z_]+$/.test(token)) {
    return false;
  }
  if (/[^A-Za-z0-9_:\-./\[\]()%#,!]/.test(token)) {
    return false;
  }

  if (KNOWN_SINGLE_CLASS_TOKENS.has(token)) {
    return true;
  }
  if (token.includes('[') && token.includes(']')) {
    if (/^[!-]?\[[a-z-]+:[^\]]+\]$/.test(token)) {
      return true;
    }
    if (CLASS_PREFIX_RE.test(token)) {
      return true;
    }
    return false;
  }
  if (token.includes('-') || token.includes(':') || token.includes('/')) {
    return CLASS_PREFIX_RE.test(token);
  }
  return CLASS_PREFIX_RE.test(token);
}

function extractUtilityTokensFromString(candidate) {
  const withoutTemplateExpressions = candidate.replace(/\$\{[^}]*\}/g, ' ');
  const tokens = [];
  const parts = withoutTemplateExpressions
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .map((part) => normalizeToken(part));

  for (const part of parts) {
    if (!part || part === '?' || part === ':' || part === '=>') {
      continue;
    }
    if (looksLikeUtilityToken(part)) {
      tokens.push(part);
    }
  }

  return tokens;
}

function extractUtilityTokens(content) {
  const values = extractQuotedStrings(content);
  const tokens = [];

  for (const value of values) {
    const hasUtilitySignal =
      value.includes(' ') ||
      value.includes(':') ||
      value.includes('-') ||
      value.includes('[') ||
      value.includes(']') ||
      KNOWN_SINGLE_CLASS_TOKENS.has(value.trim());

    if (!hasUtilitySignal) {
      continue;
    }

    tokens.push(...extractUtilityTokensFromString(value));
  }

  return uniqueSorted(tokens);
}

function tokenSegment(token) {
  const parts = token.split(':');
  return parts[parts.length - 1];
}

function extractInlineStyleBlocks(content) {
  const blocks = [];

  const styleAttrRe = /style=\{\{([\s\S]*?)\}\}/g;
  let match;
  while ((match = styleAttrRe.exec(content)) !== null) {
    blocks.push(match[1]);
  }

  const cssPropsConstRe = /const\s+\w+\s*:\s*React\.CSSProperties\s*=\s*\{([\s\S]*?)\};/g;
  while ((match = cssPropsConstRe.exec(content)) !== null) {
    blocks.push(match[1]);
  }

  const cssPropsCastRe = /\{\s*([^{}]*?)\s*\}\s+as\s+React\.CSSProperties/g;
  while ((match = cssPropsCastRe.exec(content)) !== null) {
    blocks.push(match[1]);
  }

  return blocks;
}

function extractInlineStylePropertiesAndLiterals(content) {
  const blocks = extractInlineStyleBlocks(content);
  const properties = new Set();
  const literals = new Set();

  for (const block of blocks) {
    const propRe = /\b([A-Za-z_$][A-Za-z0-9_$]*)\s*:/g;
    let propMatch;
    while ((propMatch = propRe.exec(block)) !== null) {
      properties.add(propMatch[1]);
    }

    const quotedRe = /(['"`])((?:\\.|(?!\1)[\s\S])*?)\1/g;
    let quoteMatch;
    while ((quoteMatch = quotedRe.exec(block)) !== null) {
      literals.add(quoteMatch[2].trim());
    }

    const numericRe = /(?<![A-Za-z0-9_-])-?\d+(?:\.\d+)?(?:ms|s|px|rem|%|vh|vw)?/g;
    let numericMatch;
    while ((numericMatch = numericRe.exec(block)) !== null) {
      literals.add(numericMatch[0]);
    }
  }

  return {
    properties: uniqueSorted(Array.from(properties)),
    literals: uniqueSorted(Array.from(literals).filter(Boolean)),
  };
}

function extractLiteralColors(content) {
  const matches = content.match(COLOR_LITERAL_RE) ?? [];
  return uniqueSorted(matches.map((value) => value.replace(/\s+/g, ' ').trim()));
}

function extractCubicBeziers(content) {
  const matches = content.match(CUBIC_BEZIER_RE) ?? [];
  return uniqueSorted(matches.map((value) => value.trim()));
}

function extractAnimationStrings(content) {
  const result = [];
  let match;
  while ((match = ANIMATION_STRING_RE.exec(content)) !== null) {
    result.push(match[1].trim());
  }
  return uniqueSorted(result);
}

function extractKeyframes(content) {
  const names = [];
  let match;
  while ((match = KEYFRAME_RE.exec(content)) !== null) {
    names.push(match[1]);
  }
  return uniqueSorted(names);
}

function extractComponentNames(content) {
  const names = new Set();
  const isAllCapsConstant = (name) => /^[A-Z0-9_]+$/.test(name);

  const constArrowRe =
    /(?:export\s+)?const\s+([A-Z][A-Za-z0-9_]*)\s*(?::[^=\n]+)?=\s*\([^)]*\)\s*=>/g;
  let match;
  while ((match = constArrowRe.exec(content)) !== null) {
    if (!isAllCapsConstant(match[1])) {
      names.add(match[1]);
    }
  }

  const broadArrowRe = /(?:export\s+)?const\s+([A-Z][A-Za-z0-9_]*)\b[\s\S]{0,220}?=>/g;
  while ((match = broadArrowRe.exec(content)) !== null) {
    if (!isAllCapsConstant(match[1])) {
      names.add(match[1]);
    }
  }

  const functionRe = /(?:export\s+)?function\s+([A-Z][A-Za-z0-9_]*)\s*\(/g;
  while ((match = functionRe.exec(content)) !== null) {
    if (!isAllCapsConstant(match[1])) {
      names.add(match[1]);
    }
  }

  return uniqueSorted(Array.from(names));
}

function extractStatusStateMap(statusLightContent) {
  const marker = 'const colors = {';
  const markerIdx = statusLightContent.indexOf(marker);
  if (markerIdx === -1) {
    return {};
  }
  const braceStart = statusLightContent.indexOf('{', markerIdx);
  const objectBlock = findBalancedBlock(statusLightContent, braceStart, '{', '}');
  if (!objectBlock) {
    return {};
  }

  const inner = objectBlock.slice(1, -1);
  const stateMap = {};
  const entryRe = /([a-zA-Z0-9_]+)\s*:\s*'([^']+)'/g;
  let match;
  while ((match = entryRe.exec(inner)) !== null) {
    const key = match[1];
    const classes = match[2].split(/\s+/).filter(Boolean);
    stateMap[key] = {
      classes,
      bg: classes.find((item) => item.startsWith('bg-')) ?? null,
      shadow: classes.find((item) => item.startsWith('shadow-')) ?? null,
    };
  }

  return stateMap;
}

function parseDurationMs(animationString) {
  const msMatch = animationString.match(/\b(\d+(?:\.\d+)?)ms\b/);
  if (msMatch) {
    return Math.round(Number(msMatch[1]));
  }
  const sMatch = animationString.match(/\b(\d+(?:\.\d+)?)s\b/);
  if (sMatch) {
    return Math.round(Number(sMatch[1]) * 1000);
  }
  return null;
}

function extractGlobalCssContracts(cssText) {
  return {
    body: extractCssBlock(cssText, 'body'),
    selection: extractCssBlock(cssText, '::selection'),
    moz_selection: extractCssBlock(cssText, '::-moz-selection'),
    selectable_text: extractCssBlock(cssText, '.selectable-text'),
    custom_scrollbar: {
      root: extractCssBlock(cssText, '.custom-scrollbar::-webkit-scrollbar'),
      track: extractCssBlock(cssText, '.custom-scrollbar::-webkit-scrollbar-track'),
      thumb: extractCssBlock(cssText, '.custom-scrollbar::-webkit-scrollbar-thumb'),
      thumb_hover: extractCssBlock(cssText, '.custom-scrollbar::-webkit-scrollbar-thumb:hover'),
      corner: extractCssBlock(cssText, '.custom-scrollbar::-webkit-scrollbar-corner'),
    },
  };
}

export async function extractFacts({ root = PROJECT_ROOT } = {}) {
  const files = await sourceFiles(root);
  const fileContentMap = await readFiles(files);

  const utilityTokens = new Set();
  const colorLiterals = new Set();
  const cubicBeziers = new Set();
  const inlineProperties = new Set();
  const inlineLiterals = new Set();
  const keyframes = new Set();
  const animationStrings = new Set();
  const componentNames = new Set();
  const componentToFile = {};

  for (const [filePath, content] of fileContentMap.entries()) {
    for (const token of extractUtilityTokens(content)) {
      utilityTokens.add(token);
    }
    for (const color of extractLiteralColors(content)) {
      colorLiterals.add(color);
    }
    for (const easing of extractCubicBeziers(content)) {
      cubicBeziers.add(easing);
    }

    const inlineResult = extractInlineStylePropertiesAndLiterals(content);
    for (const prop of inlineResult.properties) {
      inlineProperties.add(prop);
    }
    for (const literal of inlineResult.literals) {
      inlineLiterals.add(literal);
    }

    for (const keyframe of extractKeyframes(content)) {
      keyframes.add(keyframe);
    }
    for (const animation of extractAnimationStrings(content)) {
      animationStrings.add(animation);
    }

    if (filePath.endsWith('.tsx')) {
      const discovered = extractComponentNames(content);
      for (const name of discovered) {
        componentNames.add(name);
        componentToFile[name] = toPosixPath(path.relative(root, filePath));
      }
    }
  }

  const utilities = uniqueSorted(Array.from(utilityTokens));
  const utilityArbitrary = utilities.filter((token) => token.includes('[') && token.includes(']'));
  const utilityExact = utilities.filter((token) => !utilityArbitrary.includes(token));

  const durationMs = new Set();
  const easingTokens = new Set();
  const animationClasses = new Set();
  const backdropBlurClasses = new Set();
  const filterBlurClasses = new Set();
  const shadowClasses = new Set();
  const roundedClasses = new Set();
  const zIndexClasses = new Set();
  const spacingAndSizeArbitrary = new Set();

  for (const token of utilities) {
    const segment = tokenSegment(token);

    const durationMatch = token.match(DURATION_TOKEN_RE) || segment.match(/^duration-(\d{2,4})$/);
    if (durationMatch) {
      durationMs.add(Number(durationMatch[1]));
    }

    if (EASING_TOKEN_RE.test(token) || /^ease-(?:\[[^\]]+\]|[a-z-]+)$/.test(segment)) {
      easingTokens.add(segment.startsWith('ease-') ? segment : token);
    }

    if (segment.startsWith('animate-')) {
      animationClasses.add(segment);
    }
    if (segment.startsWith('backdrop-blur')) {
      backdropBlurClasses.add(segment);
    }
    if (segment.startsWith('blur-')) {
      filterBlurClasses.add(segment);
    }
    if (segment.startsWith('shadow')) {
      shadowClasses.add(segment);
    }
    if (segment.startsWith('rounded')) {
      roundedClasses.add(segment);
    }
    if (Z_INDEX_TOKEN_RE.test(token) || /^z-(?:\[[^\]]+\]|\d+)$/.test(segment)) {
      zIndexClasses.add(segment.startsWith('z-') ? segment : token);
    }

    if (
      segment.includes('[') &&
      /(w-|h-|min-|max-|translate-|scale-|skew-|grid-rows-|text-|p-|m-|left-|right-|top-|bottom-)/.test(
        segment,
      )
    ) {
      spacingAndSizeArbitrary.add(segment);
    }
  }

  for (const easing of cubicBeziers) {
    easingTokens.add(`ease-[${easing}]`);
  }

  const animationDurationFromStrings = [];
  for (const animationString of animationStrings) {
    const parsed = parseDurationMs(animationString);
    if (parsed !== null) {
      durationMs.add(parsed);
      animationDurationFromStrings.push(parsed);
    }
  }

  const indexHtmlPath = path.join(root, 'index.html');
  const indexHtml = fileContentMap.get(indexHtmlPath) ?? '';
  const cssPath = path.join(root, 'src', 'index.css');
  const cssText = fileContentMap.get(cssPath) ?? extractStyleTag(indexHtml);
  const tailwindConfig =
    extractTailwindConfig(indexHtml) ?? extractTailwindConfigFromCss(cssText, indexHtml);
  const globalCss = extractGlobalCssContracts(cssText);

  const statusLightPath = path.join(root, 'components', 'ui', 'StatusLight.tsx');
  const statusStateMap = extractStatusStateMap(fileContentMap.get(statusLightPath) ?? '');

  return {
    generated_at: new Date().toISOString(),
    repo_root: toPosixPath(root),
    source_files: uniqueSorted(files.map((filePath) => toPosixPath(path.relative(root, filePath)))),
    tailwind: {
      dark_mode: tailwindConfig?.darkMode ?? null,
      extend: tailwindConfig?.theme?.extend ?? {},
    },
    global_css: globalCss,
    utilities: {
      exact_classes: utilityExact,
      arbitrary_classes: uniqueSorted(utilityArbitrary),
    },
    tokens: {
      colors: {
        literal_palette: uniqueSorted(Array.from(colorLiterals)),
        accent_scale: tailwindConfig?.theme?.extend?.colors?.accent ?? {},
        glass_scale: tailwindConfig?.theme?.extend?.colors?.glass ?? {},
      },
      blur_levels: {
        backdrop: uniqueSorted(Array.from(backdropBlurClasses)),
        filter: uniqueSorted(Array.from(filterBlurClasses)),
      },
      shadow_levels: {
        classes: uniqueSorted(Array.from(shadowClasses)),
      },
      motion: {
        duration_ms: uniqueSorted(Array.from(durationMs)),
        easings: uniqueSorted(Array.from(easingTokens)),
        keyframes: uniqueSorted(Array.from(keyframes)),
        animation_classes: uniqueSorted(Array.from(animationClasses)),
        animation_strings: uniqueSorted(Array.from(animationStrings)),
        animation_duration_from_strings_ms: uniqueSorted(animationDurationFromStrings),
      },
      radii: {
        classes: uniqueSorted(Array.from(roundedClasses)),
      },
      z_index_levels: {
        classes: uniqueSorted(Array.from(zIndexClasses)),
      },
      spacing_and_size_constraints: {
        arbitrary_classes: uniqueSorted(Array.from(spacingAndSizeArbitrary)),
      },
      status_states: {
        allowed: uniqueSorted(Object.keys(statusStateMap)),
        visual_mappings: statusStateMap,
      },
    },
    inline_style: {
      allowed_properties: uniqueSorted(Array.from(inlineProperties)),
      allowed_literals: uniqueSorted(Array.from(inlineLiterals)),
      keyframes: uniqueSorted(Array.from(keyframes)),
      animation_strings: uniqueSorted(Array.from(animationStrings)),
      cubic_beziers: uniqueSorted(Array.from(cubicBeziers)),
    },
    components: {
      names: uniqueSorted(Array.from(componentNames)),
      files: componentToFile,
    },
  };
}

export async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

export async function readJson(filePath) {
  const raw = await fs.readFile(filePath, 'utf8');
  return JSON.parse(raw);
}

export async function writeJson(filePath, value) {
  await ensureDir(path.dirname(filePath));
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

export function setDiff(contractValues, extractedValues) {
  const contractSet = new Set(contractValues);
  const extractedSet = new Set(extractedValues);

  const missingInContract = extractedValues.filter((value) => !contractSet.has(value));
  const staleInContract = contractValues.filter((value) => !extractedSet.has(value));

  return {
    missing_in_contract: uniqueSorted(missingInContract),
    stale_in_contract: uniqueSorted(staleInContract),
  };
}

export function isDiffEmpty(diff) {
  return diff.missing_in_contract.length === 0 && diff.stale_in_contract.length === 0;
}

export function extractSemverParts(version) {
  const match = /^([0-9]+)\.([0-9]+)\.([0-9]+)$/.exec(version);
  if (!match) {
    return null;
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  };
}
