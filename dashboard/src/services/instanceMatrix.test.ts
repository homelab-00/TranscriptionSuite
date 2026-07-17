import { describe, expect, it } from 'vitest';

import {
  DIARIZATION_BUILTIN_LABEL,
  DIARIZATION_CAMPP_OPTION,
  DIARIZATION_DEFAULT_MODEL,
  DIARIZATION_SORTFORMER_OPTION,
  FAMILY_CHOICE_IDS,
  type FamilyChoiceId,
  defaultMainModelFor,
  defaultModelForFamilyChoice,
  diarizationTilesFor,
  familyChoiceForModel,
  familyChoicesFor,
  liveTilesFor,
  modelsForFamilyChoice,
} from './instanceMatrix';
import { MODEL_REGISTRY } from './modelRegistry';
import { MAIN_RECOMMENDED_MODEL, VULKAN_RECOMMENDED_MODEL, WHISPER_MEDIUM } from './modelSelection';
import type { RuntimeProfile } from '../types/runtime';

const RUNTIMES: RuntimeProfile[] = ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'];

/**
 * The verified compatibility matrix (design spec 2026-07-11, section 3).
 * true = selectable as main transcriber on that runtime profile.
 */
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

describe('instanceMatrix: familyChoicesFor', () => {
  it.each(RUNTIMES)('%s exposes every family choice exactly once', (runtime) => {
    const ids = familyChoicesFor(runtime).map((c) => c.id);
    expect([...ids].sort()).toEqual([...FAMILY_CHOICE_IDS].sort());
  });

  for (const runtime of RUNTIMES) {
    for (const id of FAMILY_CHOICE_IDS) {
      const expected = EXPECTED_FAMILY_MATRIX[id][runtime];
      it(`${runtime} × ${id} → ${expected ? 'enabled' : 'disabled'}`, () => {
        const choice = familyChoicesFor(runtime).find((c) => c.id === id);
        expect(choice).toBeDefined();
        expect(choice!.enabled).toBe(expected);
        if (!expected) {
          expect(choice!.reason).toBeTruthy();
        }
      });
    }
  }

  it('the NeMo family on cpu carries an NVIDIA reason (mirrors applyCpuModelDefaults)', () => {
    const choices = familyChoicesFor('cpu');
    expect(choices.find((c) => c.id === 'nemo')?.reason).toMatch(/NVIDIA/i);
  });

  it('sensevoice/vibevoice on cpu warn about speed but stay selectable', () => {
    const choices = familyChoicesFor('cpu');
    for (const id of ['sensevoice', 'vibevoice'] as const) {
      const choice = choices.find((c) => c.id === id)!;
      expect(choice.enabled).toBe(true);
      expect(choice.hint).toMatch(/cpu/i);
    }
  });
});

describe('instanceMatrix: familyChoiceForModel', () => {
  it.each(Object.entries(REPRESENTATIVE_MODEL))('classifies %s exemplar', (id, model) => {
    expect(familyChoiceForModel(model)).toBe(id);
  });

  it('classifies every main-role registry model into an existing choice', () => {
    for (const model of MODEL_REGISTRY.filter((m) => m.roles.includes('main'))) {
      const choice = familyChoiceForModel(model.id);
      expect(choice, model.id).not.toBeNull();
      expect(FAMILY_CHOICE_IDS).toContain(choice!);
    }
  });

  it('returns null for empty and sentinel values', () => {
    expect(familyChoiceForModel('')).toBeNull();
    expect(familyChoiceForModel(null)).toBeNull();
    expect(familyChoiceForModel(undefined)).toBeNull();
    expect(familyChoiceForModel('__none__')).toBeNull();
  });

  it('keeps MLX VibeVoice out of the CUDA VibeVoice family (registry ordering bug guard)', () => {
    expect(familyChoiceForModel('mlx-community/VibeVoice-ASR-bf16')).toBe('mlx-vibevoice');
  });
});

