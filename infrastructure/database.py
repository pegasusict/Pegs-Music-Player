import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional, Iterable

from infrastructure.migrations import run_migrations


class Database:
    def __init__(self, path: str):
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
        with self.connect() as connection:
            run_migrations(connection)

    # --------------------------------------------------
    # Playback State
    # --------------------------------------------------

    def save_playback_state(self, track_id: int | None, position: int) -> None:
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
        with self._lock:
            connection = self.connect()
            return connection.execute(
                "SELECT track_id, position FROM playback_state LIMIT 1"
            ).fetchone()

    # --------------------------------------------------
    # App State
    # --------------------------------------------------

    def save_app_state(self, key: str, value: str) -> None:
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def load_app_state(self, key: str):
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
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT INTO play_history (track_id, played_at) VALUES (?, ?)",
                    (track_id, datetime.now(timezone.utc).isoformat()),
                )

    def get_last_played_artist(self) -> Optional[str]:
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
        with self._lock:
            connection = self.connect()
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO cycle_state (folder, track_id) VALUES (?, ?)",
                    (folder, track_id),
                )

    def reset_cycle(self, folder: str) -> None:
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
    ):
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
