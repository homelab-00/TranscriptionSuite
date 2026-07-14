# Server Tab: NeMo Merge + Inline Model Picker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the Parakeet/Canary Main Transcriber tiles into one NeMo tile (and the MLX pair into MLX NeMo), replace the `Model Variant` dropdown with a per-family list of expandable model rows, and retire the sidebar Models tab into a "Manage all models" modal.

**Architecture:** `instanceMatrix.ts` is the single source of truth for family × runtime validity; the merge happens there and the compiler's exhaustive `Record<FamilyChoiceId, …>` types enumerate every call site that must follow. The Models tab's existing `ModelRow` already renders full model detail, so we extract its detail rendering into a shared component rather than inventing a card. `ServerView` already owns every piece of state the Model Manager needs, so the modal drives `ModelManagerTab` from `ServerView` and `ModelManagerView` is deleted (mounting it would create a second writer on the same electron-store keys).

**Tech Stack:** React 19 + TypeScript, Tailwind v4 (container queries), Vitest + Testing Library, electron-store via `window.electronAPI.config`.

**Spec:** `docs/superpowers/specs/2026-07-14-server-tab-nemo-merge-model-picker-design.md`

---

## Preconditions

Run every command from `dashboard/`. **Node 22 is mandatory** — vitest crashes with `ERR_REQUIRE_ESM` on other versions:

```bash
cd dashboard
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use --delete-prefix v22.22.3
node --version   # must print v22.x
```

**Three UI-contract scanner traps** (they silently corrupt the contract, so obey them while writing every file below):

1. **No apostrophes in `//` comments.** The scanner's string extractor does not strip comments and its regex spans newlines, so an apostrophe swallows every `className` literal that follows. Write "does not", never "doesn't".
2. **No `#NNN` hex-shaped text in comments.** It is read as a CSS color literal. Write `GH-207`, not `#207`. (Three or more hex chars — `#92` is safe, `#207` is not.)
3. **`backdrop-blur` is budgeted per file.** Check `grep -c backdrop-blur <file>` against `blur_depth_budgets.per_file_overrides` in `ui-contract/transcription-suite-ui.contract.yaml` before adding a blurred surface. A brand-new file gets `default_max: 3`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/services/instanceMatrix.ts` | Modify | Merge `parakeet`+`canary` → `nemo`, `mlx-parakeet`+`mlx-canary` → `mlx-nemo`. |
| `src/services/instanceMatrix.test.ts` | Modify | Cross-product matrix updated to 8 families; regression guard that live/diarization tiles are unchanged. |
| `components/models/ModelRowDetails.tsx` | Create | Shared, pure: the capability badge, the detail line (id, size, params, badges, languages) and description. |
| `components/models/ModelPickerRow.tsx` | Create | Collapsible, selectable row for the Server tab picker. Uses `ModelRowDetails` when expanded. |
| `components/views/server/MainModelPicker.tsx` | Create | The list: one `ModelPickerRow` per model in the selected family, a custom-repo row, and the "Manage all models" button. |
| `components/views/ModelManagerModal.tsx` | Create | Modal shell rendering `ModelManagerTab`, driven by `ServerView` state. |
| `src/hooks/useModelCache.ts` | Create | `{ modelCacheStatus, refreshCacheStatus(ids) }` with the Metal/Docker branch. |
| `src/hooks/useModelDownloads.ts` | Create | `{ downloadingIds, downloadModel, removeModel }` with the Metal / Docker / WSL2-GGML branches. |
| `components/views/ModelManagerTab.tsx` | Modify | Use the shared `ModelRowDetails`; delete its local `CapBadge`, its inline detail markup, and its now-duplicated download/toast state. |
| `components/views/server/InstanceSettingsSelectors.tsx` | Modify | `FAMILY_ICONS` gains `nemo`/`mlx-nemo`; the `Model Variant` `CustomSelect` is replaced by `<MainModelPicker>`. |
| `components/views/ServerView.tsx` | Modify | Adopt `useModelCache`; own the modal open/close state; pass the new props down. |
| `components/views/ModelManagerView.tsx` | **Delete** | Duplicate state owner — see spec §2.3. |
| `App.tsx` | Modify | Remove the `View.MODEL_MANAGER` route. |
| `components/Sidebar.tsx` | Modify | Remove the `Models` nav entry. |
| `types.ts` | Modify | Remove `View.MODEL_MANAGER`. |

---

## Task 1: Merge the NeMo families in the matrix

This is pure logic with an existing exhaustive test. Do it first: the compiler's `Record<FamilyChoiceId, …>` types will then enumerate every UI call site for Task 6.

**Files:**
- Modify: `src/services/instanceMatrix.ts`
- Test: `src/services/instanceMatrix.test.ts`

- [ ] **Step 1: Update the test's expected matrix (RED)**

In `src/services/instanceMatrix.test.ts`, replace the `EXPECTED_FAMILY_MATRIX` (lines 28-39) and `REPRESENTATIVE_MODEL` (lines 41-52) with:

```ts
const EXPECTED_FAMILY_MATRIX: Record<FamilyChoiceId, Record<RuntimeProfile, boolean>> = {
  whisper: { gpu: true, cpu: true, vulkan: false, 'vulkan-wsl2': false, metal: false },
  nemo: { gpu: true, cpu: false, vulkan: false, 'vulkan-wsl2': false, metal: false },
  sensevoice: { gpu: true, cpu: true, vulkan: false, 'vulkan-wsl2': false, metal: false },
  vibevoice: { gpu: true, cpu: true, vulkan: false, 'vulkan-wsl2': false, metal: false },
  whispercpp: { gpu: false, cpu: false, vulkan: true, 'vulkan-wsl2': true, metal: false },
  'mlx-whisper': { gpu: false, cpu: false, vulkan: false, 'vulkan-wsl2': false, metal: true },
  'mlx-nemo': { gpu: false, cpu: false, vulkan: false, 'vulkan-wsl2': false, metal: true },
  'mlx-vibevoice': { gpu: false, cpu: false, vulkan: false, 'vulkan-wsl2': false, metal: true },
};

const REPRESENTATIVE_MODEL: Record<FamilyChoiceId, string> = {
  whisper: 'Systran/faster-whisper-large-v3',
  nemo: 'nvidia/parakeet-tdt-0.6b-v3',
  sensevoice: 'iic/SenseVoiceSmall',
  vibevoice: 'microsoft/VibeVoice-ASR',
  whispercpp: 'ggml-large-v3-turbo-q8_0.bin',
  'mlx-whisper': 'mlx-community/whisper-large-v3-turbo-asr-fp16',
  'mlx-nemo': 'mlx-community/parakeet-tdt-0.6b-v3',
  'mlx-vibevoice': 'mlx-community/VibeVoice-ASR-4bit',
};
```

Replace the cpu-reason test (lines 74-79) with:

```ts
  it('the NeMo family on cpu carries an NVIDIA reason (mirrors applyCpuModelDefaults)', () => {
    const choices = familyChoicesFor('cpu');
    expect(choices.find((c) => c.id === 'nemo')?.reason).toMatch(/NVIDIA/i);
  });
