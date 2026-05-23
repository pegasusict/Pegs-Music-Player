import random
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from typing import Dict # Added for type hinting the cache
from mutagen import File as MutagenFile
from domain.timeslot import Timeslot # Import Timeslot for type hinting
from infrastructure.database import Database
from infrastructure.queries import track_queries # type: ignore
from domain.track import Track
from config import DAILY_FOLDER, AVERAGE_TRACK_DURATION_SECONDS

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanResult:
    scanned_files: int = 0
    registered_tracks: int = 0
    stale_tracks_removed: int = 0
    missing_folders: int = 0
    metadata_failures: int = 0


class MusicRepository:
    """
    Repository for managing music tracks and selection logic.
    - Retrieves tracks from the database
    - Implements selection logic for regular playback cycles
    """

    def __init__(self, db: Database):
        self.db = db
        self._last_metadata_failed = False
        self._folder_average_duration_cache: Dict[str, float] = {} # New cache

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def get_regular(
        self,
        folders: Iterable[str],
        exclude_artist: Optional[str],
        shuffle: bool = False,
    ) -> Optional[Track]:
        """Selects the next track for regular playback cycle."""
        folders = list(folders)
        if not folders:
            return None

        # Attempt 1: Get candidates respecting artist exclusion, from unplayed cycle.
        all_candidates: list[Track] = []
        track: Optional[Track] = None
        folders_exhausted_strict_artist: set[str] = set() # Track folders that yielded no candidates

        for folder in folders:
            folder_candidates = self._fetch_tracks_for_selection(folder, exclude_artist, strict_artist=True, from_unplayed_cycle=True)
            if not folder_candidates:
                folders_exhausted_strict_artist.add(folder)
            all_candidates.extend(folder_candidates)
        
        if all_candidates:
            track = self._select_candidate(all_candidates, shuffle)
            self.db.mark_cycle_played(track.folder, track.id)
            return track

        # Attempt 2: If no track found, try again without strict artist exclusion, from unplayed cycle.
        all_candidates.clear()
        folders_exhausted_non_strict_artist: set[str] = set()

        for folder in folders:
            folder_candidates = self._fetch_tracks_for_selection(folder, None, strict_artist=False, from_unplayed_cycle=True)
            if not folder_candidates:
                folders_exhausted_non_strict_artist.add(folder)
            all_candidates.extend(folder_candidates)
        
        if all_candidates:
            track = self._select_candidate(all_candidates, shuffle)
            self.db.mark_cycle_played(track.folder, track.id)
            return track

        # Attempt 3: If still no track, it means some folders are truly exhausted.
        # Reset cycles for *only* those folders that were exhausted in the second pass.
        # Then try to select again from those reset folders (getting all tracks).
        all_candidates.clear()
        for folder in folders_exhausted_non_strict_artist:
            logger.info(f"Resetting cycle for folder: {folder} as it's exhausted.")
            self.db.reset_cycle(folder)
            # After reset, get all tracks from this folder (from_unplayed_cycle=False)
            folder_candidates = self._fetch_tracks_for_selection(folder, None, strict_artist=False, from_unplayed_cycle=False)
            all_candidates.extend(folder_candidates)
        
        if all_candidates:
            track = self._select_candidate(all_candidates, shuffle)
            self.db.mark_cycle_played(track.folder, track.id)
        return track

    def register_path(self, path: Path, base_folder: Path, db_instance: Optional[Database] = None) -> Optional[Track]:
        """Register one audio file and return its database-backed Track."""
        path = path.expanduser().resolve()
        repo_db = db_instance if db_instance else self.db

        if not path.is_file():
            return None

        try:
            folder = path.relative_to(base_folder.expanduser().resolve()).parts[0]
        except (ValueError, IndexError):
            folder = path.parent.name

        (
            artist,
            title,
            duration_seconds,
            replaygain_track_gain_db,
            replaygain_track_peak,
        ) = self._read_metadata(path)
        track_id, was_inserted = track_queries.add_track(
            repo_db,
            str(path),
            artist,
            title,
            folder,
            duration_seconds,
            replaygain_track_gain_db,
            replaygain_track_peak,
        )

        if not was_inserted:
            existing_track_row = track_queries.get_track_by_id(repo_db, track_id)
            if existing_track_row and existing_track_row[5] in (0, None): # duration_seconds is the 6th element (index 5)
                logger.info(f"Updating missing duration for existing track: {path}")
                track_queries.update_track_duration(repo_db, track_id, duration_seconds)
            track_queries.update_track_replaygain(
                repo_db,
                track_id,
                replaygain_track_gain_db,
                replaygain_track_peak,
            )

        self.invalidate_folder_average_duration_cache(folder) # Invalidate cache for this folder

        return Track(
            id=track_id,
            path=path,
            artist=artist,
            title=title,
            folder=folder,
            duration_seconds=duration_seconds,
            replaygain_track_gain_db=replaygain_track_gain_db,
            replaygain_track_peak=replaygain_track_peak,
        )

    def scan_folders(
        self,
        base_folder: Path,
        folders: Iterable[str],
        supported_extensions: set[str],
        db_instance: Optional[Database] = None # New: Optional database instance for scanning
    ) -> ScanResult:
        """Recursively scan configured folders into the tracks table."""
        result = ScanResult()
        extensions = {ext.lower() for ext in supported_extensions}
        folders = list(dict.fromkeys(folders))
        seen_paths: set[str] = set()

        # Filter out NOT_IN_USE folders from the scan
        folders_to_scan = [f for f in folders if f != "NOT_IN_USE"]

        for folder in folders:
            root = (base_folder / folder).expanduser().resolve()

            if not root.exists():
                logger.warning("Music folder does not exist: %s", root)
                result.missing_folders += 1
                continue

            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in extensions and folder != "NOT_IN_USE":
                    result.scanned_files += 1
                    seen_paths.add(str(path.expanduser().resolve()))
                    if self.register_path(path, base_folder, db_instance=db_instance):
                        result.registered_tracks += 1

                    if self._last_metadata_failed:
                        result.metadata_failures += 1

        # Invalidate cache for all scanned folders after scan
        for folder in folders_to_scan:
            self.invalidate_folder_average_duration_cache(folder)
        result.stale_tracks_removed = self._remove_stale_tracks(folders, seen_paths, db_instance=db_instance)
        return result

    def get_all_tracks(self, db_instance: Optional[Database] = None) -> list[Track]:
        """Return all registered tracks."""
        repo_db = db_instance if db_instance else self.db
        return [self._track_from_row(row) for row in track_queries.get_all_tracks(repo_db)]

    def get_by_id(self, track_id: int, db_instance: Optional[Database] = None) -> Optional[Track]:
        """Return one registered track by ID."""
        repo_db = db_instance if db_instance else self.db
        row = track_queries.get_track_by_id(repo_db, track_id)
        return self._track_from_row(row) if row else None
    
    def get_recently_played_tracks(self, limit: int = 50, db_instance: Optional[Database] = None) -> list[Track]:
        """Returns a list of recently played tracks."""
        repo_db = db_instance if db_instance else self.db
        return [self._track_from_row(row) for row in track_queries.get_recently_played_tracks(repo_db, limit)]

    def refresh_track_metadata(self, db_instance: Optional[Database] = None) -> ScanResult:
        """Refresh cached tags, durations, and ReplayGain data for registered tracks."""
        repo_db = db_instance if db_instance else self.db
        result = ScanResult()
        affected_folders: set[str] = set()

        for track in self.get_all_tracks(db_instance=repo_db):
            if not track.path.exists():
                result.stale_tracks_removed += 1
                continue

            (
                artist,
                title,
                duration_seconds,
                replaygain_track_gain_db,
                replaygain_track_peak,
            ) = self._read_metadata(track.path)

            result.scanned_files += 1
            if self._last_metadata_failed:
                result.metadata_failures += 1

            track_queries.update_track_metadata(
                repo_db,
                track.id,
                artist,
                title,
                duration_seconds,
                replaygain_track_gain_db,
                replaygain_track_peak,
            )
            affected_folders.add(track.folder)

        for folder in affected_folders:
            self.invalidate_folder_average_duration_cache(folder)

        return result

    def count_daily_special(self) -> int:
        """Return the number of tracks in the daily special folder."""
        if DAILY_FOLDER == "NOT_IN_USE":
            return 0
        return self._count_folder(DAILY_FOLDER)

    def get_daily_special(self, exclude_artist: Optional[str]) -> Optional[Track]:
        """Select a daily special track, avoiding the last artist when possible."""
        if DAILY_FOLDER == "NOT_IN_USE":
            return None
        return self._select_special(DAILY_FOLDER, exclude_artist)

    def count_slot_special(self, slot: Timeslot) -> int:
        """Return the number of tracks in the special folder for a slot."""
        folder = slot.each_iteration_folder
        return self._count_folder(folder)

    def get_slot_special(self, slot: Timeslot, exclude_artist: Optional[str]) -> Optional[Track]:
        """Select a slot special track, avoiding the last artist when possible."""
        folder = slot.each_iteration_folder
        if not folder:
            return None
        return self._select_special(folder, exclude_artist)

    # ---------------------------------------------------------
    # Internal Selection
    # ---------------------------------------------------------

    def _fetch_tracks_for_selection(
        self,
        folder: str,
        exclude_artist: Optional[str],
        strict_artist: bool,
        from_unplayed_cycle: bool # New parameter to indicate if we should get unplayed or all
    ) -> list[Track]:
        """
        Retrieves tracks from a single folder based on criteria.
        If from_unplayed_cycle is True, gets unplayed tracks for the current cycle.
        Otherwise, gets all tracks in the folder.
        """
        rows = []
        if from_unplayed_cycle:
            rows = track_queries.get_unplayed_cycle_tracks(self.db, folder)
        else:
            rows = track_queries.get_tracks_by_folder(self.db, folder)

        candidates: list[Track] = []
        for row in rows:
            track = self._track_from_row(row)
            if strict_artist and exclude_artist and track.artist == exclude_artist:
                continue
            candidates.append(track)
        return candidates

    def _select_special(self, folder: str, exclude_artist: Optional[str]) -> Optional[Track]:
        """Selects a track from a special folder, applying artist exclusion if needed."""
        # Attempt 1: Strict artist exclusion
        candidates = self._fetch_tracks_for_selection(folder, exclude_artist, strict_artist=True, from_unplayed_cycle=True)
        if candidates:
            track = self._select_candidate(candidates, shuffle=True)
            self.db.mark_cycle_played(track.folder, track.id)
            return track

        # Attempt 2: No strict artist exclusion
        candidates = self._fetch_tracks_for_selection(folder, None, strict_artist=False, from_unplayed_cycle=True)
        if candidates:
            track = self._select_candidate(candidates, shuffle=True)
            self.db.mark_cycle_played(track.folder, track.id)
            return track

        # Attempt 3: Reset cycle and try again (no strict artist exclusion)
        logger.info(f"Resetting cycle for special folder: {folder}")
        self.db.reset_cycle(folder)
        candidates = self._fetch_tracks_for_selection(folder, None, strict_artist=False, from_unplayed_cycle=False)
        track = self._select_candidate(candidates, shuffle=True) if candidates else None

        if track:
            self.db.mark_cycle_played(track.folder, track.id)

        return track

    def _calculate_folder_average_duration(self, folder: str) -> float:
        """Calculates the average track duration for a given folder."""
        if folder == "NOT_IN_USE":
            return float(AVERAGE_TRACK_DURATION_SECONDS)
        durations = track_queries.get_track_durations_by_folder(self.db, folder)
        if not durations:
            return float(AVERAGE_TRACK_DURATION_SECONDS) # Fallback to global config
        return sum(durations) / len(durations)

    def get_average_track_duration_for_folder(self, folder: str) -> float:
        """Returns the cached or calculated average track duration for a folder."""
        if folder not in self._folder_average_duration_cache:
            self._folder_average_duration_cache[folder] = self._calculate_folder_average_duration(folder)
        return self._folder_average_duration_cache[folder]

    def invalidate_folder_average_duration_cache(self, folder: str) -> None:
        """Invalidates the average duration cache for a specific folder."""
        if folder == "NOT_IN_USE":
            return
        if folder in self._folder_average_duration_cache:
            del self._folder_average_duration_cache[folder]
            logger.debug(f"Invalidated average duration cache for folder: {folder}")

    def get_overall_average_track_duration(self) -> Optional[float]:
        all_durations = track_queries.get_all_track_durations(self.db)
        if all_durations:
            return sum(all_durations) / len(all_durations)
        return None

    def get_replaygain_coverage(self) -> tuple[int, int]:
        """Return total tracks and tracks with cached ReplayGain track data."""
        return track_queries.get_replaygain_coverage(self.db)

    def _count_folder(self, folder: str) -> int:
        """Count the number of tracks in a specific folder."""
        if folder == "NOT_IN_USE":
            return 0
        return len(track_queries.get_tracks_by_folder(self.db, folder))

    def _remove_stale_tracks(self, folders: list[str], seen_paths: set[str], db_instance: Optional[Database] = None) -> int:
        """Remove tracks from the database that no longer exist on disk."""
        removed = 0
        affected_folders: set[str] = set() # Initialize affected_folders
        folder_set = set(folders)
        repo_db = db_instance if db_instance else self.db

        for track in self.get_all_tracks(db_instance=repo_db):
            if track.folder not in folder_set:
                continue

            path = str(track.path.expanduser().resolve())
            if path in seen_paths and track.path.exists():
                continue

            track_queries.delete_track(repo_db, track.id)
            removed += 1
            affected_folders.add(track.folder) # Mark folder for cache invalidation
        
        for folder in affected_folders:
            self.invalidate_folder_average_duration_cache(folder)

        return removed

    def _track_from_row(self, row) -> Track:
        """Convert a database row to a Track object."""
        return Track(
            id=row[0],
            path=Path(row[1]),
            artist=row[2],
            title=row[3],
            folder=row[4],
            duration_seconds=row[5],
            replaygain_track_gain_db=row[6] if len(row) > 6 else None,
            replaygain_track_peak=row[7] if len(row) > 7 else None,
        )

    def _read_metadata(self, path: Path) -> tuple[str, str, int, float | None, float | None]:
        """Read metadata from an audio file, returning artist and duration. Logs and defaults on failure."""
        self._last_metadata_failed = False
        artist = path.parent.name
        title = path.stem
        duration_seconds = 210
        replaygain_track_gain_db = None
        replaygain_track_peak = None

        try:
            audio = MutagenFile(path, easy=True)
        except Exception:
            self._last_metadata_failed = True
            logger.warning("Failed reading metadata for %s", path)
            return artist, title, duration_seconds, replaygain_track_gain_db, replaygain_track_peak

        if audio:
            if audio.tags:
                artists = audio.tags.get("artist") or audio.tags.get("albumartist")
                if artists:
                    artist = str(artists[0])
                
                titles = audio.tags.get("title")
                if titles:
                    title = str(titles[0])

            if audio.info and audio.info.length:
                duration_seconds = max(1, round(audio.info.length))

        replaygain_track_gain_db, replaygain_track_peak = self._read_replaygain(path)

        return (
            artist,
            title,
            duration_seconds,
            replaygain_track_gain_db,
            replaygain_track_peak,
        )

    def _read_replaygain(self, path: Path) -> tuple[float | None, float | None]:
        """Read ReplayGain track tags written by tools such as rsgain."""
        try:
            audio = MutagenFile(path, easy=False)
        except Exception:
            logger.debug("Failed reading ReplayGain tags for %s", path, exc_info=True)
            return None, None

        if not audio or not audio.tags:
            return None, None

        gain_db = None
        peak = None

        for key, value in audio.tags.items():
            tag_name = self._replaygain_tag_name(key, value)
            if tag_name == "replaygain_track_gain":
                gain_db = self._parse_replaygain_float(value)
            elif tag_name == "replaygain_track_peak":
                peak = self._parse_replaygain_float(value)

        return gain_db, peak

    def _replaygain_tag_name(self, key: str, value) -> str:
        description = str(getattr(value, "desc", ""))
        combined = f"{key} {description}".lower().replace("-", "_")
        if "replaygain_track_gain" in combined:
            return "replaygain_track_gain"
        if "replaygain_track_peak" in combined:
            return "replaygain_track_peak"
        return ""

    def _parse_replaygain_float(self, value) -> float | None:
        if hasattr(value, "text") and value.text:
            raw = str(value.text[0])
        elif isinstance(value, (list, tuple)) and value:
            raw = str(value[0])
        else:
            raw = str(value)

        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _select_candidate(
        self,
        tracks: list[Track],
        shuffle: bool = True
    ) -> Track:
        """Selects one track from a list of candidates, applying shuffle if enabled."""
        if not tracks:
            raise ValueError("No tracks available for selection.")
        
        if shuffle:
            return random.choice(tracks)

        #linear mode: sort by path to ensure detemenistic alphabetical order.
        tracks.sort(key=lambda t: t.path)
        return tracks[0]
