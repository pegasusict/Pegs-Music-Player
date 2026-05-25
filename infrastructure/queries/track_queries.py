from typing import Iterable

from ..database import Database

TRACK_SELECT_COLUMNS = """
    id, path, artist, title, folder, duration_seconds,
    replaygain_track_gain_db, replaygain_track_peak
"""


def add_track(
    database: Database,
    path: str,
    artist: str,
    title: str,
    folder: str,
    duration_seconds: int,
    replaygain_track_gain_db: float | None,
    replaygain_track_peak: float | None,
) -> tuple[int, bool]:
    """Adds a track to the database and returns its ID."""
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO tracks (
                path, artist, title, folder, duration_seconds,
                replaygain_track_gain_db, replaygain_track_peak
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path,
                artist,
                title,
                folder,
                duration_seconds,
                replaygain_track_gain_db,
                replaygain_track_peak,
            ),
        )
        was_inserted = cursor.rowcount > 0 # If rowcount is 1, it was inserted. If 0, it was ignored.
        row = connection.execute( # Retrieve the ID, whether inserted or ignored
            "SELECT id FROM tracks WHERE path = ?",
            (path,),
        ).fetchone()

    if not row:
        raise RuntimeError(f"Failed to register track: {path}")

    return row[0], was_inserted


def update_track_duration(database: Database, track_id: int, duration_seconds: int) -> None:
    """Updates the duration_seconds for a given track ID."""
    with database.connect() as connection:
        connection.execute(
            "UPDATE tracks SET duration_seconds = ? WHERE id = ?",
            (duration_seconds, track_id),
        )


def update_track_replaygain(
    database: Database,
    track_id: int,
    replaygain_track_gain_db: float | None,
    replaygain_track_peak: float | None,
) -> None:
    """Updates cached ReplayGain track data for a given track ID."""
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE tracks
            SET replaygain_track_gain_db = ?,
                replaygain_track_peak = ?
            WHERE id = ?
            """,
            (replaygain_track_gain_db, replaygain_track_peak, track_id),
        )


def update_track_metadata(
    database: Database,
    track_id: int,
    artist: str,
    title: str,
    duration_seconds: int,
    replaygain_track_gain_db: float | None,
    replaygain_track_peak: float | None,
) -> None:
    """Updates cached file metadata for a given track ID."""
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE tracks
            SET artist = ?,
                title = ?,
                duration_seconds = ?,
                replaygain_track_gain_db = ?,
                replaygain_track_peak = ?
            WHERE id = ?
            """,
            (
                artist,
                title,
                duration_seconds,
                replaygain_track_gain_db,
                replaygain_track_peak,
                track_id,
            ),
        )


def get_track_durations_by_folder(database: Database, folder: str) -> list[int]:
    """Retrieves all track durations in a specific folder."""
    with database.connect() as connection:
        return [row[0] for row in connection.execute(
            """
            SELECT duration_seconds
            FROM tracks
            WHERE folder = ?
            """,
            (folder,),
        ).fetchall()]

def get_all_track_durations(database: Database) -> list[int]:
    """Retrieves all track durations from the database."""
    with database.connect() as connection:
        return [row[0] for row in connection.execute(
            """
            SELECT duration_seconds
            FROM tracks
            """
        ).fetchall()]


def get_replaygain_coverage(database: Database) -> tuple[int, int]:
    """Returns total tracks and tracks with complete ReplayGain track data."""
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_tracks,
                SUM(
                    CASE
                        WHEN replaygain_track_gain_db IS NOT NULL
                         AND replaygain_track_peak IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS replaygain_tracks
            FROM tracks
            """
        ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def get_tracks_by_folder(database: Database, folder: str) -> list[tuple[int, str, str, str, str, int, float | None, float | None]]:
    """Retrieves all tracks in a specific folder."""
    with database.connect() as connection:
        return connection.execute(
            f"""
            SELECT {TRACK_SELECT_COLUMNS}
            FROM tracks
            WHERE folder = ?
            """,
            (folder,),
        ).fetchall()

def get_tracks_by_folders(database: Database, folders: Iterable[str]) -> list[tuple[int, str, str, str, str, int, float | None, float | None]]:
    """Retrieves all tracks in multiple folders."""
    folders = list(folders)
    if not folders:
        return []

    placeholders = ",".join("?" for _ in folders)

    with database.connect() as connection:
        return connection.execute(
            f"""
            SELECT {TRACK_SELECT_COLUMNS}
            FROM tracks
            WHERE folder IN ({placeholders})
            """,
            folders,
        ).fetchall()

def get_track_by_id(database: Database, track_id: int) -> tuple[int, str, str, str, str, int, float | None, float | None]:
    """Retrieves a track by its ID."""
    with database.connect() as connection:
        return connection.execute(
            f"""
            SELECT {TRACK_SELECT_COLUMNS}
            FROM tracks
            WHERE id = ?
            """,
            (track_id,),
        ).fetchone()

def get_all_tracks(database: Database) -> list[tuple[int, str, str, str, str, int, float | None, float | None]]:
    """Retrieves all tracks from the database."""
    with database.connect() as connection:
        return connection.execute(f"""
            SELECT {TRACK_SELECT_COLUMNS}
            FROM tracks
            ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE, path COLLATE NOCASE
        """).fetchall()

def delete_track(database: Database, track_id: int) -> None:
    """Deletes a track from the database and all related state."""
    with database.connect() as connection:
        connection.execute("DELETE FROM queue_state WHERE track_id = ?", (track_id,))
        connection.execute("DELETE FROM playback_state WHERE track_id = ?", (track_id,))
        connection.execute("DELETE FROM cycle_state WHERE track_id = ?", (track_id,))
        connection.execute("DELETE FROM daily_state WHERE track_id = ?", (track_id,))
        connection.execute("DELETE FROM timeslot_state WHERE track_id = ?", (track_id,))
        connection.execute("DELETE FROM play_history WHERE track_id = ?", (track_id,)) # type: ignore
        connection.execute("DELETE FROM tracks WHERE id = ?", (track_id,))

def get_unplayed_cycle_tracks(database: Database, folder: str) -> list[tuple[int, str, str, str, str, int, float | None, float | None]]:
    """Retrieves tracks in a folder that haven't been played in the current cycle."""
    with database.connect() as connection:
        return connection.execute(
            f"""
            SELECT
                t.id, t.path, t.artist, t.title, t.folder, t.duration_seconds,
                t.replaygain_track_gain_db, t.replaygain_track_peak
            FROM tracks t
            LEFT JOIN cycle_state c ON t.id = c.track_id AND c.folder = ?
            WHERE t.folder = ? AND c.track_id IS NULL
            """,
            (folder, folder),
        ).fetchall()

def get_recently_played_tracks(database: Database, limit: int = 50) -> list[tuple[int, str, str, str, str, int, float | None, float | None]]:
    """
    Retrieves a list of recently played tracks, ordered by played_at descending.
    """
    with database.connect() as connection:
        return connection.execute(
            f"""
            SELECT
                t.id, t.path, t.artist, t.title, t.folder, t.duration_seconds,
                t.replaygain_track_gain_db, t.replaygain_track_peak
            FROM play_history ph
            JOIN tracks t ON ph.track_id = t.id
            ORDER BY ph.played_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