```

In the `liveTilesFor` suite, line 179 reads `REPRESENTATIVE_MODEL.parakeet`. Change it to `REPRESENTATIVE_MODEL.nemo`.

Then append this new suite at the end of the file — it is the regression guard that proves the merge changed no behavior:

```ts
describe('instanceMatrix: NeMo family merge', () => {
  const PARAKEET = 'nvidia/parakeet-tdt-0.6b-v3';
  const CANARY = 'nvidia/canary-1b-v2';
  const MLX_PARAKEET = 'mlx-community/parakeet-tdt-0.6b-v3';
  const MLX_CANARY = 'eelcor/canary-1b-v2-mlx';

  it('classifies both NVIDIA NeMo models into the single nemo family', () => {
    expect(familyChoiceForModel(PARAKEET)).toBe('nemo');
    expect(familyChoiceForModel(CANARY)).toBe('nemo');
  });

  it('classifies both MLX NeMo ports into the single mlx-nemo family', () => {
    expect(familyChoiceForModel(MLX_PARAKEET)).toBe('mlx-nemo');
    expect(familyChoiceForModel(MLX_CANARY)).toBe('mlx-nemo');
  });

  it('offers both concrete NeMo models behind the merged tile', () => {
    const ids = modelsForFamilyChoice('nemo').map((m) => m.id);
    expect(ids).toContain(PARAKEET);
    expect(ids).toContain(CANARY);
  });

  it('defaults the merged tiles to Parakeet, not Canary', () => {
    expect(defaultModelForFamilyChoice('nemo')).toBe(MAIN_RECOMMENDED_MODEL);
    expect(defaultModelForFamilyChoice('mlx-nemo')).toBe('mlx-community/parakeet-tdt-0.6b-v3');
  });

  // The merge is only safe because Parakeet and Canary are matrix-identical.
  // If a future change makes them diverge on live or diarization, these fail.
  it('gives Parakeet and Canary mains identical live tiles', () => {
    expect(liveTilesFor('gpu', PARAKEET)).toEqual(liveTilesFor('gpu', CANARY));
  });

  it('gives Parakeet and Canary mains identical diarization tiles', () => {
    expect(diarizationTilesFor('gpu', PARAKEET)).toEqual(diarizationTilesFor('gpu', CANARY));
  });

  it('gives MLX Parakeet and MLX Canary mains identical diarization tiles', () => {
    expect(diarizationTilesFor('metal', MLX_PARAKEET)).toEqual(
      diarizationTilesFor('metal', MLX_CANARY),
    );
  });

  it('keeps neither NeMo model live-capable (backend live.py gate)', () => {
    for (const model of [PARAKEET, CANARY, MLX_PARAKEET, MLX_CANARY]) {
      const same = liveTilesFor('gpu', model).find((t) => t.id === 'same-as-main')!;
      expect(same.enabled, model).toBe(false);
    }
  });
});
```

Add `defaultModelForFamilyChoice` to the import block at the top of the test file (it is not currently imported).

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run src/services/instanceMatrix.test.ts
```

Expected: FAIL. TypeScript/vitest will complain that `nemo` and `mlx-nemo` are not assignable to `FamilyChoiceId`, and that `parakeet`/`canary` are missing from the record.

- [ ] **Step 3: Implement the merge in `instanceMatrix.ts`**

Replace `FAMILY_CHOICE_IDS` (lines 46-57) with:

```ts
export const FAMILY_CHOICE_IDS = [
  'whisper',
  'nemo',
  'sensevoice',
  'vibevoice',
  'whispercpp',
  'mlx-whisper',
  'mlx-nemo',
  'mlx-vibevoice',
] as const;
```

In `FAMILY_META`, delete the `parakeet` and `canary` entries (lines 103-126) and replace them with a single `nemo` entry in the same position:

```ts
  // One tile covers both Parakeet (ASR-only) and Canary (translating). The tile
  // advertises the family maximum, so it shows the translation badge; the model
  // rows below disambiguate which of the two the user actually has selected.
  nemo: {
    label: 'NeMo Models',
    sublabel: 'NVIDIA Parakeet / Canary',
    accent: 'green',
    capabilities: {
      languages: '25',
      translation: 'multilingual',
      live: false,
      diarization: 'pyannote',
      requiresToken: true,
    },
  },
```

Delete the `mlx-parakeet` and `mlx-canary` entries (lines 175-198) and replace with:

```ts
  'mlx-nemo': {
    label: 'MLX NeMo',
    sublabel: 'Apple Silicon',
    accent: 'green',
    capabilities: {
      languages: '25',
      translation: 'multilingual',
      live: false,
      diarization: 'sortformer',
      requiresToken: false,
    },
  },
```

Replace `MLX_FAMILIES` (lines 221-226):

```ts
const MLX_FAMILIES: readonly FamilyChoiceId[] = ['mlx-whisper', 'mlx-nemo', 'mlx-vibevoice'];
```

In `familyAvailability`, replace the cpu branch (lines 253-262):

```ts
  if (runtime === 'cpu') {
    if (id === 'nemo') {
      // dockerManager substitutes NeMo mains with faster-whisper on cpu;
      // surface that as an explicit disable instead of a silent swap.
      return { enabled: false, reason: REASON_REQUIRES_NVIDIA };
    }
    if (id === 'sensevoice' || id === 'vibevoice') {
      return { enabled: true, hint: HINT_SLOW_ON_CPU };
    }
  }
```

In `familyChoiceForModel`, replace lines 293-299. **The MLX checks must stay ahead of the generic ones** — same ordering as backend `factory.py`:

```ts
  if (isMLXParakeetModel(name) || isMLXCanaryModel(name)) return 'mlx-nemo';
  if (isMLXModel(name)) {
    return /vibevoice/i.test(name) ? 'mlx-vibevoice' : 'mlx-whisper';
  }
  if (isNemoModel(name)) return 'nemo';
  if (isSenseVoiceModel(name)) return 'sensevoice';
```

Update the import block at the top (lines 16-25) to pull in `isNemoModel` and drop the now-unused `isCanaryModel` / `isParakeetModel`:

```ts
import {
  isMLXCanaryModel,
  isMLXModel,
  isMLXParakeetModel,
  isNemoModel,
  isSenseVoiceModel,
  isVibeVoiceASRModel,
  isWhisperCppModel,
} from './modelCapabilities';
```

In `defaultModelForFamilyChoice`, replace lines 317-320:

```ts
  if (choice === 'whispercpp') return VULKAN_RECOMMENDED_MODEL;
  // Parakeet is the ASR-only workhorse and the right default; Canary is the
  // opt-in translation model, reachable from the model rows.
  if (choice === 'nemo') return MAIN_RECOMMENDED_MODEL;
  if (choice === 'mlx-nemo') return MLX_DEFAULT_MODEL;
  return modelsForFamilyChoice(choice)[0]?.id ?? '';
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run src/services/instanceMatrix.test.ts
```

Expected: PASS, all suites.

- [ ] **Step 5: Commit**

```bash
git add src/services/instanceMatrix.ts src/services/instanceMatrix.test.ts
git commit -m "refactor(server): merge the Parakeet and Canary family tiles into a single NeMo family

* refactor(server): collapse parakeet+canary into nemo and mlx-parakeet+mlx-canary into mlx-nemo in the instance matrix
  * safe because the pairs are matrix-identical: they differ only in the translation capability, and every field the matrix branches on (live, diarization, per-runtime availability) is the same
  * no config migration needed: the family id is derived from the persisted model id, never stored

* test(server): guard the merge with assertions that Parakeet and Canary produce identical live and diarization tiles"
```

---

## Task 2: Extract the shared model-detail renderer

The Models tab's `ModelRow` already renders the full detail we want in the picker. Extract that rendering so the picker and the manager cannot drift.

**Files:**
- Create: `components/models/ModelRowDetails.tsx`
- Modify: `components/views/ModelManagerTab.tsx`
- Test: `components/models/__tests__/ModelRowDetails.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `components/models/__tests__/ModelRowDetails.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ModelRowDetails } from '../ModelRowDetails';
import type { ModelInfo } from '../../../src/services/modelRegistry';

const MODEL: ModelInfo = {
  id: 'nvidia/canary-1b-v2',
  displayName: 'Canary 1B V2',
  family: 'nemo',
  description: 'NVIDIA multitask ASR and translation model.',
  parameterCount: '1B',
  huggingfaceUrl: 'https://huggingface.co/nvidia/canary-1b-v2',
  capabilities: { translation: true, liveMode: false, diarization: true, languageCount: 25 },
  roles: ['main'],
};

