/**
 * AudioVisualizer — render-gating tests for Issue #87 idle SVG branch.
 *
 * Covers the I/O & Edge-Case Matrix from spec-gh-87-idle-visualizer-svg-keyframes.md:
 *   - true idle (no analyser, !isActive)  → SVG branch renders
 *   - analyser attached but !isActive     → blank (no SVG, no canvas paint)
 *   - isActive=true                       → existing canvas branch renders
 *
 * jsdom does not run CSS animations, so this file does NOT assert on
 * keyframe timing — only on which DOM tree is mounted for each prop
 * combination. The animation itself is verified manually per the spec.
 */

import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AudioVisualizer } from '../AudioVisualizer';

afterEach(() => {
  cleanup();
});

describe('AudioVisualizer — idle SVG render gating (Issue #87)', () => {
  it('renders the idle SVG branch when isActive=false and no analyserNode', () => {
    render(<AudioVisualizer />);

    const svg = screen.getByTestId('audio-visualizer-idle-svg');
    expect(svg).toBeInTheDocument();
    expect(svg.tagName.toLowerCase()).toBe('svg');

    const cyanPath = svg.querySelector('path.idle-wave-cyan');
    const magentaPath = svg.querySelector('path.idle-wave-magenta');
    const orangePath = svg.querySelector('path.idle-wave-orange');
    expect(cyanPath).not.toBeNull();
    expect(magentaPath).not.toBeNull();
    expect(orangePath).not.toBeNull();

    expect(cyanPath?.getAttribute('stroke')).toBe('rgba(34,211,238,0.6)');
    expect(magentaPath?.getAttribute('stroke')).toBe('rgba(217,70,239,0.5)');
    expect(orangePath?.getAttribute('stroke')).toBe('rgba(251,146,60,0.3)');

    const canvas = svg.parentElement?.querySelector('canvas');
    expect(canvas).toBeNull();
  });

  it('does NOT render the idle SVG when an analyserNode is attached but isActive=false', () => {
    const fakeAnalyser = {
      frequencyBinCount: 32,
      fftSize: 64,
      getByteFrequencyData: () => {},
      getByteTimeDomainData: () => {},
    } as unknown as AnalyserNode;

    const { container } = render(<AudioVisualizer analyserNode={fakeAnalyser} isActive={false} />);

    expect(screen.queryByTestId('audio-visualizer-idle-svg')).toBeNull();
    expect(container.querySelector('canvas')).not.toBeNull();
  });

  it('does NOT render the idle SVG when isActive=true (canvas branch active)', () => {
    const { container } = render(<AudioVisualizer isActive={true} />);

    expect(screen.queryByTestId('audio-visualizer-idle-svg')).toBeNull();
    expect(container.querySelector('canvas')).not.toBeNull();
  });
});
