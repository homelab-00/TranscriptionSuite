"""
Database layer for TranscriptionSuite.

Provides SQLite + FTS5 database for Audio Notebook recordings.
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    from server.database import database

    return getattr(database, name)


__all__ = [
    "init_db",
    "get_db_session",
    "get_connection",
    "Recording",
    "set_data_directory",
    "get_data_dir",
    "get_audio_dir",
]
