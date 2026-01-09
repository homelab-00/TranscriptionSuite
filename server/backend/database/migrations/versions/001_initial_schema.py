"""Initial schema capture - existing database structure.

Revision ID: 001
Revises: None
Create Date: 2025-01-01

This migration captures the existing TranscriptionSuite database schema.
It uses IF NOT EXISTS clauses to be safe for existing databases.
Running this on an existing database will:
1. Stamp the database with version "001"
2. Skip table creation (tables already exist)
3. Create any missing indexes (no-op if they exist)
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial schema if tables don't exist."""
    conn = op.get_bind()

    # Main recordings table
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS recordings (
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

    # Segments table (for speaker turns or time-based segments)
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL,
            segment_index INTEGER NOT NULL,
            speaker TEXT,
            text TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
        )
    """)
    )

    # Words table with timing information
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL,
            segment_id INTEGER NOT NULL,
            word_index INTEGER NOT NULL,
            word TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            confidence REAL,
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
            FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE
        )
    """)
    )

    # FTS5 virtual table for full-text search
    conn.execute(
        text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
            word,
            content='words',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    )

    # FTS triggers for sync
    conn.execute(
        text("""
        CREATE TRIGGER IF NOT EXISTS words_ai AFTER INSERT ON words BEGIN
            INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
        END
    """)
    )

    conn.execute(
        text("""
        CREATE TRIGGER IF NOT EXISTS words_ad AFTER DELETE ON words BEGIN
            INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
        END
    """)
    )

    conn.execute(
        text("""
        CREATE TRIGGER IF NOT EXISTS words_au AFTER UPDATE ON words BEGIN
            INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
            INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
        END
    """)
    )

    # Conversations table - LLM chat sessions
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
        )
    """)
    )

    # Messages table - chat history
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS messages (
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

    # Indexes for common queries
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_recordings_date ON recordings(recorded_at)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_words_recording ON words(recording_id)")
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_words_time ON words(start_time)"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_conversations_recording ON conversations(recording_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)"
        )
    )


def downgrade() -> None:
    """Cannot downgrade initial schema - data loss would occur."""
    # Intentionally left empty - downgrading would destroy all data
    # If you need to reset, delete the database file instead
    pass