describe('instanceMatrix: modelsForFamilyChoice consistency with MODEL_REGISTRY', () => {
  it.each(FAMILY_CHOICE_IDS)('%s has at least one registry model', (id) => {
    expect(modelsForFamilyChoice(id).length).toBeGreaterThan(0);
  });

  it('partitions the main-role registry without overlap or loss', () => {
    const mains = MODEL_REGISTRY.filter((m) => m.roles.includes('main'));
    const seen = new Map<string, FamilyChoiceId>();
    for (const id of FAMILY_CHOICE_IDS) {
      for (const model of modelsForFamilyChoice(id)) {
        expect(seen.has(model.id), `${model.id} in two families`).toBe(false);
        seen.set(model.id, id);
      }
    }
    expect(seen.size).toBe(mains.length);
  });

  it('registry requiresRuntime agrees with the family matrix', () => {
    for (const id of FAMILY_CHOICE_IDS) {
      for (const model of modelsForFamilyChoice(id)) {
        if (model.requiresRuntime === 'vulkan') {
          expect(EXPECTED_FAMILY_MATRIX[id].vulkan, model.id).toBe(true);
        }
        if (model.requiresRuntime === 'cuda') {
          expect(EXPECTED_FAMILY_MATRIX[id].gpu, model.id).toBe(true);
          expect(EXPECTED_FAMILY_MATRIX[id].metal, model.id).toBe(false);
        }
      }
    }
  });

  it('only whisper and whispercpp registry models carry the live role (backend live.py gate)', () => {
    for (const model of MODEL_REGISTRY.filter((m) => m.roles.includes('live'))) {
      expect(['whisper', 'whispercpp']).toContain(familyChoiceForModel(model.id));
    }
  });
});

describe('instanceMatrix: liveTilesFor (full cross-product)', () => {
  const LIVE_CAPABLE_MAINS: FamilyChoiceId[] = ['whisper', 'whispercpp'];
  for (const runtime of RUNTIMES) {
    for (const mainId of FAMILY_CHOICE_IDS) {
      if (!EXPECTED_FAMILY_MATRIX[mainId][runtime]) continue; // impossible combo
      const mainModel = REPRESENTATIVE_MODEL[mainId];
      it(`${runtime} + main=${mainId}`, () => {
        const tiles = liveTilesFor(runtime, mainModel);
        const byId = new Map(tiles.map((t) => [t.id, t]));
        expect(byId.get('same-as-main')!.enabled).toBe(LIVE_CAPABLE_MAINS.includes(mainId));
        expect(byId.get('disabled')!.enabled).toBe(true);
        // faster-whisper live decoding works everywhere (CPU fallback on
        // vulkan/metal — server/backend/pyproject.toml mlx extra ships it).
        const whisper = byId.get('whisper')!;
        expect(whisper.enabled).toBe(true);
        if (runtime === 'metal' || runtime === 'vulkan' || runtime === 'vulkan-wsl2') {
          expect(whisper.hint).toMatch(/cpu/i);
        }
        const ggml = byId.get('whispercpp')!;
        expect(ggml.enabled).toBe(runtime === 'vulkan' || runtime === 'vulkan-wsl2');
      });
    }
  }

  it('same-as-main explains why it is unavailable for non-live mains', () => {
    const tiles = liveTilesFor('gpu', REPRESENTATIVE_MODEL.nemo);
    const same = tiles.find((t) => t.id === 'same-as-main')!;
    expect(same.enabled).toBe(false);
    expect(same.reason).toBeTruthy();
  });
});

