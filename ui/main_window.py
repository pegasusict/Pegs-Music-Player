import logging
import threading

from gi.repository import GLib, Gtk, Pango

from domain.track import Track
from ui.widgets.playback_panel import PlaybackPanel
from ui.widgets.library_panel import LibraryPanel
from ui.widgets.queue_panel import QueuePanel


class MainWindow(Gtk.ApplicationWindow):
    logger = logging.getLogger(__name__)

    """Main application window for the music player."""
    BASE_TITLE = "Pegasus' Music Player"
    def __init__(self, app_controller):
        super().__init__(title=self.BASE_TITLE)

        self.app = app_controller
        self.connect("close-request", self.on_close_request)

        self.set_default_size(1200, 600)

        self.current_track_id = None
        self.library_tracks: list[Track] = []

        # -------------------------
        # Root layout
        # -------------------------

        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_child(self.page)

        self.status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.page.append(self.status_bar)

        # Status bar labels with constrained width to prevent Pango issues
        self.status_slot_label = Gtk.Label(label="Slot: -", ellipsize=Pango.EllipsizeMode.END, max_width_chars=15)
        self.status_bar.append(self.status_slot_label)

        self.status_library_label = Gtk.Label(label="Library: 0 tracks", ellipsize=Pango.EllipsizeMode.END, max_width_chars=30)
        self.status_bar.append(self.status_library_label)

        self.status_queue_label = Gtk.Label(
            label="Queue: 0 manual, 0 auto", ellipsize=Pango.EllipsizeMode.END, max_width_chars=30
        )
        self.status_bar.append(self.status_queue_label)

        self.status_playback_label = Gtk.Label(
            label="Playback: stopped", ellipsize=Pango.EllipsizeMode.END, max_width_chars=20
        )
        self.status_bar.append(self.status_playback_label)

        self.status_scan_label = Gtk.Label(label="Last scan: never")
        self.status_bar.append(self.status_scan_label)

        self.rescan_button = Gtk.Button(label="Rescan")
        self.rescan_button.connect("clicked", lambda _: self.on_rescan_library())
        self.status_bar.append(self.rescan_button)

        self.metadata_button = Gtk.Button(label="Metadata")
        self.metadata_button.set_tooltip_text("Refresh tags, durations, and ReplayGain data for registered tracks")
        self.metadata_button.connect("clicked", lambda _: self.on_refresh_metadata())
        self.status_bar.append(self.metadata_button)

        self.settings_button = Gtk.Button(label="Settings")
        self.settings_button.connect("clicked", self.on_open_settings)
        self.status_bar.append(self.settings_button)

        self.root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.root.set_vexpand(True)
        self.root.set_homogeneous(True)
        self.page.append(self.root)

        # Instantiate panels
        self.playback_panel = PlaybackPanel(self.app, self)
        self.root.append(self.playback_panel)

        self.queue_panel = QueuePanel(self.app, self)
        self.root.append(self.queue_panel)

        self.library_panel = LibraryPanel(self.app, self)
        self.root.append(self.library_panel)


        # periodic refresh
        self._status_timer_id = GLib.timeout_add(1000, self.refresh_status)
        GLib.timeout_add(5000, self.persist_playback_state)
        self._progress_timer_id = GLib.timeout_add(250, self.update_progress)
        # Removed initial refreshes that block the UI thread with DB queries
    # ---------------------------------------------------------
  

    def on_open_settings(self, _btn):
        """Opens the configuration settings window."""
        self.logger.debug("Attempting to open settings window.")
        from ui.settings_window import SettingsWindow
        try:
            settings_win = SettingsWindow(self.app)
            settings_win.set_transient_for(self)
            settings_win.present()
        except Exception as e:
            self.logger.error(f"Failed to open settings window: {e}", exc_info=True)

    def on_rescan_library(self):
        """Rescans the library in a background thread to prevent UI freezing."""
        self._run_background_library_task(
            self.app.rescan_library,
            "Scan error",
        )

    def on_refresh_metadata(self):
        """Refresh cached metadata for registered tracks in a background thread."""
        self._run_background_library_task(
            self.app.refresh_track_metadata,
            "Metadata refresh error",
        )

    def _run_background_library_task(self, task_fn, error_prefix: str):
        """Runs a DB-heavy library task in a background thread."""
        self.rescan_button.set_sensitive(False)
        self.metadata_button.set_sensitive(False)
        
        # Stop UI timers to prevent "Unable to open database" errors during heavy scan
        if hasattr(self, '_status_timer_id'):
            GLib.source_remove(self._status_timer_id)
        if hasattr(self, '_progress_timer_id'):
            GLib.source_remove(self._progress_timer_id)

        def run_scan():
            """Run the library task in a separate thread and update the UI when done."""
            try:
                # Use a separate database instance for the scan thread to avoid contention
                scan_db = self.app.create_new_db_instance()
                try:
                    task_fn(db_instance=scan_db)
                finally:
                    scan_db.close()
                # Schedule UI updates back on the main thread
                GLib.idle_add(self.post_scan_update)
            except Exception as e:
                GLib.idle_add(lambda: self.playback_panel.error_label.set_text(f"{error_prefix}: {str(e)}"))
            finally:
                GLib.idle_add(lambda: self.rescan_button.set_sensitive(True))
                GLib.idle_add(lambda: self.metadata_button.set_sensitive(True))

        threading.Thread(target=run_scan, daemon=True).start()

    def post_scan_update(self):
        """Update the UI after a library scan completes."""
        self.library_panel.refresh_library_display()
        self.refresh_status()
        # Restart timers now that the database is free
        self._status_timer_id = GLib.timeout_add(1000, self.refresh_status)
        self._progress_timer_id = GLib.timeout_add(250, self.update_progress)
        return False

    def update_track(self, track: Track | None):
        """Update the track label with the currently playing track."""
        new_id = track.id if track else None
        
        # Optimization: Only update UI if the track has actually changed
        if new_id == self.current_track_id:
            return

        self.current_track_id = new_id
        if track:
            text = f"Now playing: {track.artist} - {track.title}"
            self._update_label(self.playback_panel.track_label, text)
            new_title = f"{track.artist} - {track.title} ~ {self.BASE_TITLE}"
            if self.get_title() != new_title:
                self.set_title(new_title)
            # Trigger a refresh of the recently played list when the track changes
            self.library_panel.refresh_recently_played_display()
        else:
            self.current_track_id = None
            self._update_label(self.playback_panel.track_label, "No track playing")
            self.set_title(self.BASE_TITLE)

    def refresh_queue(self):
        """Bridge method for panels to trigger a queue refresh."""
        self.queue_panel.refresh_queue_display()
        return True

        
    def _update_label(self, label_widget: Gtk.Label, text: str):
        """Update a label only if the text has changed to prevent layout churn."""
        if label_widget.get_text() != text:
            label_widget.set_text(text)

    def refresh_status(self):
        """Refresh the status bar and delegate updates to panels."""
        status = self.app.get_status()
        last_scan_at = status["last_scan_at"]
        scan = status["last_scan_result"]

        self._update_label(self.status_slot_label, f"Slot: {status['slot']}")
        self._update_label(
            self.status_library_label,
            f"Library: {status['library_count']} tracks, "
            f"RG: {status['replaygain_count']}"
        )
        self._update_label(self.status_queue_label, 
            f"Queue: {status['manual_count']} manual, {status['auto_count']} auto"
        )
        self._update_label(self.status_playback_label, f"Playback: {status['playback_state']}")

        # Delegate playback-specific info to the playback panel
        self.playback_panel.update_playback_info(status)
        self.update_track(status["current_track"])

        if last_scan_at:
            self._update_label(self.status_scan_label,
                f"Last scan: {last_scan_at.strftime('%H:%M:%S')} "
                f"({scan.scanned_files} files, {scan.stale_tracks_removed} stale, "
                f"{scan.metadata_failures} metadata issues)"
            )
        else:
            self._update_label(self.status_scan_label, "Last scan: never")

        return True

    def _render_list(self, listbox, tracks, selectable=False):
        """
        Render a list of tracks in the given ListBox, optimizing by updating existing rows.
        """
        track_ids = [t.id for t in tracks]
        state = (track_ids, self.current_track_id if not selectable else None)
        
        if getattr(listbox, "_last_rendered_state", None) == state:
            return
        
        listbox._last_rendered_state = state

        # Optimization: Reuse existing rows instead of clearing everything for the listbox
        current_rows = []
        child = listbox.get_first_child()
        while child:
            current_rows.append(child)
            child = child.get_next_sibling()

        # Match counts: Remove excess or add missing
        # This ensures the listbox only has the necessary number of rows
        while len(current_rows) > len(tracks):
            row_to_remove = current_rows.pop()
            listbox.remove(row_to_remove)

        target_row = None

        for index, track in enumerate(tracks):
            # Use the track's title, falling back to filename stem if title is empty
            text = f"{track.artist or 'Unknown'} - {track.title or track.path.stem}"
            
            if index < len(current_rows):
                row = current_rows[index]
                label = row.get_child()
                if label.get_text() != text:
                    label.set_use_markup(False)
                    label.set_text(text)
            else:
                row = Gtk.ListBoxRow()
                label = Gtk.Label(
                    label=text,
                    xalign=0,
                    hexpand=True,
                    use_markup=False,
                    ellipsize=Pango.EllipsizeMode.END,
                    max_width_chars=80,
                    width_chars=20
                )
                row.set_child(label)
                listbox.append(row)

            row.track_id = track.id  # attach metadata
            row.track = track
            row.queue_position = index
            
            # Apply 'playing' CSS class if this is the currently playing track
            if not selectable and self.current_track_id == track.id:
                if not row.has_css_class("playing"):
                    row.add_css_class("playing")
                target_row = row
            # Remove 'playing' CSS class if it's not the current track
            elif row.has_css_class("playing"):
                row.remove_css_class("playing")

        # Scroll to playing row
        if target_row:
            listbox.select_row(target_row)
            listbox.activate_row(target_row)

            adj = listbox.get_parent().get_vadjustment()
            if adj:
                def scroll_to_row():
                    alloc = target_row.get_allocation()
                    # Only scroll if allocation is actually calculated (prevents layout churn)
                    if alloc.height > 0:
                        adj.set_value(alloc.y)
                    return False
                GLib.idle_add(scroll_to_row)

    # -------------------------
    # Actions
    # -------------------------
    # UI updates

    def update_progress(self):
        """Delegate progress bar updates to the playback panel."""
        self.playback_panel.update_progress_bar()
        return True

    def on_close_request(self, _window):
        """Handle application shutdown, ensuring state is persisted and backend threads are stopped."""
        # Stop UI timers to clear the GLib main context
        if hasattr(self, '_status_timer_id'):
            GLib.source_remove(self._status_timer_id)
        if hasattr(self, '_progress_timer_id'):
            GLib.source_remove(self._progress_timer_id)

        self.app.persist_state()
        self.app.app.stop() # Properly shut down backend threads on exit
        self.get_application().quit() # Force the GTK loop to exit
        return False

    def persist_playback_state(self):
        """Persist playback state periodically to ensure we don't lose progress on crashes."""
        self.app.persist_state()
        return True

    def _format_time(self, nanoseconds: int) -> str:
        """Convert nanoseconds to a human-readable time format."""
        total_seconds = max(0, int(nanoseconds / 1_000_000_000))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"

        return f"{minutes}:{seconds:02d}"
