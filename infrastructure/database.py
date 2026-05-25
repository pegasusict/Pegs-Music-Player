from datetime import datetime, timezone
import sqlite3
import threading
from typing import Optional

from infrastructure.migrations import run_migrations


class Database:
    """A thread-safe database connection manager for SQLite."""
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = None
        self._lock = threading.RLock()
        self._init_db()
        self._run_migrations()

    # --------------------------------------------------
    # Connection Management
    # --------------------------------------------------

    def _init_db(self) -> None:
        """
        Initializes the database file and applies performance-oriented PRAGMA settings.
        This is called once during application startup to ensure the database is ready for use.
        """
        con = sqlite3.connect(self.path, timeout=5.0)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("PRAGMA foreign_keys=ON;")
        finally:
            con.close()

    def connect(self) -> sqlite3.Connection:
        """
        Returns the thread-safe singleton connection to the database.
        """
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(
                    self.path,
                    timeout=10.0,
                    check_same_thread=False,
                )
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA synchronous=NORMAL;")
                self._conn.execute("PRAGMA foreign_keys=ON;")
            return self._conn

    def close(self) -> None:
        """
        Closes the singleton database connection.
        """
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # --------------------------------------------------
    # Schema Migrations
    # --------------------------------------------------

    def _run_migrations(self) -> None:
        """Runs database schema migrations to ensure the database is up-to-date."""
        with self.connect() as connection:
            run_migrations(connection)

    # --------------------------------------------------
    # Playback State
    # --------------------------------------------------

    def save_playback_state(self, track_id: int | None, position: int) -> None:
        """
        Saves the current playback state, including the track ID and position. 
        If track_id is None, it clears the playback state.
        """
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute("DELETE FROM playback_state")
                if track_id is not None:
                    connection.execute(
                        """
                        INSERT INTO playback_state (track_id, position)
                        VALUES (?, ?)
                        """,
                        (track_id, position),
                    )

    def load_playback_state(self):
        """Loads the current playback state, returning a tuple of (track_id, position) or None if no state is saved."""
        with self._lock:
            connection = self.connect()
            return connection.execute(
                "SELECT track_id, position FROM playback_state LIMIT 1"
            ).fetchone()

    # --------------------------------------------------
    # App State
    # --------------------------------------------------

    def save_app_state(self, key: str, value: str) -> None:
        """Saves a key-value pair in the app_state table, allowing for flexible storage of various application states."""
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def load_app_state(self, key: str) -> Optional[str]:
        """Loads a value from the app_state table based on the provided key, returning None if the key does not exist."""
        with self._lock:
            connection = self.connect()
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (key,),
            ).fetchone()
            return row[0] if row else None

    # --------------------------------------------------
    # Playback Tracking
    # --------------------------------------------------

    def mark_played(self, track_id: int) -> None:
        """Marks a track as played by inserting a record into the play_history table with the current timestamp."""
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT INTO play_history (track_id, played_at) VALUES (?, ?)",
                    (track_id, datetime.now(timezone.utc).isoformat()),
                )

    def get_last_played_artist(self) -> Optional[str]:
        """
        Retrieves the artist of the most recently played track by joining the play_history and tracks tables,
          returning None if no tracks have been played.
        """
        with self._lock:
            connection = self.connect()
            row = connection.execute("""
                SELECT t.artist
                FROM play_history p
                JOIN tracks t ON p.track_id = t.id
                ORDER BY p.played_at DESC
                LIMIT 1
            """).fetchone()
            return row[0] if row else None

    # --------------------------------------------------
    # Cycle Management
    # --------------------------------------------------

    def mark_cycle_played(self, folder: str, track_id: int) -> None:
        """Marks a track as played in the cycle for a specific folder by inserting a record into the cycle_state table."""
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO cycle_state (folder, track_id) VALUES (?, ?)",
                    (folder, track_id),
                )

    def reset_cycle(self, folder: str) -> None:
        """Resets the cycle for a specific folder by deleting all records from the cycle_state table."""
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "DELETE FROM cycle_state WHERE folder = ?",
                    (folder,),
                )

    def get_unplayed_cycle_tracks_excluding_artist(
        self,
        folder: str,
        exclude_artist: str | None,
    ) -> list[tuple]:
        """
        Retrieves a list of unplayed tracks for a specific folder, optionally excluding tracks by a specified artist,
          by performing a LEFT JOIN between the tracks and cycle_state tables.
        """
        with self._lock:
            connection = self.connect()
            query = """
                SELECT t.id, t.path, t.artist, t.duration_seconds
                FROM tracks t
                LEFT JOIN cycle_state c
                  ON t.id = c.track_id AND c.folder = ?
                WHERE t.folder = ?
                  AND c.track_id IS NULL
            """
            params = [folder, folder]

            if exclude_artist:
                query += " AND LOWER(t.artist) != LOWER(?)"
                params.append(exclude_artist)

            return connection.execute(query, params).fetchall()
