export const HF_TERMS_URL = 'https://huggingface.co/pyannote/speaker-diarization-community-1';
export const HF_TOKENS_URL = 'https://huggingface.co/settings/tokens';

interface HfTokenExplainerProps {
  onOpenLink: (url: string) => void;
}

/**
 * Shared explanation of why speaker diarization needs a Hugging Face token.
 * Used by the first-run setup modal (App.tsx) and the Settings modal (GH-208).
 */
export function HfTokenExplainer({ onOpenLink }: HfTokenExplainerProps) {
  return (
    <div className="space-y-2 text-xs leading-relaxed text-slate-400">
      <p>
        Speaker diarization (who spoke when) uses the gated PyAnnote model from Hugging Face. The
        token is used once, to download the model weights. Nothing is uploaded, and there is no
        payment involved.
      </p>
      <ul className="list-disc space-y-1 pl-4">
        <li>A free, read-only token is sufficient.</li>
        <li>After the download, diarization runs entirely locally.</li>
        <li>
          No token is needed for models with built-in diarization, such as VibeVoice or SenseVoice
          (CAM++).
        </li>
      </ul>
      <p>
        1.{' '}
        <button
          type="button"
          onClick={() => onOpenLink(HF_TERMS_URL)}
          className="text-accent-cyan hover:underline"
        >
          Accept the model terms
        </button>{' '}
        on Hugging Face (required by PyAnnote before the weights can be downloaded).
      </p>
      <p>
        2.{' '}
        <button
          type="button"
          onClick={() => onOpenLink(HF_TOKENS_URL)}
          className="text-accent-cyan hover:underline"
        >
          Create a read-only token
        </button>{' '}
        and paste it below.
      </p>
    </div>
  );
}
