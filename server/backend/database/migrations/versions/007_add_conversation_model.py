"""
Add per-conversation model override column.

This migration adds:
- conversations.model — optional model ID that overrides the global config for this conversation
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "006"
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
    """Add model column to conversations table."""
    _revision_metadata()
    conn = op.get_bind()

    existing = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
    if not any(row[1] == "model" for row in existing):
        conn.execute(text("ALTER TABLE conversations ADD COLUMN model TEXT DEFAULT NULL"))


def downgrade() -> None:
    """Remove model column from conversations (table rebuild for SQLite)."""
    conn = op.get_bind()

    conn.execute(
        text("""
        CREATE TABLE conversations_backup AS
        SELECT id, recording_id, title, created_at, updated_at, response_id
        FROM conversations
        """)
    )
    conn.execute(text("DROP TABLE conversations"))
    conn.execute(
        text("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_id TEXT,
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
        )
        """)
    )
    conn.execute(
        text("""
        INSERT INTO conversations (id, recording_id, title, created_at, updated_at, response_id)
        SELECT id, recording_id, title, created_at, updated_at, response_id
        FROM conversations_backup
        """)
    )
    conn.execute(text("DROP TABLE conversations_backup"))
