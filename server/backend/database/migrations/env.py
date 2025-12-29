"""
Alembic migration environment for TranscriptionSuite.

This file configures Alembic to work with SQLite in a way that supports:
- Batch operations (required for SQLite ALTER TABLE limitations)
- Safe concurrent access via WAL mode
- Proper foreign key handling during migrations
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool, text


# Alembic Config object
config = context.config

# Configure logging from alembic.ini if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_database_url() -> str:
    """Get the database URL from environment or default path."""
    # Check for DATA_DIR environment variable (Docker)
    data_dir = os.environ.get("DATA_DIR", "/data")
    db_path = Path(data_dir) / "database" / "notebook.db"

    # For local development, fall back to project-relative path
    if not db_path.parent.exists():
        project_root = Path(__file__).parent.parent.parent.parent.parent
        db_path = project_root / "data" / "database" / "notebook.db"

    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This generates SQL scripts without requiring a database connection.
    Useful for reviewing migration SQL before applying.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # CRITICAL: render_as_batch=True is required for SQLite
        # SQLite doesn't support most ALTER TABLE operations, so Alembic
        # uses batch mode to recreate tables with changes applied
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    This creates a connection to the database and runs migrations
    within a transaction.
    """
    url = get_database_url()

    # Use NullPool for SQLite (single connection, no pooling needed)
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Temporarily disable foreign keys for migration safety
        # Some operations may temporarily violate FK constraints
        connection.execute(text("PRAGMA foreign_keys=OFF"))

        context.configure(
            connection=connection,
            target_metadata=None,
            # CRITICAL: render_as_batch=True for SQLite
            render_as_batch=True,
            # Compare server default values
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

        # Re-enable foreign keys after migration
        connection.execute(text("PRAGMA foreign_keys=ON"))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
