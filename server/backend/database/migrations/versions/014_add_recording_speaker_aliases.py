"""Add recording_speaker_aliases table (Issue #104, Story 4.1).

Stores per-recording speaker aliases — the user's mapping from raw
diarization labels (e.g. ``SPEAKER_00``) to display names (e.g.
``Elena Vasquez``). Read at render time by the transcript view, the
plain-text exporter, the subtitle exporter, the AI summary prompt,
and the AI chat context — see ``server/backend/core/alias_substitution.py``
(Story 5.1/5.2/5.3).

Schema invariants:
  - ``UNIQUE(recording_id, speaker_id)`` — one alias per (recording, speaker)
  - ``ON DELETE CASCADE`` — alias rows die with their parent recording
    (Story 4.5 — verified by ``tests/test_alias_cascade_on_recording_delete``)
  - Identity-level (cross-recording) uniqueness is INTENTIONALLY NOT
    enforced — same alias name can appear across recordings (R-EL8 —
    cross-recording aliases deferred to Vision)

Cross-references:
  - FR21 (rename Speaker N to a real name)
  - FR22 (view substitution shows the alias)
  - NFR21 (non-destructive: existing rows untouched)
  - NFR22 (forward-only)
  - R-EL3 (verbatim guarantee: alias_name stored as-is — no NFC/normalize)
  - R-EL8 (per-recording scope; identity-level deferred)
  - ADR-005 (per-recording alias scope decision)
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
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
    """Create recording_speaker_aliases table + supporting index."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS recording_speaker_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                speaker_id TEXT NOT NULL,
                alias_name TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
                UNIQUE (recording_id, speaker_id)
            )
            """
        )
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_recording_speaker_aliases_recording_id "
            "ON recording_speaker_aliases(recording_id)"
        )
    )


def downgrade() -> None:
    """Forward-only — see NFR22 + ADR-005."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
