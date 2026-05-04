"""Add audio_hash column to transcription_jobs (Issue #104, Story 2.1).

Stores the SHA-256 hex digest of normalized PCM (16 kHz mono int16) for
each completed import job. Story 2.2 writes the value during the import
flow; Story 2.4 reads it via the dedup-check endpoint.

Cross-references:
  - FR2 (audio dedup by content hash)
  - NFR21 (non-destructive migration: existing rows get NULL)
  - NFR22 (forward-only)
  - R-EL23 (per-user-library dedup scope)

Legacy rows: existing transcription_jobs rows retain NULL audio_hash.
The dedup-check endpoint excludes NULL hashes from match results.
Backfill is intentionally out of scope (would require re-reading every
preserved audio file).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _revision_metadata() -> tuple[
    str,
    str | None,
    str | Sequence[str] | None,
    str | Sequence[str] | None,
]:
    """Reference Alembic metadata globals for static analyzers."""
    return revision, down_revision, branch_labels, depends_on


def upgrade() -> None:
    """Add audio_hash column and covering index."""
    _revision_metadata()
    conn = op.get_bind()

    # SQLite ALTER TABLE ADD COLUMN is non-destructive on existing rows
    # (they get NULL by default — see migration log note below).
    conn.execute(text("ALTER TABLE transcription_jobs ADD COLUMN audio_hash TEXT"))

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_transcription_jobs_audio_hash "
            "ON transcription_jobs(audio_hash)"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
