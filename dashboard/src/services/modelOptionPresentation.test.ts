import { describe, it, expect } from 'vitest';
import { buildModelOptionPresentation } from './modelOptionPresentation';
import type { ModelInfo } from './modelRegistry';

const models = [
  { id: 'a/model-big', displayName: 'Big Model', approxSize: '~3 GB' },
  { id: 'b/model-small', displayName: 'Small Model', approxSize: '~500 MB' },
] as ModelInfo[];

describe('buildModelOptionPresentation (GH-213)', () => {
  it('sorts downloaded models first, keeps sentinels pinned at the tail', () => {
    const p = buildModelOptionPresentation(
      models,
      { 'b/model-small': { exists: true, size: '486 MB' } },
      ['None (Disabled)'],
    );
    expect(p.options).toEqual(['b/model-small', 'a/model-big', 'None (Disabled)']);
  });

  it('labels, descriptions, and badges', () => {
    const p = buildModelOptionPresentation(
      models,
      { 'b/model-small': { exists: true, size: '486 MB' } },
      [],
    );
    expect(p.optionLabel['b/model-small']).toBe('Small Model');
    expect(p.optionDescription['b/model-small']).toBe('b/model-small');
    expect(p.optionMeta['b/model-small'].badge).toBe('Downloaded 486 MB');
  });

  it('exists:false → "Not downloaded" with size hint; unknown (no entry) → size hint only', () => {
    const p = buildModelOptionPresentation(models, { 'a/model-big': { exists: false } }, []);
    expect(p.optionMeta['a/model-big'].badge).toBe('Not downloaded (~3 GB)');
    // cache state unknown, never claim "Not downloaded"
    expect(p.optionMeta['b/model-small'].badge).toBe('~500 MB');
  });

  it('is stable for equal cache states (no reorder within groups)', () => {
    const p = buildModelOptionPresentation(models, {}, []);
    expect(p.options).toEqual(['a/model-big', 'b/model-small']);
  });

  it('downloaded without a size gets a plain Downloaded badge', () => {
    const p = buildModelOptionPresentation(models, { 'a/model-big': { exists: true } }, []);
    expect(p.optionMeta['a/model-big'].badge).toBe('Downloaded');
  });

  it('leaves sentinels without labels, descriptions, or badges', () => {
    const p = buildModelOptionPresentation(models, {}, [
      'None (Disabled)',
      'Custom (HuggingFace repo)',
    ]);
    expect(p.options.slice(-2)).toEqual(['None (Disabled)', 'Custom (HuggingFace repo)']);
    expect(p.optionLabel['None (Disabled)']).toBeUndefined();
    expect(p.optionMeta['Custom (HuggingFace repo)']).toBeUndefined();
  });

  it('handles an empty model list (sentinels only)', () => {
    const p = buildModelOptionPresentation([], {}, ['None (Disabled)']);
    expect(p.options).toEqual(['None (Disabled)']);
    expect(p.optionLabel).toEqual({});
  });
});
