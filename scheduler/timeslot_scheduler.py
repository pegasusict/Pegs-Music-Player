from datetime import datetime
from typing import Optional

from domain.timeslot import Timeslot


class TimeslotScheduler:
    """
    Responsible for determining the current timeslot based on the time of day.
    It checks the provided timeslots to see which one (if any) matches the current time.
    If multiple timeslots overlap, the one that appears last in the list takes precedence.
    """
    def __init__(self, timeslots: list[Timeslot]):
        self._timeslots = timeslots
        # self._current_slot: Optional[Timeslot] = self.detect_slot() # Removed as it's unused

    def detect_slot(self) -> Optional[Timeslot]:
        """Determines which timeslot (if any) currently applies based on the current time."""
        now = datetime.now().astimezone().time()

        for slot in self._timeslots[-1::-1]:  # check in reverse order to prioritize later slots
            if slot.contains(now):
                return slot

        return None

    @property
    def current_slot(self) -> Optional[Timeslot]:
        """Returns the currently active timeslot, or None if no slot is active."""
        return self.detect_slot()

    @property
    def timeslots(self) -> list[Timeslot]:
        """Returns the list of configured timeslots."""
        return self._timeslots
