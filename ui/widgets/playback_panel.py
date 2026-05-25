# ui/widgets/playback_panel.py

from gi.repository import Gtk, GLib, Pango, Gdk
from domain.track import Track
from ui.player_controller import PlayerController
from ui.ui_helpers import UIHelpersMixin

class PlaybackPanel(Gtk.Box, UIHelpersMixin):
    def __init__(self, app_controller: PlayerController, main_window: Gtk.Window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app_controller
        self.main_window = main_window # Reference to the main window for shared methods

        self.track_label = Gtk.Label(label="No track playing", ellipsize=Pango.EllipsizeMode.END, max_width_chars=50)
        self.append(self.track_label)

        self.resume_last_button = Gtk.Button(label="Resume last track")
        self.resume_last_button.connect("clicked", lambda _: self.on_resume_last_track())
        self.append(self.resume_last_button)

        # Horizontal box for playback controls
        self.playback_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.playback_controls.set_homogeneous(True)
        self.append(self.playback_controls)

        self.error_label = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.END, max_width_chars=50)
        self.error_label.set_wrap(True)
        self.append(self.error_label)

        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,1,1)
        self.seek.set_draw_value(False)
        self.append(self.seek)
        self.seek.connect("value-changed", self.on_seek)

        self.time_label = Gtk.Label(label="0:00 / 0:00")
        self.append(self.time_label)

        self.volume_label = self.create_label("Volume")
        self.append(self.volume_label)

        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        initial_volume_percent = round(self.app.get_volume() * 100)
        self.volume.set_value(max(0, min(100, initial_volume_percent)))
        self.volume.connect("value-changed", self.on_volume_changed)
        self.append(self.volume)
        
        # VU Meter
        self.vu_meter_label = self.create_label("VU Meter")
        self.append(self.vu_meter_label)

        self.vu_meter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(self.vu_meter_box)

        self.vu_meter_left = Gtk.ProgressBar()
        self.vu_meter_left.set_fraction(0.0)
        self.vu_meter_left.add_css_class("vu-meter")
        self.vu_meter_left.set_hexpand(True)
        self.vu_meter_box.append(self.vu_meter_left)

        self.vu_meter_right = Gtk.ProgressBar()
        self.vu_meter_right.set_fraction(0.0)
        self.vu_meter_right.add_css_class("vu-meter")
        self.vu_meter_right.set_hexpand(True)
        self.vu_meter_box.append(self.vu_meter_right)

        # Apply custom styling for the gradient
        self._setup_vu_meter_style()

        self.play_button = self.create_button(
            icon_name="media-playback-start",
            tooltip="Play or Resume",
            callback=self.play_or_resume
        )
        self.playback_controls.append(self.play_button)

        self.pause_button = self.create_button(
            icon_name="media-playback-pause",
            tooltip="Pause or Resume",
            callback=self.on_pause_resume
        )
        self.playback_controls.append(self.pause_button)

        self.stop_button = self.create_button(
            icon_name="media-playback-stop",
            tooltip="Stop",
            callback=self.stop
        )
        self.playback_controls.append(self.stop_button)

        self.next_button = self.create_button(
            icon_name="media-playback-next",
            tooltip="Next",
            callback=self.on_next
        )
        self.playback_controls.append(self.next_button)

        # Shuffle button
        self.shuffle_button = self.create_button(
            icon_name="media-playlist-shuffle", 
            tooltip="Toggle Shuffle", 
            callback=self.on_shuffle_button_clicked
        )
        self.playback_controls.append(self.shuffle_button) # Add to playback controls

        # Stop at end button
        self.stop_at_end_button = self.create_button(
            icon_name="media-playback-stop",
            tooltip="Stop after current track",
            callback=self.on_stop_at_end_button_clicked
        )
        self.playback_controls.append(self.stop_at_end_button)

        # Connect VU meter callback
        self.app.set_vu_meter_ui_callback(self._on_vu_meter_update)

    def _setup_vu_meter_style(self):
        """Applies a linear gradient to the VU meter progress nodes."""
        css_provider = Gtk.CssProvider()
        css_data = """
        .vu-meter progress {
            background-image: linear-gradient(to right, #2ecc71 0%, #2ecc71 70%, #f1c40f 85%, #e74c3c 100%);
            border-radius: 2px;
        }
        .vu-meter trough {
            min-height: 10px;
            background-color: rgba(255, 255, 255, 0.05);
            border-radius: 2px;
        }
        """
        css_provider.load_from_data(css_data.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ---------------------------------------------------------
    # Playback actions
    # ---------------------------------------------------------

    def on_next(self):
        """Skip to the next track."""
        track = self.app.skip()
        self.main_window.update_track(track) # Call main_window to update global track info

    def on_pause_resume(self):
        """Toggle between pause and resume based on current playback state."""
        status = self.app.get_status()

        if status.get("playback_state") == "paused":
            self.app.resume()
        else:
            self.app.pause()

        self.main_window.refresh_status() # Call main_window to refresh status bar

    def on_resume_last_track(self):
        """Resume the last track if available."""
        track = self.app.resume_last_track()
        self.main_window.update_track(track)
        self.main_window.refresh_status()

    def on_seek(self, scale):
        """Seek to a new position in the current track."""
        value = int(scale.get_value())
        self.app.seek(value)

    def on_volume_changed(self, scale):
        """Change the playback volume."""
        self.app.set_volume(scale.get_value() / 100)

    def _on_vu_meter_update(self, peak_levels: list[float], rms_levels: list[float]):
        """Callback to update the VU meter UI."""
        if len(peak_levels) >= 2:
            self.vu_meter_left.set_fraction(peak_levels[0])
            self.vu_meter_right.set_fraction(peak_levels[1])
        elif len(peak_levels) == 1: # Mono case
            self.vu_meter_left.set_fraction(peak_levels[0])
            self.vu_meter_right.set_fraction(peak_levels[0])
    def on_shuffle_button_clicked(self, button):
        """Toggle shuffle mode on or off."""
        self.app.set_shuffle_enabled(not self.app.get_shuffle_enabled())

    def on_stop_at_end_button_clicked(self, button):
        """Toggle stop at end mode on or off."""
        self.app.set_stop_at_end_enabled(not self.app.get_stop_at_end_enabled())

    # ---------------------------------------------------------
    # Update methods (called by MainWindow)
    # ---------------------------------------------------------

    def update_playback_info(self, status: dict):
        """Update the playback panel based on the current status."""
        new_pause_label = "▶" if status["playback_state"] == "paused" else "⏸"
        if self.pause_button.get_label() != new_pause_label:
            self.pause_button.set_label(new_pause_label)

        new_resume_visible = (bool(status["has_restorable_track"])
            and status["playback_state"] == "stopped"
        )
        if self.resume_last_button.get_visible() != new_resume_visible:
            self.resume_last_button.set_visible(new_resume_visible)

        error_text = f"Playback error: {status['last_error']}" if status.get("last_error") else ""
        self.update_label(self.error_label, error_text)
        self.error_label.set_visible(bool(error_text))

        # Update shuffle button appearance
        if status["shuffle_enabled"]:
            self.shuffle_button.add_css_class("suggested-action") # Highlight if active
            self.shuffle_button.set_tooltip_text("Shuffle: ON")
        else:
            self.shuffle_button.remove_css_class("suggested-action")
            self.shuffle_button.set_tooltip_text("Shuffle: OFF")

        # Update stop at end button appearance
        if status["stop_at_end_enabled"]:
            self.stop_at_end_button.add_css_class("suggested-action") # Highlight if active
            self.stop_at_end_button.set_tooltip_text("Stop after current track: ON")
        else:
            self.stop_at_end_button.remove_css_class("suggested-action")
            self.stop_at_end_button.set_tooltip_text("Stop after current track: OFF")


    def update_progress_bar(self):
        """Update the progress bar and time label based on current track position."""
        engine = self.app.engine
        duration = engine.get_duration()
        position = engine.get_position()

        if duration > 0 and position >= 0:
            new_time_text = (
                f"{self.format_time(position)} / {self.format_time(duration)} "
                f"(-{self.format_time(max(0, duration - position))})"
            )
            self.update_label(self.time_label, new_time_text)

            self.seek.handler_block_by_func(self.on_seek)
            # Only update range if it changed (new track)
            if abs(self.seek.get_adjustment().get_upper() - duration) > 1000:
                self.seek.set_range(0, duration)
            # Only update value if it's a significant move (to avoid constant layout hits)
            if abs(self.seek.get_value() - position) > 500_000_000: # 0.5 seconds
                self.seek.set_value(position)
            self.seek.handler_unblock_by_func(self.on_seek)
        else:
            # self.progress.set_fraction(0)
            self.time_label.set_text("0:00 / 0:00")
