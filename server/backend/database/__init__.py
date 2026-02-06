"""
Database layer for TranscriptionSuite.

Provides SQLite + FTS5 database for Audio Notebook recordings.
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    from server.database import database

    return getattr(database, name)


__all__ = [
    # Core
    "init_db",
    "get_db_session",
    "get_connection",
    "Recording",
    "set_data_directory",
    "get_data_dir",
    "get_db_path",
    "get_audio_dir",
    # Recording CRUD
    "insert_recording",
    "get_recording",
    "get_all_recordings",
    "get_recordings_by_date_range",
    "get_recordings_for_month",
    "get_recordings_for_hour",
    "delete_recording",
    "update_recording_summary",
    "update_recording_date",
    "get_recording_summary",
    "get_transcription",
    # Segments and Words
    "insert_segment",
    "insert_word",
    "insert_words_batch",
    "update_recording_word_count",
    "get_segments",
    "get_words",
    # Search
    "search_words",
    "search_words_enhanced",
    "search_recordings",
    # Conversations
    "create_conversation",  # lgtm [py/undefined-export]
    "get_conversation",  # lgtm [py/undefined-export]
    "get_conversations",  # lgtm [py/undefined-export]
    "update_conversation_title",  # lgtm [py/undefined-export]
    "update_conversation_response_id",  # lgtm [py/undefined-export]
    "get_conversation_with_messages",
    "delete_conversation",
    "add_message",
    "get_messages",
    "delete_message",
    # Longform recording storage
    "ensure_audio_dir",
    "convert_audio_to_mp3",
    "save_longform_to_database",
    "save_longform_recording",
    "get_word_timestamps_from_audio",
]
