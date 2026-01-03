"""
Async SQLite backup system for TranscriptionSuite.

Provides:
- Non-blocking backup on server startup
- Age-based backup triggering
- Rotation of old backups (configurable max count)

The backup uses SQLite's built-in backup() API which is safe for use
with WAL mode and concurrent connections.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_BACKUP_MAX_AGE_HOURS = 1
DEFAULT_MAX_BACKUPS = 3


class DatabaseBackupManager:
    """Manages SQLite database backups with rotation."""

    def __init__(
        self,
        db_path: Path,
        backup_dir: Path,
        max_age_hours: int = DEFAULT_BACKUP_MAX_AGE_HOURS,
        max_backups: int = DEFAULT_MAX_BACKUPS,
    ):
        """
        Initialize the backup manager.

        Args:
            db_path: Path to the SQLite database file
            backup_dir: Directory to store backup files
            max_age_hours: Create backup if latest is older than this
            max_backups: Maximum number of backup files to keep
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.max_age_hours = max_age_hours
        self.max_backups = max_backups

    def _ensure_backup_dir(self) -> Path:
        """Ensure backup directory exists and return it."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        return self.backup_dir

    def get_latest_backup(self) -> Optional[Path]:
        """Get the most recent backup file, or None if no backups exist."""
        backup_dir = self._ensure_backup_dir()
        backups = sorted(
            backup_dir.glob("notebook_backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return backups[0] if backups else None

    def get_all_backups(self) -> list[Path]:
        """Get all backup files sorted by modification time (newest first)."""
        backup_dir = self._ensure_backup_dir()
        return sorted(
            backup_dir.glob("notebook_backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def needs_backup(self) -> bool:
        """Check if a new backup is needed based on age of latest backup."""
        latest = self.get_latest_backup()

        if latest is None:
            logger.info("No backup exists - backup needed")
            return True

        age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
        max_age = timedelta(hours=self.max_age_hours)

        if age > max_age:
            logger.info(
                f"Latest backup is {age} old (max: {max_age}) - backup needed"
            )
            return True

        logger.info(f"Latest backup is {age} old - no backup needed")
        return False

    def _rotate_backups(self) -> None:
        """Remove old backups, keeping only max_backups most recent."""
        backups = self.get_all_backups()

        for old_backup in backups[self.max_backups :]:
            logger.info(f"Removing old backup: {old_backup.name}")
            try:
                old_backup.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove old backup {old_backup}: {e}")

    def create_backup(self) -> Optional[Path]:
        """
        Create a backup using SQLite's backup API.

        This method is safe for use with WAL mode and concurrent connections.
        The backup API copies pages incrementally without locking the source.

        Returns:
            Path to the backup file, or None on failure
        """
        if not self.db_path.exists():
            logger.warning(f"Database does not exist at {self.db_path} - cannot backup")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self._ensure_backup_dir() / f"notebook_backup_{timestamp}.db"

        source_conn = None
        dest_conn = None

        try:
            logger.info(f"Starting backup of {self.db_path} to {backup_path}")

            # Open source database in read-only mode
            source_conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=30.0,
            )

            # Create destination database
            dest_conn = sqlite3.connect(backup_path, timeout=30.0)

            # Use SQLite's built-in backup API
            # pages=-1 means copy all pages
            # progress callback can be used for large databases
            source_conn.backup(dest_conn, pages=-1)

            logger.info(f"Backup completed successfully: {backup_path}")

            # Rotate old backups after successful backup
            self._rotate_backups()

            return backup_path

        except Exception as e:
            logger.error(f"Backup failed: {e}", exc_info=True)

            # Clean up partial backup file
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except Exception:
                    logger.debug(f"Failed to cleanup partial backup file: {backup_path}")

            return None

        finally:
            if source_conn:
                source_conn.close()
            if dest_conn:
                dest_conn.close()

    def verify_backup(self, backup_path: Path) -> bool:
        """
        Verify a backup file is valid by running integrity check.

        Args:
            backup_path: Path to the backup file to verify

        Returns:
            True if backup is valid, False otherwise
        """
        if not backup_path.exists():
            return False

        try:
            conn = sqlite3.connect(backup_path, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()

            is_valid = result and result[0] == "ok"
            if not is_valid:
                logger.warning(f"Backup integrity check failed: {result}")
            return is_valid

        except Exception as e:
            logger.error(f"Failed to verify backup {backup_path}: {e}")
            return False


async def run_backup_if_needed(
    db_path: Path,
    backup_dir: Path,
    max_age_hours: int = DEFAULT_BACKUP_MAX_AGE_HOURS,
    max_backups: int = DEFAULT_MAX_BACKUPS,
) -> Optional[Path]:
    """
    Run backup in background if needed (async, non-blocking).

    This function is designed to be called during server startup
    using asyncio.create_task() and will not block the main thread.

    Args:
        db_path: Path to the SQLite database file
        backup_dir: Directory to store backup files
        max_age_hours: Create backup if latest is older than this
        max_backups: Maximum number of backup files to keep

    Returns:
        Path to the backup file if created, None otherwise
    """
    manager = DatabaseBackupManager(
        db_path=db_path,
        backup_dir=backup_dir,
        max_age_hours=max_age_hours,
        max_backups=max_backups,
    )

    if not manager.needs_backup():
        return None

    # Run backup in thread pool to avoid blocking async event loop
    loop = asyncio.get_event_loop()
    backup_path = await loop.run_in_executor(None, manager.create_backup)

    if backup_path:
        # Optionally verify the backup
        is_valid = await loop.run_in_executor(
            None, manager.verify_backup, backup_path
        )
        if not is_valid:
            logger.warning(f"Backup verification failed for {backup_path}")

    return backup_path
