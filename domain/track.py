from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Track:
    id: int
    path: Path
    artist: str
    title: str
    folder: str
    duration_seconds: int
    replaygain_track_gain_db: float | None = None
    replaygain_track_peak: float | None = None
