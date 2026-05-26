import config
from datetime import date, datetime, timedelta
from typing import Optional, List

import threading
from domain.track import Track
from infrastructure.spread_state_repository import SpreadStateRepository
from repository.music_repository import MusicRepository
from scheduler.timeslot_scheduler import TimeslotScheduler
from scheduler.spread_controller import SpreadController
from scheduler.period_target_calculator import PeriodTargetCalculator

import logging
logger = logging.getLogger(__name__)

class SelectionEngine:
    def __init__(self, 
                 music_repo: MusicRepository, 
                 spread_repo: SpreadStateRepository, 
                 scheduler: TimeslotScheduler, 
                 daily_spread: SpreadController, 
                 slot_spread: SpreadController, 
                 calculator: PeriodTargetCalculator
            ):
        self.music_repo = music_repo
        self.spread_repo = spread_repo
        self.scheduler = scheduler
        self.daily_spread = daily_spread
        self.slot_spread = slot_spread
        self.calculator = calculator

        self.current_day: Optional[str] = None
        self.current_slot_name: Optional[str] = None
        self.last_artist: Optional[str] = None

        self._shuffle_enabled: bool = False
        self._lock = threading.Lock()
    # ----------------------------

    def select_tracks_for_future_slots(self, count: int, start_time: datetime) -> List[Track]:
        """
        Selects multiple tracks for the future, calculating the active slot 
        for each track's predicted start time.
        """
        with self._lock:
            self._refresh_periods()
            future_tracks = []
            current_prediction_time = start_time
            # Use a local variable to maintain artist separation during the look-ahead
            lookahead_last_artist = self.last_artist

            for _ in range(count):
                slot = self.scheduler.detect_slot(at_time=current_prediction_time)
                track = None

                if slot:
                    # 1. Try Slot Specials
                    if self.music_repo.count_slot_special(slot) > 0 and self.slot_spread.should_trigger():
                        track = self.music_repo.get_slot_special(slot, lookahead_last_artist)
                        if track:
                            self.slot_spread.notify_played()

                    # 2. Try Daily Specials
                    if not track and self.music_repo.count_daily_special() > 0 and self.daily_spread.should_trigger():
                        track = self.music_repo.get_daily_special(lookahead_last_artist)
                        if track:
                            self.daily_spread.notify_played()

                    # 3. Regular Track
                    if not track:
                        folders = slot.folders
                        track = self.music_repo.get_regular(folders, lookahead_last_artist, shuffle=self._shuffle_enabled)

                if track:
                    future_tracks.append(track)
                    lookahead_last_artist = track.artist
                    # Advance the clock for the next prediction
                    duration = track.duration_seconds if track.duration_seconds > 0 else config.AVERAGE_TRACK_DURATION_SECONDS
                    current_prediction_time += timedelta(seconds=duration)
                else:
                    # If we can't find a track, stop filling to avoid infinite loops or bad data
                    break
            
            if future_tracks:
                self.last_artist = lookahead_last_artist
            return future_tracks

    # ----------------------------

    def _refresh_periods(self) -> None:
        """Checks for day/slot changes and resets spread controllers accordingly."""
        today = date.today().isoformat()

        # daily reset
        if self.current_day != today:
            self.current_day = today
            target = self.calculator.compute_daily_target()
            self.daily_spread.start_period(today, target)

        # slot reset
        slot = self.scheduler.current_slot

        slot_name = slot.name if slot else None

        if self.current_slot_name != slot_name:
            self.current_slot_name = slot_name

            if slot:
                period_id = f"{today}_{slot.name}"
                target = self.calculator.compute_slot_target(slot)

                self.slot_spread.start_period(period_id, target)

    # ----------------------------

    def update_last_artist(self, track: Track) -> None:
        """Updates state after selecting a track."""
        with self._lock:
            if track:
                self.last_artist = track.artist

    def set_shuffle_enabled(self, enabled: bool) -> None:
        """Enables or disables shuffle mode for regular track selection."""
        with self._lock:
            self._shuffle_enabled = enabled
            logger.info(f"Shuffle mode {'enabled' if enabled else 'disabled'}")

    def get_shuffle_enabled(self) -> bool:
        """Returns the current shuffle mode enabled state."""
        with self._lock:
            return self._shuffle_enabled
