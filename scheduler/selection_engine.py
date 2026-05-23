from datetime import date
from typing import Optional

from domain.track import Track
from infrastructure.spread_state_repository import SpreadStateRepository
from repository.music_repository import MusicRepository
from app_queue.queue_manager import QueueManager
from scheduler.timeslot_scheduler import TimeslotScheduler
from scheduler.spread_controller import SpreadController
from scheduler.period_target_calculator import PeriodTargetCalculator

import logging
logger = logging.getLogger(__name__)

class SelectionEngine:
    def __init__(self, 
                 music_repo: MusicRepository, 
                 spread_repo: SpreadStateRepository, 
                 queue: QueueManager, 
                 scheduler: TimeslotScheduler, 
                 daily_spread: SpreadController, 
                 slot_spread: SpreadController, 
                 calculator: PeriodTargetCalculator
            ):
        self.music_repo = music_repo
        self.spread_repo = spread_repo
        self.queue = queue
        self.scheduler = scheduler
        self.daily_spread = daily_spread
        self.slot_spread = slot_spread
        self.calculator = calculator

        self.current_day: Optional[str] = None
        self.current_slot_name: Optional[str] = None
        self.last_artist: Optional[str] = None
        self.selected_track: Optional[Track] = None

        self._shuffle_enabled: bool = False
    # ----------------------------

    def select_next(self) -> Optional[Track]:
        """Main selection logic for determining the next track to play."""
        self._refresh_periods()
        self.selected_track = None # Reset for current selection cycle

        if not self.queue.is_empty():
            self.selected_track = self.queue.get_next()
            if not self.selected_track:
                raise RuntimeError("Queue indicated non-empty but returned no track.")
        else:
            slot = self.scheduler.current_slot

            # slot specials
            if slot:
                total_slot_special = self.music_repo.count_slot_special(slot)

                if total_slot_special > 0 and self.slot_spread.should_trigger():
                    self.selected_track = self.music_repo.get_slot_special(slot, self.last_artist)

                    if self.selected_track:
                        self.slot_spread.notify_played()

            # daily specials
            if not self.selected_track: # Only try daily if slot special wasn't found
                total_daily_special = self.music_repo.count_daily_special()

                if total_daily_special > 0 and self.daily_spread.should_trigger():
                    self.selected_track = self.music_repo.get_daily_special(self.last_artist)

                    if self.selected_track:
                        self.daily_spread.notify_played()

            # regular
            if not self.selected_track: # Only try regular if no specials were found
                folders = slot.folders if slot else []
                self.selected_track = self.music_repo.get_regular(folders, self.last_artist, shuffle=self._shuffle_enabled)
                if not self.selected_track:
                    logger.info("No tracks available for current slot/criteria. Silently awaiting next selection opportunity.")
                    # Silently await next slot by returning None instead of crashing
                    return None

        if self.selected_track:
            self._update_last_artist(self.selected_track)

        return self.selected_track

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

    def _update_last_artist(self, track: Track) -> None:
        """Updates state after selecting a track."""
        if track:
            self.last_artist = track.artist

    def set_shuffle_enabled(self, enabled: bool) -> None:
        """Enables or disables shuffle mode for regular track selection."""
        self._shuffle_enabled = enabled
        logger.info(f"Shuffle mode {'enabled' if enabled else 'disabled'}")
