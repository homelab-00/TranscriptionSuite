"""Add auto-action status columns to recordings (Issue #104, Story 6.2/6.3).

Adds 9 columns to ``recordings`` to track the lifecycle of auto-summary and
auto-export per recording. The columns are 1:1 with the recording row —
no fan-out to a separate table — so deletion cascades naturally and the
sweeper / retry endpoint scan a single row per recording.

Status enum (TEXT, enforced at the repository layer):

    NULL                          — toggle off / not applicable
    pending                       — scheduled but not started (manual retry)
    in_progress                   — LLM call / file write in flight
    success                       — committed; on_auto_summary_fired done
    summary_empty                 — Story 6.7: <10 chars (amber)
    summary_truncated             — Story 6.7: provider signaled truncation
    held                          — R-EL10: HOLD predicate true
    deferred                      — Story 6.8: destination missing
    retry_pending                 — Story 6.11: one auto-retry scheduled
    failed                        — transient terminal failure
    manual_intervention_required  — Story 6.11: auto-retry exhausted

Cross-references:
  - FR30, FR31, FR32, FR35, FR36, FR37, FR38, FR39
  - R-EL10 (HOLD), R-EL12 (deferred), R-EL16 (empty), R-EL17 (truncated),
    R-EL18 (escalation), R-EL27 (idempotent retry)
  - NFR16 (Persist-Before-Deliver), NFR21 (non-destructive), NFR22 (forward-only)
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | None = "014"
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
    """Add auto-action status tracking columns + partial indexes."""
    _revision_metadata()
    conn = op.get_bind()

    # Auto-summary lifecycle
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_summary_status TEXT"))
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_summary_error TEXT"))
    conn.execute(
        text("ALTER TABLE recordings ADD COLUMN auto_summary_attempts INTEGER NOT NULL DEFAULT 0")
    )
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_summary_completed_at TIMESTAMP"))

    # Auto-export lifecycle
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_export_status TEXT"))
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_export_error TEXT"))
    conn.execute(
        text("ALTER TABLE recordings ADD COLUMN auto_export_attempts INTEGER NOT NULL DEFAULT 0")
    )
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_export_path TEXT"))
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_export_completed_at TIMESTAMP"))

    # Profile-snapshot used at auto-action time. Mirrors the per-job snapshot
    # already on transcription_jobs (migration 009) but on recordings — so
    # the retry endpoint and the deferred-export sweeper can read the
    # original profile context without joining through transcription_jobs
    # (which is not always present for notebook-only recordings).
    conn.execute(text("ALTER TABLE recordings ADD COLUMN auto_action_profile_snapshot TEXT"))

    # Partial indexes (only rows with non-NULL status — sweeper / retry scope)
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_recordings_auto_summary_status "
            "ON recordings(auto_summary_status) WHERE auto_summary_status IS NOT NULL"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_recordings_auto_export_status "
            "ON recordings(auto_export_status) WHERE auto_export_status IS NOT NULL"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
