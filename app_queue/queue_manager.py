from collections import deque
import threading
from datetime import datetime, timedelta

from domain.track import Track
from infrastructure.database import Database
from repository.music_repository import MusicRepository
from scheduler.selection_engine import SelectionEngine
import config


class QueueManager:
    """Manages the manual and auto queues for tracks."""
    _manual_queue: deque[Track]
    _auto_queue: deque[Track]

    def __init__(self, selection_engine: SelectionEngine) -> None:
        self._lock = threading.Lock()
        self._manual_queue = deque()
        self._auto_queue = deque()
        self.selection_engine = selection_engine
        self._autoqueue_target_size = config.AUTOQUEUE_PREPOPULATE_COUNT

    # -------------------------------------------------------------
    # Enqueue
    # -------------------------------------------------------------

    def enqueue_manual(self, track: Track) -> None:
        """Adds a track to the manual queue."""
        with self._lock:
            self._manual_queue.append(track)

    def enqueue_manual_next(self, track: Track) -> None:
        """Adds a track to the front of the manual queue."""
        with self._lock:
            self._manual_queue.appendleft(track)

    def enqueue_auto(self, track: Track) -> None:
        """Adds a track to the auto queue."""
        with self._lock:
            self._auto_queue.append(track)

    # -------------------------------------------------------------
    # State
    # -------------------------------------------------------------

    def is_empty(self) -> bool:
        """Returns True if both queues are empty."""
        with self._lock:
            return not self._manual_queue and not self._auto_queue

    def has_manual(self) -> bool:
        """Returns True if there are tracks in the manual queue."""
        with self._lock:
            return bool(self._manual_queue)

    # -------------------------------------------------------------
    # Dequeue
    # -------------------------------------------------------------

    def get_next(self) -> Track | None:
        """Returns the next track to play, prioritizing the manual queue."""
        with self._lock:
            if self._manual_queue:
                track = self._manual_queue.popleft()
                self.selection_engine.update_last_artist(track)
                return track

            # Always try to repopulate if low, before getting a track.
            # This ensures we always try to have enough tracks if possible.
            if len(self._auto_queue) < self._autoqueue_target_size:
                self._repopulate_autoqueue()

            if self._auto_queue:
                track = self._auto_queue.popleft()
                # After popping a track from autoqueue, immediately try to repopulate
                # to maintain the target size for the next call.
                self._repopulate_autoqueue()
                return track

            return None

    # -------------------------------------------------------------
    # Autoqueue Management
    # -------------------------------------------------------------

    def _repopulate_autoqueue(self) -> None:
        """Fills the autoqueue up to the target size by selecting tracks for future slots."""
        tracks_to_fetch = self._autoqueue_target_size - len(self._auto_queue)
        if tracks_to_fetch <= 0:
            return

        # Calculate predicted start time based on existing auto-queue
        prediction_start = datetime.now()
        for queued_track in self._auto_queue:
            duration = queued_track.duration_seconds if queued_track.duration_seconds > 0 else config.AVERAGE_TRACK_DURATION_SECONDS
            prediction_start += timedelta(seconds=duration)

        new_tracks = self.selection_engine.select_tracks_for_future_slots(tracks_to_fetch, prediction_start)
        
        for track in new_tracks:
            self._auto_queue.append(track)

    # -------------------------------------------------------------

    def clear_manual(self) -> None:
        """Clears the manual queue."""
        with self._lock:
            self._manual_queue.clear()

    def clear_auto(self) -> None:
        """Clears the auto queue."""
        with self._lock:
            self._auto_queue.clear()

    def remove_manual_at(self, positions: list[int]) -> None:
        """Removes manual queue entries at the given positions."""
        with self._lock:
            positions = set(positions)
            self._manual_queue = deque(
                track for index, track in enumerate(self._manual_queue)
                if index not in positions
            )

    def remove_auto_at(self, positions: list[int]) -> None:
        """Removes auto queue entries at the given positions."""
        with self._lock:
            positions = set(positions)
            self._auto_queue = deque(
                track for index, track in enumerate(self._auto_queue)
                if index not in positions
            )

    def move_manual_up(self, positions: list[int]) -> list[int]:
        """Moves selected manual queue entries up one position."""
        with self._lock:
            queue = list(self._manual_queue)
            selected = set(positions)

            for index in sorted(selected):
                if index <= 0 or index - 1 in selected or index >= len(queue):
                    continue

                queue[index - 1], queue[index] = queue[index], queue[index - 1]
                selected.remove(index)
                selected.add(index - 1)

            self._manual_queue = deque(queue)
            return sorted(selected)

    def move_manual_down(self, positions: list[int]) -> list[int]:
        """Moves selected manual queue entries down one position."""
        with self._lock:
            queue = list(self._manual_queue)
            selected = set(positions)

            for index in sorted(selected, reverse=True):
                if index < 0 or index >= len(queue) - 1 or index + 1 in selected:
                    continue

                queue[index + 1], queue[index] = queue[index], queue[index + 1]
                selected.remove(index)
                selected.add(index + 1)

            self._manual_queue = deque(queue)
            return sorted(selected)

    def move_manual_to_top(self, positions: list[int]) -> list[int]:
        """Moves selected manual queue entries to the top, preserving order."""
        with self._lock:
            queue = list(self._manual_queue)
            selected = set(positions)
            moved = [track for index, track in enumerate(queue) if index in selected]
            remaining = [track for index, track in enumerate(queue) if index not in selected]
            self._manual_queue = deque(moved + remaining)
            return list(range(len(moved)))

    def move_manual_to_bottom(self, positions: list[int]) -> list[int]:
        """Moves selected manual queue entries to the bottom, preserving order."""
        with self._lock:
            queue = list(self._manual_queue)
            selected = set(positions)
            moved = [track for index, track in enumerate(queue) if index in selected]
            remaining = [track for index, track in enumerate(queue) if index not in selected]
            self._manual_queue = deque(remaining + moved)
            start = len(remaining)
            return list(range(start, start + len(moved)))

    def prune_unavailable(self, music_repo: MusicRepository) -> None:
        """Drops queued tracks that no longer exist in the library or on disk."""
        with self._lock:
            self._manual_queue = deque(
                track for track in self._manual_queue
                if music_repo.get_by_id(track.id) and track.path.exists()
            )
            self._auto_queue = deque(
                track for track in self._auto_queue
                if music_repo.get_by_id(track.id) and track.path.exists()
            )

    def snapshot(self) -> dict[str, list[Track]]:
        """
        Returns a UI-safe snapshot of queue state.
        """
        with self._lock:
            return {
                "manual": list(self._manual_queue),
                "auto": list(self._auto_queue),
            }

    def persist(self, db: Database) -> None:
        """Saves the current queue state to the database."""
        with self._lock:
            with db.connect() as connection:
                connection.execute("DELETE FROM queue_state")

                position = 0
                for track in self._manual_queue:
                    connection.execute(
                        "INSERT INTO queue_state VALUES (?, ?, ?)",
                        (position, track.id, "manual")
                    )
                    position += 1

                for track in self._auto_queue:
                    connection.execute(
                        "INSERT INTO queue_state VALUES (?, ?, ?)",
                        (position, track.id, "auto")
                    )
                    position += 1

    def restore(self, db: Database, music_repo: MusicRepository) -> None:
        """Restores queue state from the database."""
        with self._lock:
            self._manual_queue.clear()
            self._auto_queue.clear()

            with db.connect() as con:
                rows = con.execute(
                    "SELECT track_id, type FROM queue_state ORDER BY position"
                ).fetchall()

            for track_id, qtype in rows:
                track = music_repo.get_by_id(track_id)
                if track:
                    if qtype == "manual":
                        self._manual_queue.append(track)
                    else:
                        self._auto_queue.append(track)

    def initial_populate_autoqueue(self) -> None:
        """Called once at startup to fill the autoqueue."""
        with self._lock:
            self._repopulate_autoqueue()
