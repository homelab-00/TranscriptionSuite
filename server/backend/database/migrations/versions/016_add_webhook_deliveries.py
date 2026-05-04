"""Add webhook_deliveries table (Issue #104, Story 7.1).

Creates the per-attempt webhook delivery persistence table that backs
the WebhookWorker's Persist-Before-Deliver invariant (Story 7.5 / NFR17 /
R-EL33). Each row represents ONE attempt to call a configured webhook
URL — a recording with three failed retries produces three rows. This
1:N shape is intentional and contrasts with Sprint 4's auto-action
columns which were 1:1 with the recording row.

Status enum (TEXT with CHECK constraint per AC1):

    pending                       — written by producer; not yet picked up
    in_flight                     — worker dequeued; HTTP call about to fire
    success                       — 2xx response received
    failed                        — non-2xx / timeout / transport — retries left
    manual_intervention_required  — Story 7.7 AC2: auto-retry exhausted

Foreign keys:
  - recording_id ON DELETE CASCADE — delivery rows are tied to the recording;
    deleting the recording removes its attempt history.
  - profile_id ON DELETE SET NULL — profile deletion does NOT cascade so
    historical attempts remain queryable for traceability (NFR42).

Indexes:
  - idx_webhook_deliveries_status (PARTIAL on pending/in_flight) — covers the
    worker's drain query without indexing the long tail of success rows.
  - idx_webhook_deliveries_recording — covers the dashboard "latest status
    for this recording" lookup.

Cross-references:
  - FR47 (delivery persistence), NFR16 (Persist-Before-Deliver),
    NFR17 (delivery durability), NFR21 (non-destructive),
    NFR22 (forward-only), NFR40 (retention), R-EL33, ADR-006
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | None = "015"
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
    """Create webhook_deliveries table + the two partial indexes."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id      INTEGER NOT NULL
                                    REFERENCES recordings(id) ON DELETE CASCADE,
                profile_id        INTEGER
                                    REFERENCES profiles(id) ON DELETE SET NULL,
                status            TEXT NOT NULL CHECK (status IN (
                                      'pending',
                                      'in_flight',
                                      'success',
                                      'failed',
                                      'manual_intervention_required'
                                  )),
                attempt_count     INTEGER NOT NULL DEFAULT 0,
                last_error        TEXT,
                created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_attempted_at TIMESTAMP,
                payload_json      TEXT NOT NULL
            )
            """
        )
    )

    # Worker drain query — only scans pending + in_flight rows.
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status "
            "ON webhook_deliveries(status) "
            "WHERE status IN ('pending', 'in_flight')"
        )
    )
    # Dashboard "latest status" lookup + escalation policy
    # consecutive-failure count.
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_recording "
            "ON webhook_deliveries(recording_id)"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
