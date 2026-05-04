"""Add normalized_audio_hash to transcription_jobs and recordings
(Issue #104, Sprint 2 carve-out — Item 3).

Sprint 2 + Item 2 hashed the raw upload bytes for dedup. Two encodings of
the same content (MP3 vs WAV vs M4A from the same source) produce
different raw hashes, so format-converted re-imports of the same audio
do not dedup against each other. This migration adds a parallel column
that holds the SHA-256 over a normalized PCM rendering (16 kHz mono int16
WAV produced by ffmpeg). The dedup-check query is extended to OR over
both columns; two-column hits on the same row collapse to a single
match.

Cross-references:
  - FR2 (audio dedup by content hash)
  - NFR21 (non-destructive migration: existing rows get NULL)
  - NFR22 (forward-only)
  - R-EL23 (per-user-library dedup scope)

Format-agnostic dedup is opt-in: when ffmpeg fails on a given upload,
the row keeps `normalized_audio_hash = NULL` and only participates in
raw-byte dedup. Legacy rows (pre-013) carry NULL on both columns and
never appear as matches.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _revision_metadata() -> tuple[
    str,
    str | None,
    str | Sequence[str] | None,
    str | Sequence[str] | None,
]:
    return revision, down_revision, branch_labels, depends_on


def upgrade() -> None:
    """Add normalized_audio_hash column + covering index on both tables."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(text("ALTER TABLE transcription_jobs ADD COLUMN normalized_audio_hash TEXT"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_transcription_jobs_normalized_audio_hash "
            "ON transcription_jobs(normalized_audio_hash)"
        )
    )

    conn.execute(text("ALTER TABLE recordings ADD COLUMN normalized_audio_hash TEXT"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_recordings_normalized_audio_hash "
            "ON recordings(normalized_audio_hash)"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
