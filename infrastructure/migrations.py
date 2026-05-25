from collections.abc import Callable
from dataclasses import dataclass
import logging
import sqlite3

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Migration:
    """Represents a database schema migration."""
    revision: str
    description: str
    upgrade: Callable[[sqlite3.Connection], None]


def run_migrations(connection: sqlite3.Connection) -> None:
    """Apply pending SQLite schema migrations in revision order."""
    _ensure_migration_table(connection)
    applied = _applied_revisions(connection)

    for migration in MIGRATIONS:
        if migration.revision in applied:
            continue

        logger.info(
            "Applying database migration %s: %s",
            migration.revision,
            migration.description,
        )
        migration.upgrade(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (revision, description, applied_at)
            VALUES (?, ?, datetime('now'))
            """,
            (migration.revision, migration.description),
        )


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            revision TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _applied_revisions(connection: sqlite3.Connection) -> set[str]:
    """Fetch the set of applied migration revisions from the database."""
    rows = connection.execute("SELECT revision FROM schema_migrations").fetchall()
    return {row["revision"] for row in rows}


def _column_exists(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> bool:
    """Check if a column exists in a table."""
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add a column to a table if it does not already exist."""
    if not _column_exists(connection, table, column):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _initial_schema(connection: sqlite3.Connection) -> None:
    """Create the initial database schema for the music player."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            artist TEXT,
            title TEXT,
            folder TEXT NOT NULL,
            duration_seconds INTEGER DEFAULT 210
        );

        CREATE TABLE IF NOT EXISTS play_history (
            track_id INTEGER NOT NULL,
            played_at TEXT NOT NULL,
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS cycle_state (
            folder TEXT NOT NULL,
            track_id INTEGER NOT NULL,
            PRIMARY KEY(folder, track_id),
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS queue_state (
            position INTEGER PRIMARY KEY,
            track_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS playback_state (
            track_id INTEGER,
            position INTEGER,
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS daily_state (
            track_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            PRIMARY KEY(track_id, date),
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS timeslot_state (
            track_id INTEGER NOT NULL,
            slot TEXT NOT NULL,
            date TEXT NOT NULL,
            PRIMARY KEY(track_id, slot, date),
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS spread_state (
            category TEXT PRIMARY KEY,
            period_id TEXT,
            period_target INTEGER,
            played_count INTEGER,
            accumulator REAL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tracks_folder
            ON tracks(folder);

        CREATE INDEX IF NOT EXISTS idx_tracks_artist
            ON tracks(artist COLLATE NOCASE);

        CREATE INDEX IF NOT EXISTS idx_play_history_played_at
            ON play_history(played_at DESC);

        CREATE INDEX IF NOT EXISTS idx_play_history_track_id
            ON play_history(track_id);

        CREATE INDEX IF NOT EXISTS idx_cycle_state_folder_track
            ON cycle_state(folder, track_id);
        """
    )


def _add_replaygain_columns(connection: sqlite3.Connection) -> None:
    """Add cached per-track ReplayGain fields to the tracks table."""
    _add_column_if_missing(
        connection,
        "tracks",
        "replaygain_track_gain_db",
        "REAL",
    )
    _add_column_if_missing(
        connection,
        "tracks",
        "replaygain_track_peak",
        "REAL",
    )


MIGRATIONS = [
    Migration(
        revision="0001_initial_schema",
        description="Create initial music player tables and indexes",
        upgrade=_initial_schema,
    ),
    Migration(
        revision="0002_track_replaygain",
        description="Add cached per-track ReplayGain fields",
        upgrade=_add_replaygain_columns,
    ),
]
