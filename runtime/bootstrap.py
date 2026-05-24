import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import config

from app_queue.queue_manager import QueueManager
from domain.timeslot import Timeslot
from domain.track import Track
from infrastructure.file_watcher import FileWatcher
from infrastructure.spread_state_repository import SpreadStateRepository
from repository.music_repository import MusicRepository, ScanResult
from runtime.slot_runtime import SlotRuntime
from scheduler.period_target_calculator import PeriodTargetCalculator
from scheduler.selection_engine import SelectionEngine
from scheduler.spread_controller import SpreadController
from scheduler.timeslot_scheduler import TimeslotScheduler

from persistence.sqlite_history_repository import SqlitePlayHistoryRepository
from infrastructure.database import Database
from playback.player import PlaybackEngine
from gi.repository import GLib # Import GLib for idle_add

logger = logging.getLogger(__name__)


class Application:
    """
    Central runtime bootstrap.

    Responsible for:
      - Wiring all components
      - Lifecycle management
    """

    def __init__(self, database: Database):
        logger.debug("Initializing Application bootstrap...")
        self.database = database

        # Load state from DB early to identify potential locking issues 
        # before initializing heavy external components like GStreamer.
        logger.debug("Loading saved volume from database...")
        saved_volume = self.load_volume()
        logger.debug(f"Volume loaded: {saved_volume}")

        logger.debug("Initializing repositories...")
        # Core Infrastructure
        self.music_repo = MusicRepository(database)
        self.queue_manager = QueueManager()
        
        # Scheduler
        logger.debug("Building timeslots...")
        self.scheduler = TimeslotScheduler(self._build_timeslots_from_raw_config(config.load_config()))
        
        # Spread Infrastructure
        self.spread_repo = SpreadStateRepository(database) # type: ignore
        self.daily_spread = SpreadController("daily",self.spread_repo)
        self.slot_spread = SpreadController("slot", self.spread_repo)

        logger.debug("Setting up calculators and history...")
        self.history_repo = SqlitePlayHistoryRepository(database) # Keep this line
        self.period_calculator = PeriodTargetCalculator(self.history_repo, self.music_repo) # Pass music_repo
        
        # FileWatcher
        logger.debug("Initializing FileWatcher...")
        self.filewatcher = FileWatcher(
            folders=[],  # will be configured by SlotRuntime
            supported_extensions=config.SUPPORTED_EXTENSIONS,
            on_new_track=self._register_new_track,
        )
        
        # Slot Runtime (scheduler + watcher integration)
        logger.debug("Initializing SlotRuntime and SelectionEngine...")
        self.slot_runtime = SlotRuntime(
            scheduler=self.scheduler,
            filewatcher=self.filewatcher,
            base_folder=config.BASE_FOLDER,
        )
        # Selection Engine
        self.selection_engine = SelectionEngine(
            music_repo=self.music_repo,
            spread_repo=self.spread_repo,
            queue=self.queue_manager,
            scheduler=self.scheduler,
            daily_spread=self.daily_spread,
            slot_spread=self.slot_spread,
            calculator=self.period_calculator
        )
        # Load and apply shuffle state immediately after selection_engine is created
        initial_shuffle_state = self.load_shuffle_state()
        self.selection_engine.set_shuffle_enabled(initial_shuffle_state)

        # Playback
        logger.debug("Initializing PlaybackEngine (GStreamer)...")
        self.playback_engine = PlaybackEngine()
        logger.debug("Calling load_volume() (Database query)...")
        saved_volume = self.load_volume()
        logger.debug(f"load_volume() returned {saved_volume}. Applying to engine...")
        self.playback_engine.set_volume(saved_volume)
        logger.debug("Finalizing bootstrap initialization.")

        self._running = False
        self._autoqueue_enabled: bool = self.load_autoqueue_state()
        self._new_track_callbacks = [] # New: List to hold callbacks for new tracks
        self._stop_at_end_enabled: bool = self.load_stop_at_end_state()
        self._initial_setup_complete_callbacks = [] # New: List to hold callbacks for initial setup completion
        self._state_restored = False
        self.restored_track = None
        self.restored_position = 0
        self.last_scan_at: datetime | None = None
        self.last_scan_result = ScanResult()
        self._log_startup_health()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def start(self):
        if self._running:
            return

        logger.info("Starting Application runtime")

        self._running = True
        # Start the initial scan and setup in a separate thread
        threading.Thread(target=self._perform_initial_setup, daemon=True).start()

    def _perform_initial_setup(self):
        """
        Performs the initial music library scan and subsequent setup steps
        that depend on the scan being complete. This runs in a background thread.
        """
        try:
            # Use a separate database instance for the scan thread to avoid contention
            scan_db = self.create_new_db_instance()
            try:
                self.scan_music_library(db_instance=scan_db)
            finally:
                scan_db.close()
            logger.info("Initial music library scan completed.")

            self.restore_state()

            # Ensure initial slot detection before watcher starts
            current_slot = self.scheduler.current_slot

            if current_slot:
                active = [f for f in current_slot.folders if f != "NOT_IN_USE"]
                if current_slot.each_iteration_folder != "NOT_IN_USE":
                    active.append(current_slot.each_iteration_folder)
                self.filewatcher.reconfigure(self._folder_paths(active))

            # Start runtime loop
            self.slot_runtime.start()

            # Notify UI that initial setup is complete
            GLib.idle_add(self._post_initial_setup_ui_update)

        except Exception as e:
            logger.critical(f"Error during initial application setup: {e}", exc_info=True)

    def _post_initial_setup_ui_update(self):
        """
        Performs UI updates after the initial setup is complete.
        This must be called on the main GTK thread.
        """
        for callback in self._initial_setup_complete_callbacks:
            callback()
        return False # Ensure this only runs once

    def register_initial_setup_complete_callback(self, callback: Callable[[], None]) -> None:
        """Registers a callback to be called when the initial application setup is complete."""
        self._initial_setup_complete_callbacks.append(callback)

    # ----------------------------------------------------------

    def stop(self):
        if not self._running:
            return

        logger.info("Stopping Application runtime")

        self.persist_state()
        self.playback_engine.shutdown()
        self.slot_runtime.stop()
        self.database.close()
        self._running = False
        logger.info("Application runtime stopped")

    def scan_music_library(self, db_instance: Optional[Database] = None) -> ScanResult:
        """Scans the music library, optionally using a provided database instance."""
        repo_db = db_instance if db_instance else self.database
        self.last_scan_result = self.music_repo.scan_folders(
            config.BASE_FOLDER,
            self._configured_folders(),
            config.SUPPORTED_EXTENSIONS,
            db_instance=repo_db # Pass the specific DB instance to music_repo
        )
        self.last_scan_at = datetime.now()
        self.queue_manager.prune_unavailable(self.music_repo) # This will use self.music_repo's db
        logger.info("Scanned %s files, removed %s stale tracks, saw %s metadata failures", self.last_scan_result.scanned_files, self.last_scan_result.stale_tracks_removed, self.last_scan_result.metadata_failures)
        return self.last_scan_result

    def refresh_track_metadata(self, db_instance: Optional[Database] = None) -> ScanResult:
        """Refresh cached metadata for tracks already registered in the library."""
        repo_db = db_instance if db_instance else self.database
        self.last_scan_result = self.music_repo.refresh_track_metadata(db_instance=repo_db)
        self.last_scan_at = datetime.now()
        logger.info(
            "Refreshed metadata for %s files, saw %s missing files and %s metadata failures",
            self.last_scan_result.scanned_files,
            self.last_scan_result.stale_tracks_removed,
            self.last_scan_result.metadata_failures,
        )
        return self.last_scan_result

    def get_status(self) -> dict[str, object]:
        snapshot = self.queue_manager.snapshot()
        slot = self.scheduler.current_slot
        total_tracks, replaygain_tracks = self.music_repo.get_replaygain_coverage()

        return {
            "slot": slot.name if slot else "-",
            "library_count": total_tracks,
            "replaygain_count": replaygain_tracks,
            "manual_count": len(snapshot["manual"]),
            "auto_count": len(snapshot["auto"]),
            "last_scan_at": self.last_scan_at,
            "last_scan_result": self.last_scan_result,
            "running": self._running,
        }

    def _log_startup_health(self) -> None:
        """Log a compact runtime snapshot for troubleshooting startup issues."""
        try:
            connection = self.database.connect()
            migrations = [
                row[0]
                for row in connection.execute(
                    "SELECT revision FROM schema_migrations ORDER BY revision"
                ).fetchall()
            ]
            track_count = connection.execute(
                "SELECT COUNT(*) FROM tracks"
            ).fetchone()[0]
            replaygain_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM tracks
                WHERE replaygain_track_gain_db IS NOT NULL
                  AND replaygain_track_peak IS NOT NULL
                """
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        except Exception:
            logger.exception("Startup health check failed")
            return

        current_slot = self.scheduler.current_slot
        configured_folders = self._configured_folders()
        logger.warning(
            "Startup health: db_path=%s migrations=%s integrity=%s "
            "tracks=%s replaygain_tracks=%s current_slot=%s "
            "configured_folders=%s limiter_available=%s",
            self.database.path,
            ",".join(migrations) if migrations else "none",
            integrity,
            track_count,
            replaygain_count,
            current_slot.name if current_slot else "-",
            ",".join(configured_folders) if configured_folders else "none",
            self.playback_engine.limiter_available,
        )

    def restore_state(self) -> None:
        if self._state_restored:
            return

        self.queue_manager.restore(self.database, self.music_repo)

        saved = self.database.load_playback_state()
        if saved:
            track_id, position = saved
            self.restored_track = self.music_repo.get_by_id(track_id)
            self.restored_position = position

        self._state_restored = True

    def persist_state(self, current_track=None, position: int | None = None) -> None:
        self.queue_manager.persist(self.database)
        self.save_volume(self.playback_engine.get_volume())
        self.save_shuffle_state(self.selection_engine._shuffle_enabled) # Save shuffle state
        self.save_stop_at_end_state(self._stop_at_end_enabled)
        self.save_autoqueue_state(self._autoqueue_enabled)

        track = current_track
        if position is None:
            position = self.playback_engine.get_position()

        if track:
            self.database.save_playback_state(track.id, position)

    def load_volume(self) -> float:
        value = self.database.load_app_state("volume")

        if value is None:
            return 0.8

        try:
            return max(0.0, min(1.0, float(value)))
        except ValueError:
            return 0.8

    def save_volume(self, volume: float) -> None:
        self.database.save_app_state("volume", str(max(0.0, min(1.0, volume))))

    def load_shuffle_state(self) -> bool:
        """Loads the shuffle enabled state from the database."""
        value = self.database.load_app_state("shuffle_enabled")
        if value is None:
            return False # Default to shuffle off if not found
        return value.lower() == 'true'

    def save_shuffle_state(self, enabled: bool) -> None:
        """Saves the shuffle enabled state to the database."""
        self.database.save_app_state("shuffle_enabled", str(enabled).lower())

    def load_autoqueue_state(self) -> bool:
        """Loads the auto-queue enabled state from the database."""
        value = self.database.load_app_state("autoqueue_enabled")
        if value is None:
            return True  # Default to ON
        return value.lower() == 'true'

    def load_stop_at_end_state(self) -> bool:
        """Loads the 'stop at end' enabled state from the database."""
        value = self.database.load_app_state("stop_at_end_enabled")
        if value is None:
            return False  # Default to OFF
        return value.lower() == 'true'

    def save_autoqueue_state(self, enabled: bool) -> None:
        """Saves the auto-queue enabled state to the database."""
        self.database.save_app_state("autoqueue_enabled", str(enabled).lower())

    def save_stop_at_end_state(self, enabled: bool) -> None:
        """Saves the 'stop at end' enabled state to the database."""
        self.database.save_app_state("stop_at_end_enabled", str(enabled).lower())

    def _register_new_track(self, path: Path) -> None:
        track = self.music_repo.register_path(path, config.BASE_FOLDER)

        if track:
            if self._autoqueue_enabled:
                self.queue_manager.enqueue_auto(track)
                
            # Notify any registered listeners
            for callback in self._new_track_callbacks:
                callback(track)

    def set_autoqueue_enabled(self, enabled: bool) -> None:
        """Sets the state of the auto-queue."""
        self._autoqueue_enabled = enabled
        self.save_autoqueue_state(enabled)
        logger.info(f"Auto-queue {'enabled' if enabled else 'disabled'}")

    def set_stop_at_end_enabled(self, enabled: bool) -> None:
        """Sets the state of 'stop at end'."""
        self._stop_at_end_enabled = enabled
        self.save_stop_at_end_state(enabled)
        logger.info(f"Stop at end {'enabled' if enabled else 'disabled'}")

    def create_new_db_instance(self) -> Database:
        """Creates and returns a new Database instance, primarily for background tasks."""
        return Database(config.DB_PATH)

    def get_autoqueue_enabled(self) -> bool:
        """Returns the current state of the auto-queue."""
        return self._autoqueue_enabled

    def get_stop_at_end_enabled(self) -> bool:
        """Returns the current state of 'stop at end'."""
        return self._stop_at_end_enabled

    def register_new_track_callback(self, callback: Callable[[Track], None]) -> None:
        """Registers a callback to be called when a new track is discovered."""
        self._new_track_callbacks.append(callback)

    def get_raw_config(self) -> dict:
        """Returns the current raw configuration from the YAML file."""
        import config
        return config.load_config()

    def apply_config(self, new_config: dict):
        """Saves new configuration and updates relevant components."""
        original_config = config.load_config()
        requested_db_path = str(Path(str(new_config.get("db_path", ""))).expanduser())
        active_db_path = str(Path(self.database.path).expanduser())

        if requested_db_path and requested_db_path != active_db_path:
            logger.warning(
                "Ignoring live database path change from %s to %s; restart required",
                active_db_path,
                requested_db_path,
            )
            new_config = dict(new_config)
            new_config["db_path"] = original_config.get("db_path", self.database.path)

        # Save the new configuration to the YAML file
        config.save_config(new_config)
        # Reload the configuration to ensure all module-level constants are updated
        # and then apply the changes to the running application.
        updated_raw_config = config.load_config()

        from infrastructure.logging_setup import init_logging
        init_logging(config.LOG_LEVEL, config.LOG_FILE)

        self._rebuild_scheduler_and_notify_slot_runtime(updated_raw_config)

    def _rebuild_scheduler_and_notify_slot_runtime(self, raw_config: dict):
        """
        Rebuilds the TimeslotScheduler with the new configuration
        and notifies the SlotRuntime to reconfigure its FileWatcher.
        """
        logger.info("Applying new timeslot configuration.")
        self.scheduler = TimeslotScheduler(self._build_timeslots_from_raw_config(raw_config))
        self.selection_engine.scheduler = self.scheduler
        self.slot_runtime.scheduler = self.scheduler
        self.slot_runtime.base_folder = config.BASE_FOLDER
        self.filewatcher.set_supported_extensions(config.SUPPORTED_EXTENSIONS)
        self.slot_runtime.trigger_reconfiguration()
        logger.info("Timeslot scheduler rebuilt and SlotRuntime notified.")


    def _build_timeslots_from_raw_config(self, raw_config: dict) -> list[Timeslot]:
        """
        Builds Timeslot objects from a raw configuration dictionary.
        This method no longer relies on the global TIMESLOTS constant.
        """
        timeslots_data = raw_config.get("timeslots", [])
        built_timeslots = []
        for slot in timeslots_data:
            try:
                # Parse time strings into datetime.time objects
                start_time = datetime.strptime(slot["start"], "%H:%M").time()
                end_time = datetime.strptime(slot["end"], "%H:%M").time()

                built_timeslots.append(
                    Timeslot(
                        name=str(slot["name"]),
                        start=start_time,
                        end=end_time,
                        folders=[str(folder) for folder in slot["folders"]], # type: ignore
                        each_iteration_folder=str(slot.get("each_iteration_folder", "NOT_IN_USE")) # type: ignore
                    )
                )
            except KeyError as e:
                logger.error(f"Malformed timeslot entry in config: missing key '{e}'. Skipping slot: {slot}")
            except ValueError as e:
                logger.error(f"Invalid time format in timeslot entry: {e}. Skipping slot: {slot}")
        return built_timeslots

    def _folder_paths(self, folders: list[str]):
        # Use the current BASE_FOLDER from the config module, which is updated on config reload.
        return [config.BASE_FOLDER / folder for folder in folders]

    def _configured_folders(self) -> list[str]:
        # Use the current DAILY_FOLDER and TIMESLOTS from the config module, which are updated on config reload.
        folders: list[str] = [f for f in [str(config.DAILY_FOLDER)] if f != "NOT_IN_USE"] # type: ignore

        # Iterate over the current scheduler's timeslots, which will be rebuilt after config changes.
        for slot in self.scheduler.timeslots:
            folders.extend(f for f in slot.folders if f != "NOT_IN_USE") # type: ignore
            if slot.each_iteration_folder != "NOT_IN_USE":
                folders.append(slot.each_iteration_folder)

        return list(dict.fromkeys(folders))