describe('ModelRowDetails', () => {
  it('shows the repo id, parameter count, language count and description', () => {
    render(<ModelRowDetails model={MODEL} cached={false} />);

    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
    expect(screen.getByText('1B params')).toBeInTheDocument();
    expect(screen.getByText('25 languages')).toBeInTheDocument();
    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
  });

  it('renders only the capability badges the model actually has', () => {
    render(<ModelRowDetails model={MODEL} cached={false} />);

    expect(screen.getByText('Translation')).toBeInTheDocument();
    expect(screen.getByText('Diarization')).toBeInTheDocument();
    expect(screen.queryByText('Live Mode')).not.toBeInTheDocument();
  });

  // Guards spec section 2.1: ModelInfo has no size field, so a size can only
  // ever be shown for a model that is already cached.
  it('shows no size when the model is not cached', () => {
    render(<ModelRowDetails model={MODEL} cached={false} cacheSize="4.1 GB" />);

    expect(screen.queryByText(/Downloaded/)).not.toBeInTheDocument();
  });

  it('shows the on-disk size once the model is cached', () => {
    render(<ModelRowDetails model={MODEL} cached={true} cacheSize="4.1 GB" />);

    expect(screen.getByText('Downloaded 4.1 GB')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run components/models/__tests__/ModelRowDetails.test.tsx
```

Expected: FAIL — `Cannot find module '../ModelRowDetails'`.

- [ ] **Step 3: Create the component**

Create `components/models/ModelRowDetails.tsx`. This is lifted verbatim from `ModelManagerTab.tsx` lines 131-138 (`CapBadge`) and 328-356 (the detail line and description):

```tsx
import React from 'react';
import type { ModelInfo } from '../../src/services/modelRegistry';

function CapBadge({ label, active }: { label: string; active: boolean }) {
  if (!active) return null;
  return (
    <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-400">
      {label}
    </span>
  );
}

interface ModelRowDetailsProps {
  model: ModelInfo;
  cached: boolean;
  /** On-disk size. Only known after download, so it renders only when cached. */
  cacheSize?: string;
  className?: string;
}

/**
 * The detail block for one model: repo id, on-disk size, parameter count,
 * capability badges, language count, and description.
 *
 * Shared by the Model Manager rows and the Server tab model picker so the two
 * cannot drift apart. ModelInfo carries no size field, so a size is shown only
 * for a model that is already cached.
 */
export const ModelRowDetails: React.FC<ModelRowDetailsProps> = ({
  model,
  cached,
  cacheSize,
  className = '',
}) => (
  <div className={className}>
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <span className="font-mono">{model.id}</span>
      {cached && cacheSize && (
        <>
          <span className="text-slate-600">&middot;</span>
          <span className="text-green-400">Downloaded {cacheSize}</span>
        </>
      )}
      {model.parameterCount && (
        <>
          <span className="text-slate-600">&middot;</span>
          <span>{model.parameterCount} params</span>
        </>
      )}
      <span className="text-slate-600">&middot;</span>
      <CapBadge label="Translation" active={model.capabilities.translation} />
      <CapBadge label="Live Mode" active={model.capabilities.liveMode} />
      <CapBadge label="Diarization" active={model.capabilities.diarization} />
      {model.capabilities.languageCount > 0 && (
        <span className="text-slate-500">
          {model.capabilities.languageCount} language
          {model.capabilities.languageCount !== 1 ? 's' : ''}
        </span>
      )}
    </div>
    <p className="mt-1 text-xs text-slate-500">{model.description}</p>
  </div>
);
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run components/models/__tests__/ModelRowDetails.test.tsx
```

Expected: PASS (4 tests).

- [ ] **Step 5: Adopt it in `ModelManagerTab.tsx`**

Delete the local `CapBadge` (lines 131-138). Replace the "Detail line" and "Description" blocks (lines 328-356) with a single call, preserving the `pl-5` indent that aligned them under the status dot:

```tsx
      <ModelRowDetails
        model={model}
        cached={cached}
        cacheSize={cacheSize}
        className="mt-1.5 pl-5"
      />
```

Add the import at the top of the file:

```tsx
import { ModelRowDetails } from '../models/ModelRowDetails';
```

Remove any `import` of icons that are now unused (TypeScript's `noUnusedLocals` will name them if so).

- [ ] **Step 6: Verify the Models tab still renders**

```bash
npx vitest run components/ --silent
npx tsc --noEmit
```

Expected: PASS, and no type errors.

- [ ] **Step 7: Commit**

```bash
git add components/models/ModelRowDetails.tsx components/models/__tests__/ModelRowDetails.test.tsx components/views/ModelManagerTab.tsx
git commit -m "refactor(models): extract the shared model-detail renderer out of ModelManagerTab

* refactor(models): lift the capability badges, detail line and description into ModelRowDetails so the Model Manager and the upcoming Server tab picker cannot drift apart

* test(models): assert a size is never shown for a model that is not cached, since ModelInfo carries no size field and the real size is known only after download"
```

---

## Task 3: The collapsible, selectable picker row

**Files:**
- Create: `components/models/ModelPickerRow.tsx`
- Test: `components/models/__tests__/ModelPickerRow.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `components/models/__tests__/ModelPickerRow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { ModelPickerRow } from '../ModelPickerRow';
import type { ModelInfo } from '../../../src/services/modelRegistry';

const MODEL: ModelInfo = {
  id: 'nvidia/canary-1b-v2',
  displayName: 'Canary 1B V2',
  family: 'nemo',
  description: 'NVIDIA multitask ASR and translation model.',
  parameterCount: '1B',
  huggingfaceUrl: 'https://huggingface.co/nvidia/canary-1b-v2',
  capabilities: { translation: true, liveMode: false, diarization: true, languageCount: 25 },
  roles: ['main'],
};

function setup(overrides: Partial<React.ComponentProps<typeof ModelPickerRow>> = {}) {
  const props = {
    model: MODEL,
    selected: false,
    cached: false,
    downloading: false,
    canManage: true,
    disabled: false,
    onSelect: vi.fn(),
    onDownload: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<ModelPickerRow {...props} />);
  return props;
}

describe('ModelPickerRow', () => {
  it('is collapsed by default, showing the name but not the description', () => {
    setup();

    expect(screen.getByText('Canary 1B V2')).toBeInTheDocument();
    expect(screen.queryByText(MODEL.description)).not.toBeInTheDocument();
  });

  it('reveals the full detail when expanded', async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole('button', { name: /details/i }));

    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
  });

  it('selects the model when the row is clicked', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('radio', { name: /Canary 1B V2/ }));

    expect(props.onSelect).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the selected row as checked', () => {
    setup({ selected: true });

    expect(screen.getByRole('radio', { name: /Canary 1B V2/ })).toBeChecked();
  });

  it('does not allow selection while the server is running', async () => {
    const user = userEvent.setup();
    const props = setup({ disabled: true });

    await user.click(screen.getByRole('radio', { name: /Canary 1B V2/ }));

    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it('offers Download when the model is absent and Remove once it is cached', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('button', { name: /download/i }));
    expect(props.onDownload).toHaveBeenCalledWith('nvidia/canary-1b-v2');

    screen.getByRole('button', { name: /download/i });
  });

  it('shows Remove instead of Download for a cached model', () => {
    setup({ cached: true });

    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run components/models/__tests__/ModelPickerRow.test.tsx
```

Expected: FAIL — `Cannot find module '../ModelPickerRow'`.

- [ ] **Step 3: Create the component**

Create `components/models/ModelPickerRow.tsx`:

```tsx
import React, { useState } from 'react';
import { ChevronDown, Download, Loader2, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { ModelRowDetails } from './ModelRowDetails';
import type { ModelInfo } from '../../src/services/modelRegistry';

interface ModelPickerRowProps {
  model: ModelInfo;
  selected: boolean;
  cached: boolean;
  cacheSize?: string;
  downloading: boolean;
  /** Whether download and remove are permitted right now. */
  canManage: boolean;
  /** Selection is locked while the server is running. */
  disabled: boolean;
  onSelect: (id: string) => void;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
}

/**
 * One model in the Server tab picker: a compact row that expands to the same
 * detail block the Model Manager shows.
 *
 * Collapsed by default because the largest families carry a dozen models, and a
 * dozen always-expanded rows would swamp an already long Server tab.
 */
export const ModelPickerRow: React.FC<ModelPickerRowProps> = ({
  model,
  selected,
  cached,
  cacheSize,
  downloading,
  canManage,
  disabled,
  onSelect,
  onDownload,
  onRemove,
}) => {
  const [expanded, setExpanded] = useState(false);

  const statusDot = downloading
    ? 'animate-pulse bg-blue-400'
    : cached
      ? 'bg-green-500'
      : 'bg-slate-500';

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 transition-colors ${
        selected ? 'border-accent-magenta/60 bg-white/10' : 'border-white/10 bg-white/5'
      }`}
    >
      <div className="flex items-center gap-3">
        <input
          type="radio"
          name="main-model"
          checked={selected}
          disabled={disabled}
          onChange={() => onSelect(model.id)}
          aria-label={model.displayName}
          className="accent-accent-magenta h-3.5 w-3.5 shrink-0"
        />

        <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${statusDot}`} />

        <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">
          {model.displayName}
        </span>

        {model.capabilities.translation && (
          <span className="shrink-0 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-slate-400">
            A&#8646;B
          </span>
        )}
        {model.parameterCount && (
          <span className="shrink-0 text-xs text-slate-500">{model.parameterCount}</span>
        )}

        {downloading ? (
          <Button variant="secondary" size="sm" disabled>
            <Loader2 size={13} className="mr-1.5 animate-spin" />
            Downloading
          </Button>
        ) : cached ? (
          <Button variant="danger" size="sm" onClick={() => onRemove(model.id)} disabled={!canManage}>
            <Trash2 size={13} className="mr-1.5" />
            Remove
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onDownload(model.id)}
            disabled={!canManage}
          >
            <Download size={13} className="mr-1.5" />
            Download
          </Button>
        )}

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? 'Hide details' : 'Show details'}
          aria-expanded={expanded}
          className="shrink-0 rounded p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ChevronDown
            size={14}
            className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {expanded && (
        <ModelRowDetails model={model} cached={cached} cacheSize={cacheSize} className="mt-2 pl-7" />
      )}
    </div>
  );
};
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run components/models/__tests__/ModelPickerRow.test.tsx
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add components/models/ModelPickerRow.tsx components/models/__tests__/ModelPickerRow.test.tsx
git commit -m "feat(models): add the collapsible, selectable model row for the Server tab picker

* feat(models): ModelPickerRow renders one model as a compact row that expands into the same detail block the Model Manager shows, and carries its own download and remove actions
  * collapsed by default because the largest families hold a dozen models, and a dozen expanded rows would swamp the Server tab"
```

---

## Task 4: The model cache hook

**Files:**
- Create: `src/hooks/useModelCache.ts`
- Test: `src/hooks/__tests__/useModelCache.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/hooks/__tests__/useModelCache.test.ts`:

```ts
import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useModelCache } from '../useModelCache';

const dockerCheck = vi.fn();
const mlxCheck = vi.fn();

beforeEach(() => {
  dockerCheck.mockReset().mockResolvedValue({ 'a/b': { exists: true, size: '1 GB' } });
  mlxCheck.mockReset().mockResolvedValue({ 'c/d': { exists: true, size: '2 GB' } });
  (window as any).electronAPI = {
    docker: { checkModelsCached: dockerCheck },
    mlx: { checkModelsCached: mlxCheck },
  };
});

afterEach(() => {
  delete (window as any).electronAPI;
});

describe('useModelCache', () => {
  it('starts empty', () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: false }));
    expect(result.current.modelCacheStatus).toEqual({});
  });

  it('probes Docker only when the container is running', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b']));

    expect(dockerCheck).not.toHaveBeenCalled();
  });

  it('merges Docker results once the container is running', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b']));

    await waitFor(() => {
      expect(result.current.modelCacheStatus['a/b']).toEqual({ exists: true, size: '1 GB' });
    });
    expect(dockerCheck).toHaveBeenCalledWith(['a/b']);
  });

  // GH-136: on Metal there is no container, docker.container.running is
  // permanently false, and the cache is a plain host-filesystem check.
  it('probes MLX on Metal even when nothing is running', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: true }));

    act(() => result.current.refreshCacheStatus(['c/d']));

    await waitFor(() => {
      expect(result.current.modelCacheStatus['c/d']).toEqual({ exists: true, size: '2 GB' });
    });
    expect(mlxCheck).toHaveBeenCalledWith(['c/d']);
    expect(dockerCheck).not.toHaveBeenCalled();
  });

  it('deduplicates ids and drops empty ones', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b', 'a/b', '']));

    await waitFor(() => expect(dockerCheck).toHaveBeenCalledWith(['a/b']));
  });

  it('does nothing when there is no id to check', () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus([]));

    expect(dockerCheck).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run src/hooks/__tests__/useModelCache.test.ts
```

Expected: FAIL — `Cannot find module '../useModelCache'`.

- [ ] **Step 3: Create the cache hook**

Create `src/hooks/useModelCache.ts`. The Metal/Docker branch is ported from `ModelManagerView.tsx:151-178`:

```ts
import { useCallback, useState } from 'react';

export interface ModelCacheEntry {
  exists: boolean;
  size?: string;
}

export type ModelCacheStatus = Record<string, ModelCacheEntry>;

interface UseModelCacheOptions {
  isRunning: boolean;
  isMetal: boolean;
}

export interface UseModelCacheResult {
  modelCacheStatus: ModelCacheStatus;
  refreshCacheStatus: (modelIds: readonly string[]) => void;
}

/**
 * Tracks which model weights are present on disk.
 *
 * The probe differs by runtime. On Metal there is no container: the cache is a
 * plain host-filesystem check that works whether or not the server runs, and
 * docker.container.running is permanently false there (GH-136). On Docker the
 * cache lives inside the container, so it can only be read while it runs.
 */
export function useModelCache({ isRunning, isMetal }: UseModelCacheOptions): UseModelCacheResult {
  const [modelCacheStatus, setModelCacheStatus] = useState<ModelCacheStatus>({});

  const refreshCacheStatus = useCallback(
    (modelIds: readonly string[]) => {
      const api = (window as any).electronAPI;
      const ids = [...new Set(modelIds)].filter(Boolean);
      if (ids.length === 0) return;

      const apply = (result: ModelCacheStatus) => {
        setModelCacheStatus((prev) => ({ ...prev, ...result }));
      };

      if (isMetal) {
        if (!api?.mlx?.checkModelsCached) return;
        api.mlx.checkModelsCached(ids).then(apply).catch(() => {});
        return;
      }

      if (!api?.docker?.checkModelsCached || !isRunning) return;
      api.docker.checkModelsCached(ids).then(apply).catch(() => {});
    },
    [isRunning, isMetal],
  );

  return { modelCacheStatus, refreshCacheStatus };
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run src/hooks/__tests__/useModelCache.test.ts
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useModelCache.ts src/hooks/__tests__/useModelCache.test.ts
git commit -m "feat(models): add useModelCache, a shared probe for which model weights are on disk

* feat(models): expose modelCacheStatus and refreshCacheStatus so both the Server tab picker and the Model Manager can report download state for arbitrary model ids
  * keeps the Metal branch from the old Model Manager: on Metal the cache is a host-filesystem check that works with the server stopped, because there is no container and docker.container.running is permanently false (GH-136)"
```

---

## Task 4b: Extract the download/remove logic

**Do not reimplement this.** `ModelManagerTab.handleDownload` (lines 627-659) branches three ways and one of the branches is easy to miss:

- **Metal** → `api.mlx.downloadModelToCache`
- **Docker** → `api.docker.downloadModelToCache`
- **vulkan-wsl2 + a whisper.cpp model** → `api.docker.downloadGgmlModelToHost`, writing to a **separate host cache** tracked by `refreshHostCacheStatus`, because GGML weights on WSL2 live on the Windows host rather than in the container.

Removal has the same shape, and on the WSL2/GGML path it is **not supported at all** — it shows a "delete manually from `%APPDATA%`" toast (line 669). Writing a fresh `downloadModel(id)` in `ServerView` would silently drop the WSL2 path on a supported platform. Extract instead, and have one owner.

**Files:**
- Create: `src/hooks/useModelDownloads.ts`
- Test: `src/hooks/__tests__/useModelDownloads.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/hooks/__tests__/useModelDownloads.test.ts`:

```ts
import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useModelDownloads } from '../useModelDownloads';

const toastMessage = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (m: string) => toastMessage(m),
    error: (m: string) => toastMessage(m),
    warning: (m: string) => toastMessage(m),
  },
}));

const dockerDownload = vi.fn();
const dockerRemove = vi.fn();
const ggmlToHost = vi.fn();
const mlxDownload = vi.fn();
const refreshCacheStatus = vi.fn();
const refreshHostCacheStatus = vi.fn();

// A GGML model id, which is what triggers the WSL2 host-cache branch.
const GGML = 'ggml-large-v3-turbo-q8_0.bin';

beforeEach(() => {
  [dockerDownload, dockerRemove, ggmlToHost, mlxDownload].forEach((m) =>
    m.mockReset().mockResolvedValue(undefined),
  );
  refreshCacheStatus.mockReset();
  refreshHostCacheStatus.mockReset();
  toastMessage.mockReset();
  (window as any).electronAPI = {
    docker: {
      downloadModelToCache: dockerDownload,
      removeModelCache: dockerRemove,
      downloadGgmlModelToHost: ggmlToHost,
    },
    mlx: { downloadModelToCache: mlxDownload, removeModelCache: vi.fn() },
  };
});

afterEach(() => {
  delete (window as any).electronAPI;
});

function setup(runtimeProfile = 'gpu', isMetal = false) {
  return renderHook(() =>
    useModelDownloads({ isMetal, runtimeProfile, refreshCacheStatus, refreshHostCacheStatus }),
  );
}

describe('useModelDownloads', () => {
  it('downloads into the container cache on Docker', async () => {
    const { result } = setup();

    await act(() => result.current.downloadModel('Systran/faster-whisper-medium'));

    expect(dockerDownload).toHaveBeenCalledWith('Systran/faster-whisper-medium');
    expect(refreshCacheStatus).toHaveBeenCalledWith(['Systran/faster-whisper-medium']);
  });

  it('downloads via MLX on Metal', async () => {
    const { result } = setup('metal', true);

    await act(() => result.current.downloadModel('mlx-community/parakeet-tdt-0.6b-v3'));

    expect(mlxDownload).toHaveBeenCalled();
    expect(dockerDownload).not.toHaveBeenCalled();
  });

  // The branch that is easy to lose: on WSL2 the GGML weights go to the Windows
  // host, not into the container.
  it('routes GGML models to the Windows host cache on vulkan-wsl2', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.downloadModel(GGML));

    expect(ggmlToHost).toHaveBeenCalledWith(GGML);
    expect(dockerDownload).not.toHaveBeenCalled();
    expect(refreshHostCacheStatus).toHaveBeenCalledWith([GGML]);
  });

  it('still uses the container cache for non-GGML models on vulkan-wsl2', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.downloadModel('Systran/faster-whisper-medium'));

    expect(dockerDownload).toHaveBeenCalled();
    expect(ggmlToHost).not.toHaveBeenCalled();
  });

  it('tracks which models are in flight', async () => {
    let resolveDownload: () => void = () => {};
    dockerDownload.mockImplementation(
      () => new Promise<void>((r) => (resolveDownload = r)),
    );
    const { result } = setup();

    act(() => {
      void result.current.downloadModel('Systran/faster-whisper-medium');
    });

    await waitFor(() =>
      expect(result.current.downloadingIds.has('Systran/faster-whisper-medium')).toBe(true),
    );

    await act(async () => {
      resolveDownload();
    });

    await waitFor(() =>
      expect(result.current.downloadingIds.has('Systran/faster-whisper-medium')).toBe(false),
    );
  });

  it('clears the in-flight marker even when the download fails', async () => {
    dockerDownload.mockRejectedValue(new Error('network down'));
    const { result } = setup();

    await act(() => result.current.downloadModel('Systran/faster-whisper-medium'));

    expect(result.current.downloadingIds.size).toBe(0);
    expect(toastMessage).toHaveBeenCalledWith(expect.stringMatching(/network down/));
  });

  it('removes from the container cache on Docker', async () => {
    const { result } = setup();

    await act(() => result.current.removeModel('Systran/faster-whisper-medium'));

    expect(dockerRemove).toHaveBeenCalledWith('Systran/faster-whisper-medium');
    expect(refreshCacheStatus).toHaveBeenCalledWith(['Systran/faster-whisper-medium']);
  });

  // Removing a host-side GGML model is not wired through IPC; the tab tells the
  // user to delete it by hand rather than failing silently.
  it('explains that GGML removal on vulkan-wsl2 must be done by hand', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.removeModel(GGML));

    expect(dockerRemove).not.toHaveBeenCalled();
    expect(toastMessage).toHaveBeenCalledWith(expect.stringMatching(/manually/i));
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run src/hooks/__tests__/useModelDownloads.test.ts
```

Expected: FAIL — `Cannot find module '../useModelDownloads'`.

- [ ] **Step 3: Create the hook**

Create `src/hooks/useModelDownloads.ts`. Port the branching **verbatim** from `ModelManagerTab.tsx:627-682`, swapping its bespoke toast for the app-wide `sonner` one:

```ts
import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { getModelsByFamily } from '../services/modelRegistry';

interface UseModelDownloadsOptions {
  isMetal: boolean;
  runtimeProfile: string;
  refreshCacheStatus: (ids: readonly string[]) => void;
  refreshHostCacheStatus: (ids: readonly string[]) => void;
}

export interface UseModelDownloadsResult {
  downloadingIds: ReadonlySet<string>;
  downloadModel: (id: string) => Promise<void>;
  removeModel: (id: string) => Promise<void>;
}

function isWhisperCppModelId(modelId: string): boolean {
  return Boolean(getModelsByFamily('whispercpp').find((m) => m.id === modelId));
}

/**
 * Download and remove model weights.
 *
 * Three storage paths, not one. Metal has no container, so weights go to the
 * host cache via the MLX bridge. Docker keeps them inside the container. And on
 * vulkan-wsl2 the GGML weights must live on the Windows host rather than in the
 * container, so they take a separate IPC call and a separate cache probe.
 *
 * Removing a host-side GGML model is not wired through IPC at all, so we tell
 * the user how to do it by hand instead of failing quietly.
 */
export function useModelDownloads({
  isMetal,
  runtimeProfile,
  refreshCacheStatus,
  refreshHostCacheStatus,
}: UseModelDownloadsOptions): UseModelDownloadsResult {
  const [downloadingIds, setDownloadingIds] = useState<ReadonlySet<string>>(new Set());
  const isVulkanWsl2 = runtimeProfile === 'vulkan-wsl2';

  const downloadModel = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      const download = isMetal
        ? api?.mlx?.downloadModelToCache
        : api?.docker?.downloadModelToCache;
      if (!download) return;

      setDownloadingIds((prev) => new Set(prev).add(modelId));
      try {
        if (isVulkanWsl2 && isWhisperCppModelId(modelId)) {
          if (!api?.docker?.downloadGgmlModelToHost) return;
          await api.docker.downloadGgmlModelToHost(modelId);
          toast.success(`Downloaded ${modelId}`);
          refreshHostCacheStatus([modelId]);
        } else {
          await download(modelId);
          toast.success(`Downloaded ${modelId}`);
          refreshCacheStatus([modelId]);
        }
      } catch (err: any) {
        toast.error(`Download failed: ${err?.message || 'Unknown error'}`);
      } finally {
        setDownloadingIds((prev) => {
          const next = new Set(prev);
          next.delete(modelId);
          return next;
        });
      }
    },
    [isMetal, isVulkanWsl2, refreshCacheStatus, refreshHostCacheStatus],
  );

  const removeModel = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      try {
        if (isVulkanWsl2 && isWhisperCppModelId(modelId)) {
          toast.warning(
            'Delete manually from %APPDATA%\\TranscriptionSuite\\whisper-models\\',
          );
          return;
        }
        const remove = isMetal ? api?.mlx?.removeModelCache : api?.docker?.removeModelCache;
        if (!remove) return;
        await remove(modelId);
        toast.success(`Removed cache for ${modelId}`);
        refreshCacheStatus([modelId]);
      } catch (err: any) {
        toast.error(`Remove failed: ${err?.message || 'Unknown error'}`);
      }
    },
    [isMetal, isVulkanWsl2, refreshCacheStatus],
  );

  return { downloadingIds, downloadModel, removeModel };
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run src/hooks/__tests__/useModelDownloads.test.ts
```

Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useModelDownloads.ts src/hooks/__tests__/useModelDownloads.test.ts
git commit -m "feat(models): extract model download and remove into a shared hook

* feat(models): lift the three storage paths out of ModelManagerTab so the Server tab picker can offer download and remove without reimplementing them
  * Metal writes to the host cache through the MLX bridge, Docker writes inside the container, and vulkan-wsl2 sends GGML weights to the Windows host through a separate IPC call and a separate cache probe
  * removing a host-side GGML model is not wired through IPC, so the hook keeps telling the user how to do it by hand rather than failing quietly

* refactor(models): use the app-wide sonner toast instead of the tab's bespoke one"
```

---

## Task 5: The Main Model picker

**Files:**
- Create: `components/views/server/MainModelPicker.tsx`
- Test: `components/views/server/__tests__/MainModelPicker.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `components/views/server/__tests__/MainModelPicker.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MainModelPicker } from '../MainModelPicker';
import { MAIN_MODEL_CUSTOM_OPTION } from '../../../../src/services/modelSelection';

function setup(overrides: Partial<React.ComponentProps<typeof MainModelPicker>> = {}) {
  const props = {
    selectedFamily: 'nemo' as const,
    mainModelSelection: 'nvidia/parakeet-tdt-0.6b-v3',
    mainCustomModel: '',
    isRunning: false,
    canManage: true,
    modelCacheStatus: {},
    downloadingIds: new Set<string>(),
    onMainModelSelectionChange: vi.fn(),
    onMainCustomModelChange: vi.fn(),
    onDownload: vi.fn(),
    onRemove: vi.fn(),
    onOpenManager: vi.fn(),
    ...overrides,
  };
  render(<MainModelPicker {...props} />);
  return props;
}

describe('MainModelPicker', () => {
  it('lists both NeMo models behind the merged family tile', () => {
    setup();

    expect(screen.getByRole('radio', { name: /Parakeet/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Canary/ })).toBeInTheDocument();
  });

  it('does not leak models from other families', () => {
    setup();

    expect(screen.queryByRole('radio', { name: /Faster Whisper/ })).not.toBeInTheDocument();
  });

  it('reports the model id when a row is selected', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('radio', { name: /Canary/ }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('reveals the free-text repo input when the custom row is chosen', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('radio', { name: /custom/i }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith(MAIN_MODEL_CUSTOM_OPTION);
  });

  it('shows the repo input while the custom option is active', () => {
    setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION });

    expect(screen.getByPlaceholderText('owner/model-name')).toBeInTheDocument();
  });

  it('locks every row while the server is running', () => {
    setup({ isRunning: true });

    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).toBeDisabled();
    }
  });

  it('opens the full manager on request', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('button', { name: /manage all models/i }));

    expect(props.onOpenManager).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run components/views/server/__tests__/MainModelPicker.test.tsx
```

Expected: FAIL — `Cannot find module '../MainModelPicker'`.

- [ ] **Step 3: Create the component**

Create `components/views/server/MainModelPicker.tsx`:

```tsx
import React from 'react';
import { Library, Zap } from 'lucide-react';
import { Button } from '../../ui/Button';
import { ModelPickerRow } from '../../models/ModelPickerRow';
import {
  modelsForFamilyChoice,
  type FamilyChoiceId,
} from '../../../src/services/instanceMatrix';
import { MAIN_MODEL_CUSTOM_OPTION } from '../../../src/services/modelSelection';
import type { ModelCacheStatus } from '../../../src/hooks/useModelCache';

interface MainModelPickerProps {
  selectedFamily: FamilyChoiceId | null;
  mainModelSelection: string;
  mainCustomModel: string;
  isRunning: boolean;
  canManage: boolean;
  modelCacheStatus: ModelCacheStatus;
  downloadingIds: ReadonlySet<string>;
  onMainModelSelectionChange: (value: string) => void;
  onMainCustomModelChange: (value: string) => void;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
  onOpenManager: () => void;
}

/**
 * The Main Transcriber model selection, scoped to the family the user picked
 * above. Replaces the single Model Variant dropdown: one expandable row per
 * model, so the two NeMo models (and the dozen Whisper variants) are
 * distinguishable without leaving the Server tab.
 *
 * Cross-family work — downloading weights for a family that is not currently
 * selected, or the diarization models — lives behind Manage all models.
 */
export const MainModelPicker: React.FC<MainModelPickerProps> = ({
  selectedFamily,
  mainModelSelection,
  mainCustomModel,
  isRunning,
  canManage,
  modelCacheStatus,
  downloadingIds,
  onMainModelSelectionChange,
  onMainCustomModelChange,
  onDownload,
  onRemove,
  onOpenManager,
}) => {
  const models = selectedFamily ? modelsForFamilyChoice(selectedFamily) : [];
  const isCustom = mainModelSelection === MAIN_MODEL_CUSTOM_OPTION;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium tracking-wider text-slate-500 uppercase">Model</label>
        <Button variant="ghost" size="sm" icon={<Library size={13} />} onClick={onOpenManager}>
          Manage all models
        </Button>
      </div>

      <div className="space-y-2">
        {models.map((model) => (
          <ModelPickerRow
            key={model.id}
            model={model}
            selected={mainModelSelection === model.id}
            cached={Boolean(modelCacheStatus[model.id]?.exists)}
            cacheSize={modelCacheStatus[model.id]?.size}
            downloading={downloadingIds.has(model.id)}
            canManage={canManage}
            disabled={isRunning}
            onSelect={onMainModelSelectionChange}
            onDownload={onDownload}
            onRemove={onRemove}
          />
        ))}

        {/* Custom HuggingFace repo — preserves the old dropdown MAIN_MODEL_CUSTOM_OPTION path. */}
        <div
          className={`rounded-lg border px-3 py-2.5 transition-colors ${
            isCustom ? 'border-accent-magenta/60 bg-white/10' : 'border-white/10 bg-white/5'
          }`}
        >
          <div className="flex items-center gap-3">
            <input
              type="radio"
              name="main-model"
              checked={isCustom}
              disabled={isRunning}
              onChange={() => onMainModelSelectionChange(MAIN_MODEL_CUSTOM_OPTION)}
              aria-label="Custom HuggingFace repo"
              className="accent-accent-magenta h-3.5 w-3.5 shrink-0"
            />
            <span className="flex-1 text-sm font-medium text-white">Custom HuggingFace repo</span>
          </div>
          {isCustom && (
            <input
              type="text"
              value={mainCustomModel}
              onChange={(e) => onMainCustomModelChange(e.target.value)}
              placeholder="owner/model-name"
              disabled={isRunning}
              className={`focus:ring-accent-magenta mt-2 ml-7 h-9 w-[calc(100%-1.75rem)] rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 outline-none focus:ring-1 ${
                isRunning ? 'cursor-not-allowed opacity-50' : ''
              }`}
            />
          )}
        </div>
      </div>

      {selectedFamily === 'whispercpp' && (
        <p className="text-xs text-slate-500 italic">
          This GGML model runs on the AMD/Intel GPU via the whisper.cpp sidecar. Switching models
          requires a server restart.
        </p>
      )}
      {selectedFamily?.startsWith('mlx') && (
        <p className="flex items-center gap-1 text-xs text-violet-400">
          <Zap size={10} />
          Metal / MLX accelerated
        </p>
      )}
    </div>
  );
};
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run components/views/server/__tests__/MainModelPicker.test.tsx
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add components/views/server/MainModelPicker.tsx components/views/server/__tests__/MainModelPicker.test.tsx
git commit -m "feat(server): add MainModelPicker, the per-family model list that replaces the Model Variant dropdown

* feat(server): render one expandable row per model in the selected family, so the two models behind the merged NeMo tile are distinguishable without leaving the Server tab
* feat(server): keep the custom HuggingFace repo path from the old dropdown, and surface cross-family work behind a Manage all models button"
```

---

## Task 6: Wire the picker into the Server tab

**Files:**
- Modify: `components/views/server/InstanceSettingsSelectors.tsx`

- [ ] **Step 1: Fix the family icon record (compiler-driven)**

`FAMILY_ICONS` at line 85 is a `Record<FamilyChoiceId, React.ReactNode>`, so it will not compile until it matches the new 8-family union. Replace the `parakeet`, `canary`, `mlx-parakeet` and `mlx-canary` keys with `nemo` and `mlx-nemo`, reusing the icons the old Parakeet entries used:

```bash
npx tsc --noEmit 2>&1 | head -20
```

Expected before the fix: errors naming `parakeet`, `canary`, `mlx-parakeet`, `mlx-canary` as missing/excess properties. Fix each one it names, then re-run until clean.

- [ ] **Step 2: Replace the Model Variant dropdown**

In `InstanceSettingsSelectors.tsx`, delete the whole `Model Variant` block (the `<div className="grid grid-cols-1 gap-4 md:grid-cols-2">` wrapper at line 304 through its close at line 340 — this includes the `CustomSelect`, the custom-model `<input>`, and the whisper.cpp / MLX notes, all of which now live in `MainModelPicker`).

Replace it with:

```tsx
      <MainModelPicker
        selectedFamily={selectedFamily}
        mainModelSelection={mainModelSelection}
        mainCustomModel={mainCustomModel}
        isRunning={isRunning}
        canManage={canManage}
        modelCacheStatus={modelCacheStatus}
        downloadingIds={downloadingIds}
        onMainModelSelectionChange={onMainModelSelectionChange}
        onMainCustomModelChange={onMainCustomModelChange}
        onDownload={onDownloadModel}
        onRemove={onRemoveModel}
        onOpenManager={onOpenModelManager}
      />
```

Add to the props interface of `InstanceSettingsSelectors`:

```tsx
  canManage: boolean;
  downloadingIds: ReadonlySet<string>;
  onDownloadModel: (id: string) => void;
  onRemoveModel: (id: string) => void;
  onOpenModelManager: () => void;
```

Add the import:

```tsx
import { MainModelPicker } from './MainModelPicker';
```

Then remove imports that are now unused (`CustomSelect`, `MAIN_MODEL_CUSTOM_OPTION`, `Zap`, and `mainDropdownOptions`'s helpers) — `npx tsc --noEmit` with `noUnusedLocals` will name each one.

- [ ] **Step 3: Typecheck**

```bash
npx tsc --noEmit
```

Expected: errors only in `ServerView.tsx`, for the five new required props. Task 7 supplies them.

- [ ] **Step 4: Commit**

```bash
git add components/views/server/InstanceSettingsSelectors.tsx
git commit -m "feat(server): swap the Model Variant dropdown for the MainModelPicker

* feat(server): point the family icon record at the merged nemo and mlx-nemo families
* feat(server): move the whisper.cpp restart note and the MLX acceleration note into the picker alongside the model rows they describe"
```

---

## Task 7: The Manage-all-models modal, and retiring the sidebar tab

`ModelManagerView` is **deleted**, not reused. It owns a second copy of the model-selection state and persists it to the same electron-store keys as `ServerView`; mounting it inside a Server-tab modal would make two writers race on those keys and silently clobber the user's choice. `ModelManagerTab` is already fully presentational, so the modal drives it from `ServerView`'s state.

**Files:**
- Create: `components/views/ModelManagerModal.tsx`
- Modify: `components/views/ServerView.tsx`
- Delete: `components/views/ModelManagerView.tsx`
- Modify: `App.tsx`, `components/Sidebar.tsx`, `types.ts`

- [ ] **Step 1: Create the modal shell**

Create `components/views/ModelManagerModal.tsx`:

```tsx
import React from 'react';
import { X } from 'lucide-react';
import { ModelManagerTab } from './ModelManagerTab';
import type { ModelCacheStatus } from '../../src/hooks/useModelCache';

interface ModelManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  mainModelSelection: string;
  setMainModelSelection: (v: string) => void;
  mainCustomModel: string;
  setMainCustomModel: (v: string) => void;
  liveModelSelection: string;
  setLiveModelSelection: (v: string) => void;
  liveCustomModel: string;
  setLiveCustomModel: (v: string) => void;
  diarizationModelSelection: string;
  setDiarizationModelSelection: (v: string) => void;
  diarizationCustomModel: string;
  setDiarizationCustomModel: (v: string) => void;
  modelCacheStatus: ModelCacheStatus;
  isRunning: boolean;
  refreshCacheStatus: (ids: readonly string[]) => void;
  isMetal: boolean;
}

/**
 * The full cross-family model manager, reachable from the Server tab now that it
 * no longer has its own sidebar entry. This is where weights for a family the
 * user has not currently selected get downloaded, and where the diarization
 * models live.
 *
 * Every piece of state is passed in from ServerView on purpose. ServerView
 * already hydrates and persists these electron-store keys; giving this modal its
 * own copy would put two writers on the same keys and lose whichever change
 * landed first.
 */
export const ModelManagerModal: React.FC<ModelManagerModalProps> = ({
  isOpen,
  onClose,
  ...tabProps
}) => {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Model Manager"
      onClick={onClose}
    >
      <div
        className="border-glass-border flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <h2 className="text-xl font-bold tracking-tight text-white">Model Manager</h2>
            <p className="text-sm text-slate-400">Browse, download, and manage model weights.</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto p-6">
          <ModelManagerTab {...tabProps} />
        </div>
      </div>
    </div>
  );
};
```

**Check the blur budget before committing this file:** `grep -c backdrop-blur components/views/ModelManagerModal.tsx` must be 0 here (the shell uses an opaque `bg-slate-900`, deliberately, to stay clear of the budget).

- [ ] **Step 2: Adopt `useModelCache` in `ServerView`**

In `ServerView.tsx`, delete the local `modelCacheStatus` state (line 261-263) and the `setModelCacheStatus` calls, and replace with the hook. Place it after `isMetal` (line 335) and `isRunning` (line 693) are both defined — i.e. below line 693:

```tsx
  const { modelCacheStatus, refreshCacheStatus } = useModelCache({ isRunning, isMetal });
```

Rewrite the existing debounced cache effect (lines 1115-1141) to call the hook instead of the raw API:

```tsx
  // Check model download cache whenever the active model names or container state change
  useEffect(() => {
    const modelIds = [
      ...new Set([activeTranscriber, normalizedLiveModel, diarizationStatusModelId]),
    ].filter(
      (id) => id && id !== MODEL_DEFAULT_LOADING_PLACEHOLDER && id !== DISABLED_MODEL_SENTINEL,
    );
    if (modelIds.length === 0) return;

    if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    modelCacheCheckRef.current = setTimeout(() => refreshCacheStatus(modelIds), 500);

    return () => {
      if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    };
  }, [
    activeTranscriber,
    normalizedLiveModel,
    diarizationStatusModelId,
    refreshCacheStatus,
  ]);
```

Add a second effect so the picker shows download state for **every** model in the selected family, not just the active one:

```tsx
  // The picker lists every model in the selected family, so probe all of them.
  const selectedFamily = useMemo(() => familyChoiceForModel(activeTranscriber), [activeTranscriber]);
  useEffect(() => {
    if (!selectedFamily) return;
    refreshCacheStatus(modelsForFamilyChoice(selectedFamily).map((m) => m.id));
  }, [selectedFamily, refreshCacheStatus]);
```

Add the imports:

```tsx
import { useModelCache } from '../../src/hooks/useModelCache';
import { ModelManagerModal } from './ModelManagerModal';
import { familyChoiceForModel, modelsForFamilyChoice } from '../../src/services/instanceMatrix';
```

- [ ] **Step 3: Own the downloads and the modal in `ServerView`**

`ServerView` owns **one** instance of the download hook and passes it into both the picker and the modal. Two instances would give the picker and the manager separate `downloadingIds` sets, so a download started in one would not appear to be in flight in the other.

Add near the other model state (around line 267):

```tsx
  const [isModelManagerOpen, setIsModelManagerOpen] = useState(false);
  const [hostCacheStatus, setHostCacheStatus] = useState<Record<string, { exists: boolean }>>({});
```

`refreshHostCacheStatus` is the WSL2 host-side GGML probe. Lift it out of `ModelManagerTab.tsx` (search for `refreshHostCacheStatus` there) into `ServerView` verbatim, then wire the hook below `isRunning`/`isMetal`:

```tsx
  const { downloadingIds, downloadModel, removeModel } = useModelDownloads({
    isMetal,
    runtimeProfile,
    refreshCacheStatus,
    refreshHostCacheStatus,
  });
```

Add the imports:

```tsx
import { useModelDownloads } from '../../src/hooks/useModelDownloads';
```

Pass the new props to `InstanceSettingsSelectors` (the call at line ~2325):

```tsx
                  canManage={isMetal || isRunning}
                  downloadingIds={downloadingIds}
                  onDownloadModel={downloadModel}
                  onRemoveModel={removeModel}
                  onOpenModelManager={() => setIsModelManagerOpen(true)}
```

`canManage` is `isMetal || isRunning` because Metal cache operations are host-local and work with the server stopped, while Docker ones need the container up.

- [ ] **Step 3b: Strip the now-duplicated state out of `ModelManagerTab`**

`ModelManagerTab` must stop owning what `ServerView` now owns, or the two will disagree about what is downloading.

Delete from `ModelManagerTab.tsx`: `downloadingModels` (line 548), `hostCacheStatus` (line 550), `toast` (line 554), `showToast` (line 576), `refreshHostCacheStatus`, `handleDownload` (627-659) and `handleRemove` (661-682), plus the bespoke toast JSX it renders.

Add to `ModelManagerTabProps`:

```tsx
  downloadingIds: ReadonlySet<string>;
  hostCacheStatus: Record<string, { exists: boolean }>;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
```

Replace the internal `handleDownload` / `handleRemove` / `downloadingModels` references in its JSX with `onDownload` / `onRemove` / `downloadingIds`. The compiler will name each site.

Render the modal at the end of `ServerView`'s JSX, as a sibling of the outermost content div:

```tsx
      <ModelManagerModal
        isOpen={isModelManagerOpen}
        onClose={() => setIsModelManagerOpen(false)}
        mainModelSelection={mainModelSelection}
        setMainModelSelection={setMainModelSelection}
        mainCustomModel={mainCustomModel}
        setMainCustomModel={setMainCustomModel}
        liveModelSelection={liveModelSelection}
        setLiveModelSelection={setLiveModelSelection}
        liveCustomModel={liveCustomModel}
        setLiveCustomModel={setLiveCustomModel}
        diarizationModelSelection={diarizationModelSelection}
        setDiarizationModelSelection={setDiarizationModelSelection}
        diarizationCustomModel={diarizationCustomModel}
        setDiarizationCustomModel={setDiarizationCustomModel}
        modelCacheStatus={modelCacheStatus}
        isRunning={isRunning}
        refreshCacheStatus={refreshCacheStatus}
        isMetal={isMetal}
        runtimeProfile={runtimeProfile}
        downloadingIds={downloadingIds}
        hostCacheStatus={hostCacheStatus}
        onDownload={downloadModel}
        onRemove={removeModel}
      />
```

- [ ] **Step 4: Retire the sidebar tab**

- `components/views/ModelManagerView.tsx` — delete the file: `git rm components/views/ModelManagerView.tsx`
- `App.tsx` — delete the `import { ModelManagerView }` (line 9) and the whole `case View.MODEL_MANAGER:` block (lines 723-728).
- `components/Sidebar.tsx` — delete the `Models` nav entry (lines 186-190) and the now-unused `Library` icon import.
- `types.ts` — delete the `MODEL_MANAGER` member from the `View` enum.

- [ ] **Step 5: Typecheck and run the full suite**

```bash
npx tsc --noEmit
npx vitest run
```

Expected: no type errors; every test passes. If a test referenced `View.MODEL_MANAGER` or `ModelManagerView`, update it — those are the last two references.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(server): re-home the Model Manager into a Server tab modal and drop its sidebar entry

* feat(server): reach the full cross-family manager from a Manage all models button, so downloading weights for an unselected family and managing the diarization models both survive the sidebar entry going away

* fix(server): delete ModelManagerView rather than mounting it in the modal
  * it owned a second copy of the model selection state and persisted it to the same electron-store keys as ServerView, so mounting both at once would have raced two writers on those keys and silently lost whichever change landed first
  * ModelManagerTab is already presentational, so the modal drives it from the state ServerView already owns

* feat(server): probe the cache for every model in the selected family, not just the active one, so each row reports its own download state"
```

---

## Task 8: UI contract, format, and the full gate

**Files:**
- Modify: `ui-contract/transcription-suite-ui.contract.yaml`, `ui-contract/contract-baseline.json`

- [ ] **Step 1: Check the blur budget before regenerating**

```bash
grep -c backdrop-blur components/models/ModelPickerRow.tsx components/models/ModelRowDetails.tsx components/views/server/MainModelPicker.tsx components/views/ModelManagerModal.tsx
grep -n -A 22 "blur_depth_budgets" ui-contract/transcription-suite-ui.contract.yaml
```

Expected: 0 for each new file. New files get `default_max: 3`, so anything up to 3 is fine — but `InstanceSettingsSelectors.tsx` and `ServerView.tsx` have their own overrides; if you added a blurred surface to either, verify it against the budget.

- [ ] **Step 2: Regenerate the contract**

```bash
npm run format
npm run ui:contract:extract
npm run ui:contract:build
```

- [ ] **Step 3: Revert the machine-specific `repo_path`**

`build-contract.mjs` bakes the absolute path of the tree it ran in. Restore the canonical one so a worktree path is not committed:

```bash
sed -i 's|repo_path: .*/dashboard|repo_path: /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/dashboard|' ui-contract/transcription-suite-ui.contract.yaml
grep -n repo_path ui-contract/transcription-suite-ui.contract.yaml
```

- [ ] **Step 4: Bump `spec_version`, then re-lock the baseline**

The bump must come **before** `--update-baseline`, or validation fails with `semver_bump_required`. Edit `meta.spec_version` in `ui-contract/transcription-suite-ui.contract.yaml` (1.3.0 → 1.4.0), then:

```bash
node scripts/ui-contract/validate-contract.mjs --update-baseline
```

Expected: `Semantic Valid: yes` and a `baseline_updated` warning.

- [ ] **Step 5: Run the full gate**

```bash
npm run check && npm test
echo "exit: $?"
```

Expected: `npm run check` exits 0 (typecheck + lint + prettier + ui-contract), and every test passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(ui-contract): register the model picker components and bump spec_version to 1.4.0"
```

---

## Task 9: Manual smoke test

Automated tests cannot see a layout. Run the app and confirm.

- [ ] **Step 1: Launch**

```bash
npm run dev:electron
```

> If this throws "Electron failed to install correctly" on Node 26, that is a known extract-zip failure — see the memory note; run under Node 22.

- [ ] **Step 2: Walk the Server tab**

- [ ] Main Transcriber shows **8** tiles, not 10. One reads **NeMo Models**, one reads **MLX NeMo**.
- [ ] Selecting **NeMo Models** lists exactly two rows: Parakeet TDT 0.6B and Canary 1B V2.
- [ ] The Canary row carries the translation badge; the Parakeet row does not. (This is the disambiguation that justifies the tile advertising `A⇄B`.)
- [ ] Clicking a row's chevron expands it to the repo id, params, badges, and description.
- [ ] Selecting **Whisper** lists 9 rows; **Whisper.cpp** lists 11. Neither makes the page unusable.
- [ ] The custom row reveals the `owner/model-name` input and it still persists.
- [ ] Every row is locked while the server is running.
- [ ] **Manage all models** opens the modal with all 7 family sections including Diarization; closing it and reopening does not lose a selection made inside it. **This is the dual-write regression check** — change the main model inside the modal, close it, and confirm the Server tab reflects the change rather than reverting.
- [ ] The sidebar has no **Models** entry, and nothing in the app links to a dead route.
- [ ] Squeeze the window narrow: the Server tab still lays out, and the scroll-edge fades from the earlier fix still work.

---

## Self-review notes

- **Spec coverage:** §1.1-1.5 → Task 1. §2.1-2.2 → Tasks 2, 3, 5. §2.3 → Tasks 4, 4b, 7. §2.4 → Task 5. §2.5 → Task 7. §3 → tests in Tasks 1-5. §4 risk 3 (blur budget) → Task 8 Step 1.
- **The WSL2 trap.** The first draft of this plan had `ServerView` write a fresh `downloadModel(id)`. That would have silently dropped the vulkan-wsl2 GGML path, which sends whisper.cpp weights to the Windows host through a different IPC call and a different cache probe. Task 4b exists specifically to extract that logic rather than re-derive it, and `useModelDownloads.test.ts` pins all three storage paths.
- **Single ownership.** `ServerView` owns exactly one `useModelCache` and one `useModelDownloads`. Both the picker and the modal are fed from those. Any change that gives `ModelManagerTab` back its own copy re-opens the dual-write bug that killed `ModelManagerView` (spec §2.3).
- **Out of scope, deliberately:** the Live Mode Model dropdown stays a dropdown; it will look inconsistent beside the new picker and that is an accepted, deferred cost.
- **Verify against the real code, not this plan.** Line numbers here were read at `1f80c6cc`. Task 1 shifts `instanceMatrix.ts`, and Task 2 shifts `ModelManagerTab.tsx`, so later tasks' line references drift. Anchor on the quoted code, not the numbers.
