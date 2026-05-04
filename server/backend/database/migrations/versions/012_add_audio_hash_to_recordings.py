"""Add audio_hash column to recordings (Issue #104, Sprint 2 carve-out — Item 2).

Mirrors migration 011, which added audio_hash to transcription_jobs.
Sprint 2 scoped dedup to the /api/transcribe/import path (transcription_jobs
table) but the dashboard's primary file-picker calls
/api/notebook/transcribe/upload, which writes to the recordings table.
This migration plus its companion plumbing (save_longform_to_database +
find_recordings_by_audio_hash + find_duplicates_anywhere) closes the
notebook-upload dedup gap so cross-flow detection works:

  - file imported via /audio yesterday, then via notebook today    → dedup
  - file uploaded twice through the notebook tab                   → dedup
  - file imported via notebook yesterday, then via /audio today    → dedup

Cross-references:
  - FR2 (audio dedup by content hash)
  - NFR21 (non-destructive migration: existing rows get NULL)
  - NFR22 (forward-only)
  - R-EL23 (per-user-library dedup scope)

Legacy rows: existing recordings rows retain NULL audio_hash. The
dedup-check query excludes NULL hashes from match results, so legacy
recordings simply do not participate in dedup until they are re-imported.
Backfill is intentionally out of scope (would require re-reading every
preserved audio file).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
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
    """Add audio_hash column and covering index on recordings."""
    _revision_metadata()
    conn = op.get_bind()

    # SQLite ALTER TABLE ADD COLUMN is non-destructive on existing rows
    # (they get NULL by default — see NFR21).
    conn.execute(text("ALTER TABLE recordings ADD COLUMN audio_hash TEXT"))

    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_recordings_audio_hash ON recordings(audio_hash)")
    )


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
