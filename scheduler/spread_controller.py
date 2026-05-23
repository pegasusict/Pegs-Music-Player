from typing import Optional

from infrastructure.spread_state_repository import SpreadStateRepository


class SpreadController:
    def __init__(
        self,
        category: str,
        state_repo: SpreadStateRepository,
    ):
        self.category = category
        self.repo = state_repo

        self.period_id: Optional[str] = None
        self.target: int = 0
        self.played: int = 0
        self.accumulator: float = 0.0

    # --------------------------------------------------

    def start_period(self, period_id: str, target: int) -> None:
        """Initializes or resets the spread state for a new period."""
        self.period_id = period_id
        self.target = max(1, target)

        saved = self.repo.load(self.category)

        if saved and saved.get("period_id") == period_id:
            self.target = max(1, saved.get("target", self.target))
            self.played = saved.get("played", 0)
            self.accumulator = float(saved.get("accumulator", 0.0))
        else:
            self._reset_state()
            self.repo.clear(self.category)

    # --------------------------------------------------

    def should_trigger(self) -> bool:
        """Determines whether the spread condition is met to trigger a special track."""
        if self.target == 0: # Avoid division by zero and unnecessary calculations
            return False

        if self.played >= self.target:
            return False

        self.accumulator += 1 / self.target

        if self.accumulator >= 1:
            self.accumulator -= 1
            return True

        return False

    # --------------------------------------------------

    def notify_played(self) -> None:
        """Updates the state after a track has been played that counts towards the spread."""
        self.played += 1
        self._persist()

    # --------------------------------------------------

    def _reset_state(self) -> None:
        """Resets the spread state to initial values."""
        self.played = 0
        self.accumulator = 0.0

    # --------------------------------------------------

    def _persist(self) -> None:
        """Saves the current state to the repository."""
        if not self.period_id:
            return

        self.repo.save(
            self.category,
            self.period_id,
            self.target,
            self.played,
            self.accumulator
        )