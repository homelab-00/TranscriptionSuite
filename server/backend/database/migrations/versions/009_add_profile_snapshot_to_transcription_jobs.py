"""Add profile-snapshot columns to transcription_jobs (Issue #104, Story 1.3).

Two new columns:
  - job_profile_snapshot:  frozen JSON dump of the profile at job-start time.
  - snapshot_schema_version: profile schema_version captured at the same instant.

Both are nullable so legacy rows (no profile association) remain valid.
The worker reads the snapshot, never live profile state, so concurrent
profile edits cannot affect a running job (FR18, R-EL21).

Forward-only per NFR22.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
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
    """Add job_profile_snapshot + snapshot_schema_version columns."""
    _revision_metadata()
    conn = op.get_bind()

    existing = conn.execute(text("PRAGMA table_info(transcription_jobs)")).fetchall()
    existing_names = {row[1] for row in existing}

    if "job_profile_snapshot" not in existing_names:
        conn.execute(text("ALTER TABLE transcription_jobs ADD COLUMN job_profile_snapshot TEXT"))

    if "snapshot_schema_version" not in existing_names:
        conn.execute(text("ALTER TABLE transcription_jobs ADD COLUMN snapshot_schema_version TEXT"))


def downgrade() -> None:
    """Forward-only — see NFR22 + ADR-003."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
