"""
Add recordings.transcription_backend metadata column.

Stores the normalized backend family used to transcribe/import a notebook
recording (e.g. whisper, parakeet, canary, vibevoice_asr).
"""

from collections.abc import Sequence

from alembic import op  # type: ignore[reportMissingImports]
from sqlalchemy import text  # type: ignore[reportMissingImports]

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "004"
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
    """Add recordings.transcription_backend when missing."""
    _revision_metadata()
    conn = op.get_bind()

    existing = conn.execute(text("PRAGMA table_info(recordings)")).fetchall()
    if not any(row[1] == "transcription_backend" for row in existing):
        conn.execute(text("ALTER TABLE recordings ADD COLUMN transcription_backend TEXT"))


def downgrade() -> None:
    """
    No-op downgrade.

    This metadata column is forward-compatible and not worth a destructive table
    rebuild to remove in SQLite.
    """
    pass
