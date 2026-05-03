// Story 1.1 — Day-1 ESLint flat config (Audio Notebook QoL pack epic-foundations).
//
// Scope: ONLY the banned-API discipline gate. The dashboard codebase had no
// ESLint configuration at all before this story; introducing the full
// recommended ruleset retroactively would surface ~40 pre-existing
// violations and inflate the story scope. Story 1.1 establishes the
// gate that prevents NEW test files from regressing on NFR54 — the
// recommended ruleset is left for a follow-up cleanup story.
//
// This is the dashboard analogue of server/backend/pyproject.toml's
// [tool.ruff.lint.flake8-tidy-imports.banned-api] block. The Python rules
// don't translate one-for-one, so we map each Python ban to the closest
// JS/TS analogue:
//
//   Python time.sleep            → JS setTimeout / setInterval (in tests)
//   Python datetime.datetime.now → JS Date.now() / new Date() (in tests)
//   Python httpx.Client          → JS axios / node-fetch / undici (in tests)
//
// Approved alternatives (when the corresponding fixture/util lands):
//   - vi.useFakeTimers() / vi.advanceTimersByTime() for time control
//   - vi.setSystemTime() for Date control
//   - msw or vi.fn() for HTTP mocking
//
// If a test legitimately needs a banned API, add an inline
// `// eslint-disable-next-line no-restricted-syntax` with a one-line
// justification. That is the documented escape hatch.

import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

const TEST_FILES = ['**/*.test.ts', '**/*.test.tsx'];

// Pre-existing test files that already use the banned APIs. Grandfathered
// to keep Story 1.1 scope minimal. Migration is tech-debt tracked
// separately; new test files MUST NOT be added to this list.
const GRANDFATHERED_OFFENDERS = [
  'electron/__tests__/appState.test.ts',
  'electron/__tests__/compatGuard.test.ts',
  'electron/__tests__/containerRuntime.test.ts',
  'electron/__tests__/startupEventWatcher.test.ts',
  'electron/__tests__/updateInstaller.test.ts',
  'src/hooks/__tests__/useAuthTokenSync.test.ts',
  'src/hooks/useAuthTokenSync.test.ts',
  'src/stores/importQueueStore.test.ts',
  'components/ui/__tests__/UpdateBanner.test.tsx',
  'components/ui/__tests__/UpdateModal.test.tsx',
];

export default [
  // ── Global ignores ────────────────────────────────────────────────────
  {
    ignores: [
      'dist/**',
      'dist-electron/**',
      'node_modules/**',
      'release/**',
      'ui-contract/**',
      'scripts/ui-contract/**',
      'src/api/generated-types.ts',
    ],
  },

  // ── Linter-wide options ───────────────────────────────────────────────
  // The pre-Story-1.1 codebase has many `// eslint-disable-next-line X`
  // comments referring to rules from plugins we don't actively enable.
  // Silencing "unused disable" reports keeps the gate focused on the
  // banned-API rules; the disable comments stay harmless.
  {
    linterOptions: {
      reportUnusedDisableDirectives: 'off',
    },
  },

  // ── Parser config + plugin registration ───────────────────────────────
  // We register typescript-eslint and react-hooks as PLUGINS so that
  // pre-existing `// eslint-disable-next-line @typescript-eslint/...` and
  // `// eslint-disable-next-line react-hooks/...` comments resolve
  // (otherwise ESLint v9 errors with "Definition for rule X was not found").
  // We do NOT enable any of those plugins' rules — only the banned-API
  // discipline gate below is active.
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tseslint.plugin,
      'react-hooks': reactHooks,
    },
  },

  // ── Test-file discipline gate (the actual NFR54 rule) ─────────────────
  {
    files: TEST_FILES,
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name='setTimeout']",
          message:
            'Use vi.useFakeTimers() + vi.advanceTimersByTime() instead of setTimeout in tests.',
        },
        {
          selector: "CallExpression[callee.name='setInterval']",
          message:
            'Use vi.useFakeTimers() + vi.advanceTimersByTime() instead of setInterval in tests.',
        },
        {
          selector: "CallExpression[callee.object.name='Date'][callee.property.name='now']",
          message: 'Use vi.setSystemTime() instead of Date.now() in tests.',
        },
        {
          selector: "NewExpression[callee.name='Date'][arguments.length=0]",
          message: 'Use vi.setSystemTime() instead of new Date() (no args) in tests.',
        },
      ],
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: 'axios',
              message: 'Use msw or vi.fn() to mock HTTP in tests.',
            },
            {
              name: 'node-fetch',
              message: 'Use msw or vi.fn() to mock HTTP in tests.',
            },
            {
              name: 'undici',
              message: 'Use msw or vi.fn() to mock HTTP in tests.',
            },
          ],
        },
      ],
    },
  },

  // ── Grandfathered offenders (pre-Story-1.1 tech-debt) ─────────────────
  {
    files: GRANDFATHERED_OFFENDERS,
    rules: {
      'no-restricted-syntax': 'off',
      'no-restricted-imports': 'off',
    },
  },
];
