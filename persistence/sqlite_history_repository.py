from datetime import datetime, timezone
from typing import List, Optional

from domain.track import Track
from infrastructure.database import Database
from persistence.history_repository import PlayHistoryRepository


class SqlitePlayHistoryRepository(PlayHistoryRepository):
    """SQLite implementation of the PlayHistoryRepository."""
    def __init__(self, database: Database):
        self.db = database

    def _connect(self):
        return self.db.connect()

    # --------------------------------
    # General Play Logging
    # --------------------------------

    def log_play(self, track: Track) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO play_history (track_id, played_at) VALUES (?, ?)",
                (track.id, datetime.now(timezone.utc).isoformat()),
            )

    def get_last_played_artist(self) -> Optional[str]:
        with self._connect() as connection:
            cursor = connection.execute("""
                SELECT t.artist
                FROM play_history p
                JOIN tracks t ON p.track_id = t.id
                ORDER BY p.played_at DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            return row[0] if row else None

    # --------------------------------
    # Cycle Logic
    # --------------------------------

    def mark_played_in_cycle(self, track_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO cycle_state (track_id) VALUES (?)",
                (track_id,),
            )

    def reset_cycle(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cycle_state")

    def get_unplayed_tracks(self, folders: List[str]) -> List[Track]:
        placeholders = ",".join("?" for _ in folders)

        query = f"""
            SELECT id, path, artist, folder
            FROM tracks
            WHERE folder IN ({placeholders})
            AND id NOT IN (SELECT track_id FROM cycle_state)
        """

        with self._connect() as connection:
            cursor = connection.execute(query, folders)
            rows = cursor.fetchall()

        return [Track(*row) for row in rows]

    # --------------------------------
    # Daily Spread
    # --------------------------------

    def log_daily_play(self, track: Track) -> None:
        today = self.today().date().isoformat()

        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO daily_state (track_id, date) VALUES (?, ?)",
                (track.id, today),
            )

    def reset_daily(self) -> None:
        today = self.today().date().isoformat()

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM daily_state WHERE date = ?",
                (today,),
            )

    # --------------------------------
    # Timeslot Spread
    # --------------------------------

    def log_timeslot_play(self, track: Track, slot: str) -> None:
        today = self.today().date().isoformat()

        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO timeslot_state (track_id, slot, date) VALUES (?, ?, ?)",
                (track.id, slot, today),
            )

    def reset_timeslot(self, slot: str) -> None:
        today = self.today().date().isoformat()

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM timeslot_state WHERE slot = ? AND date = ?",
                (slot, today),
            )

    # --------------------------------
    # Historical Period Analysis
    # --------------------------------

    def get_last_n_periods(self, period_type: str, period_name: str, n: int) -> list[int]:
        if period_type == "timeslot":
            query = """
                SELECT COUNT(*)
                FROM timeslot_state
                WHERE slot = ?
                GROUP BY date
                ORDER BY date DESC
                LIMIT ?
            """
        elif period_type == "daily":
            query = """
                SELECT COUNT(*)
                FROM daily_state
                GROUP BY date
                ORDER BY date DESC
                LIMIT ?
            """
        else:
            return []

        with self._connect() as connection:
            params = (period_name, n) if period_type == "timeslot" else (n,)
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()

        return [row[0] for row in rows]

    # --------------------------------

    def today(self) -> datetime:
        return datetime.today()
    
