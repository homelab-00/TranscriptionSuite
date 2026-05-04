/**
 * Snapshot test for alias-aware speaker rendering (Issue #104, Story 4.4 AC2).
 *
 * This is one of the propagation snapshots required by NFR52 (≥4 across
 * the sprint). The other 4 cover plaintext + subtitle + AI summary +
 * AI chat (server-side, in tests/test_*_alias_propagation_snapshot.py).
 */

import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SpeakerRenameInput } from '../SpeakerRenameInput';
import { buildSpeakerLabelMap, labelFor } from '../../../src/utils/aliasSubstitution';

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

interface Segment {
  speaker?: string | null;
  text: string;
}

function TranscriptStub({
  segments,
  aliases,
}: {
  segments: Segment[];
  aliases: Record<string, string>;
}) {
  const labelMap = buildSpeakerLabelMap(segments, aliases);
  return (
    <ul data-testid="transcript">
      {segments.map((seg, i) => (
        <li key={i}>
          {seg.speaker && (
            <SpeakerRenameInput
              speakerId={seg.speaker}
              currentLabel={labelFor(seg.speaker, labelMap)}
              onCommit={() => {}}
            />
          )}
          <span> · {seg.text}</span>
        </li>
      ))}
    </ul>
  );
}

describe('Alias propagation snapshot — Story 4.4 AC2', () => {
  it('renders 5 speakers with 2 aliased — golden snapshot', () => {
    const segments: Segment[] = [
      { speaker: 'SPEAKER_00', text: 'Welcome everyone.' },
      { speaker: 'SPEAKER_01', text: 'Thanks for having us.' },
      { speaker: 'SPEAKER_02', text: 'I have a question.' },
      { speaker: 'SPEAKER_00', text: 'Go ahead.' },
      { speaker: 'SPEAKER_03', text: 'Following up on that...' },
      { speaker: 'SPEAKER_04', text: 'Last point.' },
    ];
    const aliases = {
      SPEAKER_00: 'Elena Vasquez',
      SPEAKER_02: 'Sami Patel',
    };

    const { container } = render(<TranscriptStub segments={segments} aliases={aliases} />);
    expect(container).toMatchSnapshot();
  });

  it('all turns of the same speaker_id show the same alias (FR22)', () => {
    const segments: Segment[] = [
      { speaker: 'SPEAKER_00', text: 'Turn 1.' },
      { speaker: 'SPEAKER_01', text: 'Other speaker.' },
      { speaker: 'SPEAKER_00', text: 'Turn 2.' },
      { speaker: 'SPEAKER_00', text: 'Turn 3.' },
    ];
    const { getAllByRole } = render(
      <TranscriptStub segments={segments} aliases={{ SPEAKER_00: 'Elena' }} />,
    );
    const buttons = getAllByRole('button');
    // 4 segments × 1 button per segment with a speaker = 4 buttons
    expect(buttons).toHaveLength(4);
    // 3 of them are SPEAKER_00 → "Elena"
    const elenaButtons = buttons.filter((b) => b.textContent === 'Elena');
    expect(elenaButtons).toHaveLength(3);
    // 1 of them is SPEAKER_01 → "Speaker 2" (because SPEAKER_00 is alias-overridden,
    // SPEAKER_01 is the FIRST raw label without an alias, gets "Speaker 1"... wait no.
    // First-appearance ordering processes SPEAKER_00 first (gets alias),
    // then SPEAKER_01 (no alias) gets "Speaker 1" (counter starts at 1).
    const otherButtons = buttons.filter((b) => b.textContent === 'Speaker 1');
    expect(otherButtons).toHaveLength(1);
  });
});
