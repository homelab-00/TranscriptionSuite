# Server Tab: NeMo Family Merge + Inline Model Picker — Design Spec

Date: 2026-07-14
Branch: `feat/server-tab-nemo-merge-model-picker`, stacked on
`fix/ui-polish-scroll-fade` (which is itself off `main` @ 1f80c6cc).

This is a separate feature from the scroll-fade fix, so it gets its own branch
per the repo branching policy. It is *stacked* rather than independent because
both are part of one run of UI passes; the fade fix must merge first, or this
branch must be rebased onto `main` before it is opened as a standalone PR.

Supersedes nothing. Builds directly on
[2026-07-11-server-tab-matrix-redesign-design.md](./2026-07-11-server-tab-matrix-redesign-design.md),
whose `instanceMatrix.ts` remains the single source of truth for
runtime × model × live × diarization validity.

## Goal

Two changes to the Server tab's Instance Settings card:

1. Collapse the separate **Parakeet v3** and **Canary v2** Main Transcriber tiles
   into one **NeMo Models** tile. Choosing between the two concrete models moves
   into the model selection below. Do the same for **MLX Parakeet** + **MLX Canary**
   → **MLX NeMo**.
2. Replace the single **Model Variant** dropdown with a detailed, per-model list
   scoped to the selected family. Retire the sidebar **Models** tab; its full
   cross-family manager becomes a **"Manage all models"** modal launched from the
   Server tab.

## Decisions taken (and the alternatives rejected)

| Decision | Chosen | Rejected alternative |
|---|---|---|
| Sidebar Models tab | **Removed.** Full manager reachable as a modal from the Server tab. | Keep the sidebar tab alongside the inline picker. |
| Inline picker scope | **Selected family only.** | Show all ~40 main models grouped by family (would make the family tiles redundant). |
| MLX Parakeet + MLX Canary | **Merge into `mlx-nemo`**, symmetric with the CUDA side. | Merge only the CUDA pair. |
| Row density | **Compact rows that expand into the full detail card on click.** | Full card grid (11-12 cards is too tall); plain compact rows (loses the detail that motivated the change). |
| Live Mode Model dropdown | **Unchanged, stays a dropdown.** Explicitly out of scope. | Convert it too (doubles the surface area for no requested benefit). |

## 1. NeMo family merge

### 1.1 Why this is safe

Parakeet and Canary are **matrix-identical**. In `FAMILY_META` they differ only in
`label`, `accent`, and `capabilities.translation` (`'none'` vs `'multilingual'`).
Every field the compatibility matrix actually branches on is the same for both:

- `live: false` — neither can serve Live Mode (`live.py` gate)
- `diarization: 'pyannote'`, `requiresToken: true`
- identical `familyAvailability()` results on every runtime, including the
  CPU → `REQUIRES_NVIDIA` disable

Therefore merging them **cannot change any live-mode or diarization behavior**.
The same holds for the MLX pair (both `sortformer`, both Metal-only).

### 1.2 No migration required

The family choice is **derived, never persisted**.
`InstanceSettingsSelectors.tsx:188` computes
`selectedFamily = familyChoiceForModel(mainModelSelection)`, and the value
actually written to electron-store is `server.mainModelSelection` — a **model id**
(e.g. `nvidia/parakeet-tdt-0.6b-v3`), not a family id. Collapsing two family ids
into one changes only a derived value, so existing user configs continue to
resolve correctly with no migration step.

**This is a load-bearing invariant.** If a future change persists the family id,
this merge becomes a breaking change.

### 1.3 Changes to `src/services/instanceMatrix.ts`

`FAMILY_CHOICE_IDS` goes from 10 entries to 8:

```
whisper, nemo, sensevoice, vibevoice, whispercpp,
mlx-whisper, mlx-nemo, mlx-vibevoice
```

`FAMILY_META` gains `nemo` and `mlx-nemo`, and loses the four they replace:

