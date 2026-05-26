# ui/player_controller.py
from typing import Callable

from gi.repository import GLib

from domain.track import Track
from playback.player import PlaybackEngine


class PlayerController:
    def __init__(self, app):
        self.app = app

        self.engine = app.playback_engine  # IMPORTANT: injected engine
        self.engine.set_on_track_end(self._on_track_end)
        self.engine.set_vu_meter_callback(self._on_vu_meter_update) # New: Connect VU meter callback
        self.engine.set_on_error(self._on_playback_error)

        self.current_track = None
        self.last_error = None
        self.has_restorable_track = False
        self.main_window = None # Will be set by the application
        self._consecutive_errors = 0
        self._refresh_timer_id = 0
        self._vu_meter_ui_callback = None # New: Callback for UI to receive VU meter updates

        # Add periodic logging for average track duration
        GLib.timeout_add_seconds(3600, self._update_average_duration_periodically) # Every hour # type: ignore

    # ----------------------------
    # Lifecycle
    # ----------------------------

    def set_main_window(self, main_window):
        self.main_window = main_window
        self.app.register_new_track_callback(self._on_new_track_registered)
        # Register callback for initial setup completion
        self.app.register_initial_setup_complete_callback(self._on_initial_setup_complete)

    # ----------------------------

    def start_backend(self):
        """Initiates the full backend application startup, including scan and setup."""
        # The actual app.start() call now initiates a background thread for scan and setup.
        # We don't need to block here.
        self.app.start() # This kicks off the background scan and setup

        # The initial track selection/resume will now happen in _on_initial_setup_complete
        # after the background scan and restore are done.

    def play_or_resume(self):
        """Handles the logic for the 'Play' button: resume, play next, or start app."""
        if self.engine.state == "paused":
            self.resume()
        elif self.engine.state == "stopped":
            if not self.app._running:
                self.start_backend() # Start the backend if it's not running
            self.play_next() # Always try to play next if stopped (either after startup or if already running)
        # So, remove the immediate track selection logic from here.
        # This method primarily kicks off the backend.
        # The UI will be updated via the callback.

    def _on_initial_setup_complete(self):
        """
        Called on the main thread after the initial background setup (scan, restore) is done.
        This method is responsible for initial UI population and starting playback if applicable.
        """
        if self.main_window:
            self.main_window.library_panel.refresh_library_display()
            self.main_window.queue_panel.refresh_queue_display()
            self.main_window.refresh_status()

            # Now, handle initial playback based on restored state or play next
            if self.app.restored_track:
                self.current_track = self.app.restored_track
                self.has_restorable_track = True
                self.resume_last_track() # This will play the restored track
            else:
                self.play_next() # Start playing the first track if no restore

    def resume_last_track(self):
        if not self.current_track:
            return None

        self.has_restorable_track = False
        self.last_error = None
        self.engine.play(
            str(self.current_track.path),
            self.current_track.replaygain_track_gain_db,
            self.current_track.replaygain_track_peak,
        )

        if self.app.restored_position:
            GLib.timeout_add(500, self._seek_restored_position)

        self.persist_state()
        # Ensure UI is updated after resuming
        if self.main_window:
            GLib.idle_add(lambda: self.main_window.update_track(self.current_track))
            GLib.idle_add(self.main_window.refresh_status)
        return self.current_track

    def stop(self):
        self.persist_state()
        self.engine.stop()

    def pause(self):
        self.engine.pause()
        self.persist_state()

    def resume(self):
        self.engine.resume()
        self.persist_state()

    # ----------------------------
    # Playback flow
    # ----------------------------

    def play_next(self):
        track = self.app.queue_manager.get_next()

        if not track:
            return None

        self.current_track = track
        self.has_restorable_track = False
        self.last_error = None
        self._consecutive_errors = 0

        self.engine.play(
            str(track.path),
            track.replaygain_track_gain_db,
            track.replaygain_track_peak,
        )
        self.app.history_repo.log_play(track)
        self.persist_state()
        if self.main_window:
            GLib.idle_add(self.main_window.refresh_queue)

        return track

    def skip(self):
        self.persist_state()
        self.engine.stop()
        return self.play_next()

    def go_to_beginning(self):
        """Seeks to the beginning of the current track."""
        self.seek(0)

    # ----------------------------
    # Auto-chain playback
    # ----------------------------

    def _on_track_end(self):
        if self.app.get_stop_at_end_enabled():
            self.stop()
            # Reset the "stop at end" flag after it has been triggered
            self.app.set_stop_at_end_enabled(False)
            self.app.queue_manager.clear_auto() # Clear autoqueue when stopping at end
            if self.main_window: GLib.idle_add(self.main_window.refresh_status)
        else:
            self.play_next()

    def _on_playback_error(self, message, debug):
        self._consecutive_errors += 1
        track_name = self.current_track.path.name if self.current_track else "current track"
        self.last_error = f"{track_name}: {message}"
        
        if self._consecutive_errors > 5:
            self.engine.stop()
            self.last_error = "Too many consecutive playback errors. Stopped."
            return

        self.play_next()

    def _on_vu_meter_update(self, peak_levels: list[float], rms_levels: list[float]):
        """Internal callback from PlaybackEngine, forwards to UI callback."""
        if self._vu_meter_ui_callback:
            self._vu_meter_ui_callback(peak_levels, rms_levels)

    def set_vu_meter_ui_callback(self, callback: Callable[[list[float], list[float]], None]):
        self._vu_meter_ui_callback = callback

    # ----------------------------
    # UI-safe helper
    # ----------------------------

    def get_queue_snapshot(self):
        return self.app.queue_manager.snapshot()

    def get_all_tracks(self):
        return self.app.music_repo.get_all_tracks()

    def get_recently_played_tracks(self, limit: int = 50):
        return self.app.music_repo.get_recently_played_tracks(limit)

    def enqueue_manual(self, tracks):
        for track in tracks:
            self.app.queue_manager.enqueue_manual(track)

        self.persist_state()

    def enqueue_manual_next(self, tracks):
        for track in reversed(tracks):
            self.app.queue_manager.enqueue_manual_next(track)

        self.persist_state()

    def remove_manual_queue_positions(self, positions):
        self.app.queue_manager.remove_manual_at(positions)
        self.persist_state()

    def remove_auto_queue_positions(self, positions):
        self.app.queue_manager.remove_auto_at(positions)
        self.persist_state()

    def clear_manual_queue(self):
        self.app.queue_manager.clear_manual()
        self.persist_state()

    def clear_auto_queue(self):
        self.app.queue_manager.clear_auto()
        self.persist_state()

    def move_manual_queue_up(self, positions):
        moved = self.app.queue_manager.move_manual_up(positions)
        self.persist_state()
        return moved

    def move_manual_queue_down(self, positions):
        moved = self.app.queue_manager.move_manual_down(positions)
        self.persist_state()
        return moved

    def move_manual_queue_to_top(self, positions):
        moved = self.app.queue_manager.move_manual_to_top(positions)
        self.persist_state()
        return moved

    def move_manual_queue_to_bottom(self, positions):
        moved = self.app.queue_manager.move_manual_to_bottom(positions)
        self.persist_state()
        return moved

    def rescan_library(self):
        return self.app.scan_music_library()

    def refresh_track_metadata(self, db_instance=None):
        return self.app.refresh_track_metadata(db_instance=db_instance)

    def get_status(self):
        status = self.app.get_status()
        status["playback_state"] = self.engine.state
        status["current_track"] = self.current_track
        status["last_error"] = self.last_error
        status["has_restorable_track"] = self.has_restorable_track
        status["stop_at_end_enabled"] = self.get_stop_at_end_enabled()
        status["shuffle_enabled"] = self.get_shuffle_enabled()
        status["volume"] = self.engine.get_volume()
        return status

    # -----------------------------
    # Position API (NEW)
    # -----------------------------

    def get_position(self):
        return self.engine.get_position()

    def get_duration(self):
        return self.engine.get_duration()

    def seek(self, nanoseconds: int):
        self.engine.seek(nanoseconds)
        self.persist_state()

    def set_volume(self, volume: float):
        self.engine.set_volume(volume)
        self.app.save_volume(self.engine.get_volume())

    def get_volume(self) -> float:
        return self.engine.get_volume()

    def _update_average_duration_periodically(self) -> bool:
        avg = self.app.music_repo.get_overall_average_track_duration()
        if avg is not None:
            import config
            if abs(avg - config.AVERAGE_TRACK_DURATION_SECONDS) > 5:
                config.update_average_duration(round(avg))
        return True # Keep the timer running

    def persist_state(self):
        self.app.persist_state(
            current_track=self.current_track,
            position=self.engine.get_position(),
        )

    def _seek_restored_position(self):
        self.engine.seek(self.app.restored_position)
        self.persist_state()
        return False

    def set_autoqueue_enabled(self, enabled: bool) -> None:
        """Sets the auto-queue enabled state in the application backend."""
        self.app.set_autoqueue_enabled(enabled)

    def get_autoqueue_enabled(self) -> bool:
        """Gets the auto-queue enabled state from the application backend."""
        return self.app.get_autoqueue_enabled()

    def set_stop_at_end_enabled(self, enabled: bool) -> None:
        """Sets the 'stop at end' enabled state in the application backend."""
        self.app.set_stop_at_end_enabled(enabled)

    def get_stop_at_end_enabled(self) -> bool:
        """Gets the 'stop at end' enabled state from the application backend."""
        return self.app.get_stop_at_end_enabled()

    def set_shuffle_enabled(self, enabled: bool) -> None:
        """Sets the shuffle mode enabled state in the application backend."""
        self.app.selection_engine.set_shuffle_enabled(enabled)
        self.app.save_shuffle_state(enabled) # Persist the shuffle state

    def get_shuffle_enabled(self) -> bool:
        """Gets the shuffle mode enabled state from the application backend."""
        return self.app.selection_engine.get_shuffle_enabled()

    def _on_new_track_registered(self, track: Track) -> None:
        """Callback for when a new track is registered by the FileWatcher."""
        if not self.main_window:
            return

        # Debounce UI refreshes during bulk scans to prevent Pango layout storms
        if self._refresh_timer_id:
            GLib.source_remove(self._refresh_timer_id)

        def do_refresh():
            if self.main_window:
                self.main_window.library_panel.refresh_library_display()
                self.main_window.queue_panel.refresh_queue_display()
            self._refresh_timer_id = 0
            return False

        self._refresh_timer_id = GLib.timeout_add(200, do_refresh)
