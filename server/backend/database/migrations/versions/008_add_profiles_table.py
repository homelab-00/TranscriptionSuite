"""Add profiles table for the Audio Notebook QoL pack (Issue #104, Story 1.2).

Public-vs-private field separation:
  - public_fields_json holds non-sensitive settings (template, destination,
    toggles, model id, prompt template, format).
  - private_field_refs_json holds keychain-reference IDs only (e.g.
    'profile.123.webhook_token') — NEVER plaintext (FR11, R-EL22).

Forward-only per NFR22; downgrade() raises to make this explicit.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
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
    """Create profiles table + supporting index."""
    _revision_metadata()
    conn = op.get_bind()

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                schema_version TEXT NOT NULL,
                public_fields_json TEXT NOT NULL,
                private_field_refs_json TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )

    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name)"))


def downgrade() -> None:
    """Forward-only — see NFR22 + ADR-001."""
    _revision_metadata()
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if a roll-back is required."
    )