| id | label | sublabel | accent | languages | translation | live | diarization | requiresToken |
|---|---|---|---|---|---|---|---|---|
| `nemo` | NeMo Models | NVIDIA Parakeet / Canary | `green` | `25` | `multilingual` | `false` | `pyannote` | `true` |
| `mlx-nemo` | MLX NeMo | Apple Silicon | `green` | `25` | `multilingual` | `false` | `sortformer` | `false` |

The tile advertises the family's **maximum** capability, so both show the `A⇄B`
translation badge. This is intentional: the tile is a coarse filter, and the
per-model rows below disambiguate (the Canary row carries the translation badge,
the Parakeet row does not). Surfacing that distinction is the entire point of §2.

Other edits in the same file:

- `MLX_FAMILIES`: `mlx-parakeet`, `mlx-canary` → `mlx-nemo`
- `familyAvailability()`: the CPU branch `id === 'parakeet' || id === 'canary'`
  becomes `id === 'nemo'` (still returning `REQUIRES_NVIDIA`, mirroring
  `dockerManager applyCpuModelDefaults`)
- `familyChoiceForModel()`: `isMLXParakeetModel(name) || isMLXCanaryModel(name)`
  → `'mlx-nemo'`; `isParakeetModel(name) || isCanaryModel(name)` → `'nemo'`.
  The existing `isNemoModel()` helper in `modelCapabilities.ts` already expresses
  the non-MLX half of this and should be used.
  **Ordering constraint preserved:** MLX checks must still run before the generic
  patterns, matching backend `factory.py`.
- `defaultModelForFamilyChoice()`: `'nemo'` → `MAIN_RECOMMENDED_MODEL` (Parakeet);
  `'mlx-nemo'` → `MLX_DEFAULT_MODEL` (`mlx-community/parakeet-tdt-0.6b-v3`).
  Parakeet is the default in both cases because it is the ASR-only workhorse;
  Canary is the opt-in translation model.

### 1.4 Callers to update

- `InstanceSettingsSelectors.tsx:85` — `FAMILY_ICONS: Record<FamilyChoiceId, ...>`
  is an exhaustive record; it will fail to typecheck until the four old keys are
  replaced by the two new ones. This is a feature, not a chore: it is how the
  compiler enumerates the call sites for us.
- `instanceMatrix.test.ts` — asserts the full runtime × family cross-product.
  It must be updated in lockstep, and **its diff is the primary review surface**
  for this half of the work: it is the artifact that proves no compatibility rule
  changed.

### 1.5 Backend

**No changes.** `factory.py` dispatches on the concrete model name and already
handles Parakeet and Canary independently. The family id is a dashboard-only
presentation concept.

## 2. Inline model picker

### 2.1 What the data actually supports

`ModelInfo` (`src/services/modelRegistry.ts`) carries `displayName`,
`description`, `parameterCount`, `huggingfaceUrl`, `capabilities`
(`translation`, `liveMode`, `diarization`, `languageCount`), `roles`, and
`requiresRuntime`.

**There is no structured size field.** Sizes appear only as prose inside
`description` ("~3.1 GB"), and `modelCacheStatus[id].size` is populated **only
after the model is downloaded**. Rows therefore must **not** promise a size for a
not-yet-downloaded model. They show `parameterCount`, language count, and
capability badges; the real on-disk size appears once the model is cached.

### 2.2 Component structure

Three new components, one extraction, one new hook (§2.3):

| File | New or extracted | Purpose |
|---|---|---|
| `components/models/ModelCard.tsx` | **Extracted** from `ModelManagerTab.tsx`, behavior unchanged | The full detail card: description, capability badges, HF link, download/remove, cache status. |
| `components/models/ModelRow.tsx` | New | One compact row: selection radio, `displayName`, `parameterCount`, language count, capability badges, cached indicator, expand chevron. Expanding renders `<ModelCard>` inline. |
| `components/views/server/MainModelPicker.tsx` | New | The list: `ModelRow` per model in the selected family, a trailing "Custom HuggingFace repo" row, and the "Manage all models" button. Replaces the `Model Variant` `CustomSelect`. |
| `components/views/ModelManagerModal.tsx` | New | Modal shell around the existing `ModelManagerView`. |

