"""
Add model metadata fields for summaries and chat messages.

This migration adds:
- recordings.summary_model
- messages.model
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "003"  # lgtm [py/unused-global-variable]
down_revision: Union[str, None] = "002"  # lgtm [py/unused-global-variable]
branch_labels: Union[str, Sequence[str], None] = (
    None  # lgtm [py/unused-global-variable]
)
depends_on: Union[str, Sequence[str], None] = None  # lgtm [py/unused-global-variable]


def upgrade() -> None:
    """Add summary_model and message model columns."""
    conn = op.get_bind()

    existing = conn.execute(text("PRAGMA table_info(recordings)")).fetchall()
    if not any(row[1] == "summary_model" for row in existing):
        conn.execute(text("ALTER TABLE recordings ADD COLUMN summary_model TEXT"))

    existing = conn.execute(text("PRAGMA table_info(messages)")).fetchall()
    if not any(row[1] == "model" for row in existing):
        conn.execute(text("ALTER TABLE messages ADD COLUMN model TEXT"))

    conn.commit()


def downgrade() -> None:
    """Remove summary_model and message model columns (table rebuild)."""
    conn = op.get_bind()

    conn.execute(
        text("""
        CREATE TABLE recordings_backup AS
        SELECT id, filename, filepath, title, duration_seconds, recorded_at,
               imported_at, word_count, has_diarization, summary
        FROM recordings
        """)
    )
    conn.execute(text("DROP TABLE recordings"))
    conn.execute(
        text("""
        CREATE TABLE recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL UNIQUE,
            title TEXT,
            duration_seconds REAL NOT NULL,
            recorded_at TIMESTAMP NOT NULL,
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            word_count INTEGER DEFAULT 0,
            has_diarization INTEGER DEFAULT 0,
            summary TEXT
        )
        """)
    )
    conn.execute(
        text("""
        INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at,
                                imported_at, word_count, has_diarization, summary)
        SELECT id, filename, filepath, title, duration_seconds, recorded_at,
               imported_at, word_count, has_diarization, summary
        FROM recordings_backup
        """)
    )
    conn.execute(text("DROP TABLE recordings_backup"))

    conn.execute(
        text("""
        CREATE TABLE messages_backup AS
        SELECT id, conversation_id, role, content, created_at, tokens_used
        FROM messages
        """)
    )
    conn.execute(text("DROP TABLE messages"))
    conn.execute(
        text("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_used INTEGER,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
        """)
    )
    conn.execute(
        text("""
        INSERT INTO messages (id, conversation_id, role, content, created_at, tokens_used)
        SELECT id, conversation_id, role, content, created_at, tokens_used
        FROM messages_backup
        """)
    )
    conn.execute(text("DROP TABLE messages_backup"))
    conn.commit()
