from persistence.history_repository import PlayHistoryRepository
import config
from repository.music_repository import MusicRepository # Import MusicRepository
from typing import Optional

from domain.timeslot import Timeslot # Import Timeslot for type hinting

class PeriodTargetCalculator:
    def __init__(self, repository: PlayHistoryRepository, music_repo: MusicRepository): # Add music_repo
        self._repo = repository
        self._music_repo = music_repo # Store music_repo
    # ----------------------------

    def compute_daily_target(self) -> int:
        history = self._repo.get_last_n_periods("daily", "daily", 7)

        if history:
            return self._weighted(history, alpha=0.4)

        return self._fallback_daily()

    def compute_slot_target(self, slot: Timeslot) -> int:
        history = self._repo.get_last_n_periods("timeslot", slot.name, 7)

        if history:
            return self._weighted(history, alpha=0.6)

        return self._fallback_slot(slot)

    # ----------------------------

    def _fallback_daily(self) -> int:
        ACTIVE_DAY_SECONDS = 24 * 60 * 60
        return self._duration_based_target(ACTIVE_DAY_SECONDS)

    def _fallback_slot(self, slot: Timeslot) -> int:
        effective = min(slot.duration_seconds(), 8 * 60 * 60) # assuming there are 3 slots per day.
        return self._duration_based_target(effective, folder_context=slot.each_iteration_folder)

    # ----------------------------

    def _duration_based_target(self, duration_seconds: int, folder_context: Optional[str] = None) -> int:
        if folder_context and folder_context != "NOT_IN_USE":
            avg_track_duration = self._music_repo.get_average_track_duration_for_folder(folder_context)
        else:
            avg_track_duration = float(config.AVERAGE_TRACK_DURATION_SECONDS)

        estimated_capacity = max(1, int(duration_seconds // avg_track_duration))
        return estimated_capacity
    
    # The _estimate_average_track_length method was removed as it was not performing
    # any calculation and simply returning a default, which is now handled by the config.
    
    # ----------------------------

    def _weighted(self, values: list[int], alpha: float) -> int:
        if not values: # Fallback if no history
            return 1 # Return a default count, not a duration

        avg: float = float(values[0])
        for value in values[1:]:
            avg = (alpha * float(value)) + ((1.0 - alpha) * avg)

        return max(1, round(avg))
