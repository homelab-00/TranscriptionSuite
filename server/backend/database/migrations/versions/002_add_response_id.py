"""
Add response_id field to conversations for LM Studio stateful chat support.

This migration adds the response_id column to track LM Studio v1 API chat sessions.
"""

from sqlalchemy import text


def upgrade(conn):
    """Add response_id column to conversations table."""
    conn.execute(
        text("""
        ALTER TABLE conversations 
        ADD COLUMN response_id TEXT DEFAULT NULL
        """)
    )
    conn.commit()


def downgrade(conn):
    """Remove response_id column from conversations table."""
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