Extracting `ModelCard` is what keeps the expanded row and the modal rendering the
**same** component rather than two copies that drift apart.

### 2.3 Shared download/cache state

`ModelManagerView` currently owns `modelCacheStatus`, download progress, and the
MLX status probe. The Server tab now needs the same signals.

Extract that into `src/hooks/useModelCache.ts`, consumed by both the Server tab's
picker and the modal. Without this, the Server tab would have no way to show
"downloaded" state and the two surfaces could disagree about what is cached.

### 2.4 Selection semantics

- Selecting a row writes `server.mainModelSelection` — **identical** to what the
  dropdown does today. No new persistence key, no new store shape.
- The custom-repo row preserves today's `MAIN_MODEL_CUSTOM_OPTION` behavior:
  choosing it reveals the free-text `owner/model-name` input bound to
  `mainCustomModel`.
- Rows are disabled while the server is running, matching the dropdown's existing
  `disabled={isRunning}`.
- The whisper.cpp restart note and the MLX "Metal accelerated" note
  (`InstanceSettingsSelectors.tsx:327-338`) move with the picker.

### 2.5 Retiring the sidebar tab

- `App.tsx:726` — remove the `<ModelManagerView />` route.
- `Sidebar.tsx:188` — remove the `Models` entry.
- `ModelManagerView` itself is **kept** and becomes the modal body. It already
  owns every piece of state the full manager needs, so the modal is a shell, not
  a rewrite.
- The modal retains all 7 family sections including `diarization`, which is what
  preserves cross-family pre-downloads and the pyannote download UI. Losing those
  was the specific risk that made a modal necessary rather than simply deleting
  the tab.

## 3. Testing

| Area | Test |
|---|---|
| `instanceMatrix.ts` | Update `instanceMatrix.test.ts` cross-product to 8 families. Assert `familyChoiceForModel()` maps both `nvidia/parakeet-*` and `nvidia/canary-*` → `'nemo'`, and both MLX variants → `'mlx-nemo'`. Assert `nemo` is disabled with `REQUIRES_NVIDIA` on `cpu`, and enabled on `docker`. Assert live tiles and diarization tiles are **unchanged** for a NeMo main versus the old Parakeet/Canary mains — this is the regression guard for §1.1. |
| `MainModelPicker` | Renders one row per model in the selected family and no others. Selecting a row calls back with the model id. The custom row reveals the text input. Rows are disabled when `isRunning`. |
| `ModelRow` | Collapsed by default; clicking expands to the card. Shows a cached indicator only when `modelCacheStatus[id].exists`. Does **not** render a size when the model is not cached (guards §2.1). |
| `useModelCache` | Cache status resolves per model id; download state transitions. |

## 4. Risks

1. **The tile now over-advertises translation.** A user on the NeMo tile who has
   Parakeet selected sees the family-level `A⇄B` badge on the tile while their
   actual model cannot translate. Mitigated by the per-model rows, which is
   exactly the detail the redesign adds. Accepted deliberately.
2. **Server tab length.** MLX Whisper has 12 models and Whisper.cpp has 11.
   Compact rows are what keep this tractable; the expand-on-click is what keeps
   the detail available without paying for it in vertical space by default.
3. **UI contract.** New components add new className tokens and a new
   `component_coverage` entry. The contract's per-file `backdrop-blur` budget is
   the specific trap: check `grep -c backdrop-blur` against
   `blur_depth_budgets.per_file_overrides` before adding any blurred surface.
   The modal shell is the likely offender.
4. **Scope creep into Live Mode.** The Live Mode Model dropdown will look
   inconsistent next to the new picker. That is a known, accepted, deferred cost.

## 5. Out of scope

- Converting the Live Mode Model dropdown to the new picker.
- Any backend change.
- Any change to the diarization selector.
- Adding a structured `size` field to `ModelInfo` (would let rows show sizes
  pre-download; a genuine improvement, but it means hand-maintaining ~40 sizes).
