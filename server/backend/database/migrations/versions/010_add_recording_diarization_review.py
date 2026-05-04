"""Add recording_diarization_review table (Issue #104, Story 1.9 — ADR-009).

Lifecycle states (CHECK constraint):
  pending     — review queued, no human input yet
  in_review   — user is actively editing speaker labels
  completed   — review finalised, ready for release
  released    — auto-summary HOLD lifted; downstream consumers can fire

The lifecycle state machine itself lives in Story 5.6 (Sprint 3); this
migration provides only the table + repository CRUD stubs.

Cross-references:
  - FR27 (review state persists)
  - NFR23 (state survives DB restore)
  - R-EL19 (review-state lifecycle)
  - R-EL20 (persistent-banner trigger)

Forward-only per NFR22.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | None = "009"
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
    """Create recording_diarization_review table."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS recording_diarization_review (
                recording_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN
                    ('pending', 'in_review', 'completed', 'released')),
                reviewed_turns_json TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            )
            """
        )
    )

    # Helper index for the persistent-banner query (status IN ('pending','in_review'))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_diarization_review_status "
            "ON recording_diarization_review(status)"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22 + ADR-009."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
