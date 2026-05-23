from dataclasses import dataclass
from datetime import datetime, time


@dataclass(slots=True)
class Timeslot:
    """Represents a timeslot during which certain music folders should be played."""
    name: str
    start: time
    end: time
    folders: list[str]
    each_iteration_folder: str = "NOT_IN_USE" # Optional folder for each iteration, defaulting to "NOT_IN_USE"

    def contains_now(self) -> bool:
        """Check if the current time falls within this timeslot."""
        return self.contains(datetime.now().time())

    def contains(self, now: time | None = None) -> bool:
        """Check if the given time falls within this timeslot."""
        now = datetime.now().time() if now is None else now

        if self.start < self.end:
            return self.start <= now < self.end

        # cross midnight
        return now >= self.start or now < self.end

    def duration_seconds(self) -> int:
        """Return this slot's duration, accounting for slots that cross midnight."""
        start_seconds = (self.start.hour * 3600) + (self.start.minute * 60) + self.start.second
        end_seconds = (self.end.hour * 3600) + (self.end.minute * 60) + self.end.second

        if end_seconds <= start_seconds:
            end_seconds += 24 * 3600

        return end_seconds - start_seconds