describe('instanceMatrix: diarizationTilesFor (full cross-product)', () => {
  for (const runtime of RUNTIMES) {
    for (const mainId of FAMILY_CHOICE_IDS) {
      if (!EXPECTED_FAMILY_MATRIX[mainId][runtime]) continue;
      const mainModel = REPRESENTATIVE_MODEL[mainId];
      it(`${runtime} + main=${mainId}`, () => {
        const tiles = diarizationTilesFor(runtime, mainModel);
        const byId = new Map(tiles.map((t) => [t.id, t]));

        if (mainId === 'whispercpp') {
          // whisper.cpp mains cannot diarize at all.
          expect(tiles).toHaveLength(0);
          return;
        }
        if (mainId === 'vibevoice' || mainId === 'mlx-vibevoice') {
          // VibeVoice diarizes natively; the engine choice is locked.
          expect(tiles).toHaveLength(1);
          expect(tiles[0].id).toBe('builtin');
          expect(tiles[0].enabled).toBe(true);
          expect(tiles[0].isDefault).toBe(true);
          return;
        }

        expect(byId.get('builtin')).toBeUndefined();
        const pyannote = byId.get('pyannote')!;
        expect(pyannote.enabled).toBe(true);
        expect(pyannote.storedValue).toBe(DIARIZATION_DEFAULT_MODEL);

        const campp = byId.get('campp')!;
        expect(campp.enabled).toBe(mainId === 'sensevoice');
        expect(campp.storedValue).toBe(DIARIZATION_CAMPP_OPTION);
        if (mainId !== 'sensevoice') expect(campp.reason).toBe('SenseVoice only');

        const sortformer = byId.get('sortformer')!;
        expect(sortformer.enabled).toBe(runtime === 'metal');
        expect(sortformer.storedValue).toBe(DIARIZATION_SORTFORMER_OPTION);
        if (runtime !== 'metal') expect(sortformer.reason).toBe('Requires Metal');

        // The custom-repo tile was removed entirely.
        expect(tiles.some((t) => t.label === 'Custom')).toBe(false);

        // Exactly one default, and it matches the engine hierarchy.
        const defaults = tiles.filter((t) => t.isDefault);
        expect(defaults).toHaveLength(1);
        if (mainId === 'sensevoice') expect(defaults[0].id).toBe('campp');
        else if (runtime === 'metal') expect(defaults[0].id).toBe('sortformer');
        else expect(defaults[0].id).toBe('pyannote');
      });
    }
  }

  it('keeps the persisted option strings stable (electron-store compat)', () => {
    expect(DIARIZATION_CAMPP_OPTION).toBe('CAM++ (fast, built-in)');
    expect(DIARIZATION_SORTFORMER_OPTION).toBe('Sortformer (Metal; ≤ 4 speakers)');
    expect(DIARIZATION_DEFAULT_MODEL).toBe('pyannote/speaker-diarization-community-1');
    expect(DIARIZATION_BUILTIN_LABEL).toBeTruthy();
  });

  it('custom mains fall back to whisper-like diarization rules', () => {
    const tiles = diarizationTilesFor('gpu', 'someone/finetuned-whisper');
    expect(tiles.find((t) => t.id === 'pyannote')!.enabled).toBe(true);
    expect(tiles.find((t) => t.id === 'campp')!.enabled).toBe(false);
  });

  it('disabled main keeps the server-wide pyannote default available', () => {
    const tiles = diarizationTilesFor('gpu', '__none__');
    expect(tiles.find((t) => t.id === 'pyannote')!.enabled).toBe(true);
  });
});

describe('instanceMatrix: defaultMainModelFor', () => {
  it('matches per-runtime recommended defaults', () => {
    expect(defaultMainModelFor('gpu')).toBe(MAIN_RECOMMENDED_MODEL);
    expect(defaultMainModelFor('cpu')).toBe(WHISPER_MEDIUM);
    expect(defaultMainModelFor('vulkan')).toBe(VULKAN_RECOMMENDED_MODEL);
    expect(defaultMainModelFor('vulkan-wsl2')).toBe(VULKAN_RECOMMENDED_MODEL);
    expect(defaultMainModelFor('metal')).toBe('mlx-community/parakeet-tdt-0.6b-v3');
  });

  it('every default is enabled on its own runtime', () => {
    for (const runtime of RUNTIMES) {
      const model = defaultMainModelFor(runtime);
      const choice = familyChoiceForModel(model)!;
      expect(EXPECTED_FAMILY_MATRIX[choice][runtime], `${runtime} → ${model}`).toBe(true);
    }
  });
});

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

  // The tile advertises the family maximum, so the maximum has to be real.
  // The MLX Canary port ships ASR only (backend capabilities.py
  // supports_english_translation returns False for it), so the MLX tile must
  // NOT claim translation, even though the CUDA Canary genuinely does.
  it('advertises translation on the CUDA NeMo tile but not the MLX one', () => {
    const byId = (runtime: RuntimeProfile) =>
      new Map(familyChoicesFor(runtime).map((c) => [c.id, c]));

    expect(byId('gpu').get('nemo')!.capabilities.translation).toBe('multilingual');
    expect(byId('metal').get('mlx-nemo')!.capabilities.translation).toBe('none');
  });
});
