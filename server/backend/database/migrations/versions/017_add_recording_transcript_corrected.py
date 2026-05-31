"""Add transcript_corrected column to recordings (in-place transcript editing).

Backs the Audio-Note hybrid edit mode: a user may hand-correct a recording's
transcript and have it persisted WITHOUT touching the original segments /
word-timestamps. This column is purely additive and nullable:

    NULL / empty  — no correction; the rich segment view is the source of truth
    TEXT          — the user's flattened, hand-corrected transcript

Revert = set this column back to NULL (the original segments are intact, so the
word-clickable view returns). This preserves the project's data-loss invariant
(NFR21 non-destructive) and is forward-only (NFR22).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | None = "016"
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
    """Add the nullable, non-destructive transcript_corrected column."""
    _revision_metadata()
    conn = op.get_bind()

    # SQLite ALTER TABLE ADD COLUMN is non-destructive on existing rows
    # (they default to NULL — see NFR21).
    conn.execute(text("ALTER TABLE recordings ADD COLUMN transcript_corrected TEXT"))


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
