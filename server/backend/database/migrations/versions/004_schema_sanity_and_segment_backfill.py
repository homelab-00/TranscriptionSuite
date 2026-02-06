"""
Legacy schema compatibility fixes and segment text backfill.

This migration ensures older pre-Alembic databases are brought to the
current column set, then backfills empty segment text from word rows.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_column(conn, table: str, column: str, ddl: str) -> bool:
    """Add a column if it does not exist. Returns True if added."""
    existing = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    if any(row[1] == column for row in existing):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def upgrade() -> None:
    """Apply legacy column compatibility and backfill segment text."""
    conn = op.get_bind()

    title_added = _ensure_column(conn, "recordings", "title", "title TEXT")
    _ensure_column(conn, "recordings", "summary", "summary TEXT")
    _ensure_column(conn, "recordings", "summary_model", "summary_model TEXT")
    _ensure_column(conn, "messages", "model", "model TEXT")

    if title_added:
        conn.execute(text("UPDATE recordings SET title = filename WHERE title IS NULL"))

    conn.execute(
        text(
            """
            UPDATE segments
            SET text = (
                SELECT TRIM(GROUP_CONCAT(TRIM(word), ' '))
                FROM (
                    SELECT word
                    FROM words
                    WHERE words.segment_id = segments.id
                    ORDER BY start_time
                )
            )
            WHERE (text IS NULL OR text = '')
              AND EXISTS (SELECT 1 FROM words WHERE words.segment_id = segments.id)
            """
        )
    )

    conn.commit()


def downgrade() -> None:
    """
    No-op downgrade.

    This migration performs safe forward compatibility repairs and data backfill.
    Reversing it would risk destructive schema/data changes.
    """
    pass
