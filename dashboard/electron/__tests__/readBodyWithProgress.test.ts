// @vitest-environment node

import { describe, it, expect } from 'vitest';
import { readBodyWithProgress } from '../readBodyWithProgress.js';

function streamOf(chunks: Buffer[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new Uint8Array(chunk));
      controller.close();
    },
  });
}

describe('readBodyWithProgress', () => {
  it('returns the whole body and reports the running byte count', async () => {
    const seen: number[] = [];

    const body = await readBodyWithProgress(
      streamOf([Buffer.from('MZ'), Buffer.from('payload')]),
      (received) => seen.push(received),
    );

    expect(body.toString()).toBe('MZpayload');
    expect(seen).toEqual([2, 9]);
  });

  it('rejects a response without a body', async () => {
    await expect(readBodyWithProgress(null, () => {})).rejects.toThrow(/no body/i);
  });

  it('ignores a progress callback that throws', async () => {
    const body = await readBodyWithProgress(streamOf([Buffer.from('abc')]), () => {
      throw new Error('bar bug');
    });

    expect(body.toString()).toBe('abc');
  });
});
