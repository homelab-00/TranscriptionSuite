"""
Add transcription_jobs table for durability (Wave 1).

Records every WebSocket/HTTP transcription job with status, result, and
delivery tracking so completed results survive WebSocket disconnections.
"""

from collections.abc import Sequence

from alembic import op  # type: ignore[reportMissingImports]
from sqlalchemy import text  # type: ignore[reportMissingImports]

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
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
    """Create transcription_jobs table and indexes."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS transcription_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'processing',
            source TEXT NOT NULL,
            client_name TEXT,
            language TEXT,
            task TEXT DEFAULT 'transcribe',
            translation_target TEXT,
            audio_path TEXT,
            result_text TEXT,
            result_json TEXT,
            result_language TEXT,
            duration_seconds REAL,
            error_message TEXT,
            delivered INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_transcription_jobs_status ON transcription_jobs(status)"
        )
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_transcription_jobs_client "
            "ON transcription_jobs(client_name, created_at)"
        )
    )


def downgrade() -> None:
    """Drop transcription_jobs table and indexes."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(text("DROP INDEX IF EXISTS idx_transcription_jobs_client"))
    conn.execute(text("DROP INDEX IF EXISTS idx_transcription_jobs_status"))
    conn.execute(text("DROP TABLE IF EXISTS transcription_jobs"))
