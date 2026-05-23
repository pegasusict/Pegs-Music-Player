from datetime import datetime

from domain.track import Track


class PlayHistoryRepository:
    def log_play(self, track: Track) -> None:
        raise NotImplementedError

    def mark_played_in_cycle(self, track_id: int) -> None:
        raise NotImplementedError

    def reset_cycle(self) -> None:
        raise NotImplementedError

    def get_unplayed_tracks(self, folders: list[str]) -> list[Track]:
        raise NotImplementedError

    def get_last_played_artist(self) -> str | None:
        raise NotImplementedError

    def log_daily_play(self, track: Track) -> None:
        raise NotImplementedError

    def log_timeslot_play(self, track: Track, slot: str) -> None:
        raise NotImplementedError

    def reset_daily(self) -> None:
        raise NotImplementedError

    def reset_timeslot(self, slot: str) -> None:
        raise NotImplementedError
    
    def get_last_n_periods(self, period_type: str, period_name: str, n: int) -> list[int]:
        raise NotImplementedError
    
    def today(self) -> datetime:
        return datetime.today()
