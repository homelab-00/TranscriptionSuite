"""
Add response_id field to conversations for LM Studio stateful chat support.

This migration adds the response_id column to track LM Studio v1 API chat sessions.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _revision_metadata() -> tuple[
    str,
    Union[str, None],
    Union[str, Sequence[str], None],
    Union[str, Sequence[str], None],
]:
    """Reference Alembic metadata globals for static analyzers."""
    return revision, down_revision, branch_labels, depends_on


def upgrade() -> None:
    """Add response_id column to conversations table."""
    _revision_metadata()
    conn = op.get_bind()
    # Skip if column already exists (idempotent upgrade)
    existing = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
    if any(row[1] == "response_id" for row in existing):
        return
    conn.execute(
        text("""
        ALTER TABLE conversations 
        ADD COLUMN response_id TEXT DEFAULT NULL
        """)
    )
    conn.commit()


def downgrade() -> None:
    """Remove response_id column from conversations table."""
    conn = op.get_bind()
    # SQLite doesn't support DROP COLUMN directly, need to recreate table
    conn.execute(
        text("""
        CREATE TABLE conversations_backup AS 
        SELECT id, recording_id, title, created_at, updated_at 
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
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
        )
        """)
    )
    conn.execute(
        text("""
        INSERT INTO conversations (id, recording_id, title, created_at, updated_at)
        SELECT id, recording_id, title, created_at, updated_at 
        FROM conversations_backup
        """)
    )
    conn.execute(text("DROP TABLE conversations_backup"))
    conn.commit()
