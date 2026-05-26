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

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Horizontal box for playback controls
        self.playback_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.playback_controls.set_homogeneous(True)
        self.append(self.playback_controls)

        self.error_label = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.END, max_width_chars=50)
        self.error_label.set_wrap(True)
        self.append(self.error_label)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,1,1)
        self.seek.set_draw_value(False)
        self.append(self.seek)
        self.seek.connect("value-changed", self.on_seek)

        self.time_label = Gtk.Label(label="0:00 / 0:00")
        self.append(self.time_label)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # VU Meter
        self.vu_meter_label = self.create_label("VU Meter / Volume")
        self.append(self.vu_meter_label)

        # Mixer-style side-by-side vertical VU meters with a central dB scale
        self.vu_meter_grid = Gtk.Grid()
        self.vu_meter_grid.set_column_spacing(10)
        self.vu_meter_grid.set_row_spacing(4)
        self.vu_meter_grid.set_halign(Gtk.Align.CENTER)
        self.append(self.vu_meter_grid)

        self.vu_meter_left = Gtk.ProgressBar(orientation=Gtk.Orientation.VERTICAL, inverted=True)
        self.vu_meter_left.set_fraction(0.0)
        self.vu_meter_left.add_css_class("vu-meter")
        self.vu_meter_left.set_vexpand(True)
        self.vu_meter_grid.attach(self.vu_meter_left, 0, 0, 1, 1)

        # Central dB Scale Column
        scale_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for db_val in ["0", "-12", "-24", "-36", "-48", "-60"]:
            lbl = self.create_label(db_val, max_chars=3, xalign=0.5, css_class="vu-scale-label")
            lbl.set_vexpand(True)
            scale_box.append(lbl)
        self.vu_meter_grid.attach(scale_box, 1, 0, 1, 1)

        self.vu_meter_right = Gtk.ProgressBar(orientation=Gtk.Orientation.VERTICAL, inverted=True)
        self.vu_meter_right.set_fraction(0.0)
        self.vu_meter_right.add_css_class("vu-meter")
        self.vu_meter_right.set_vexpand(True)
        self.vu_meter_grid.attach(self.vu_meter_right, 2, 0, 1, 1)

        # Channel indicators below the meters
        self.vu_meter_grid.attach(self.create_label("L", xalign=0.5), 0, 1, 1, 1)
        self.vu_meter_grid.attach(self.create_label("R", xalign=0.5), 2, 1, 1, 1)

        # Vertical Separator between VU and Volume
        v_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        v_sep.set_margin_start(6)
        v_sep.set_margin_end(6)
        self.vu_meter_grid.attach(v_sep, 3, 0, 1, 1)

        # Vertical Volume Slider (Fader)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
        self.volume.set_inverted(True) # 100 at top, 0 at bottom
        self.volume.set_draw_value(False)
        self.volume.set_vexpand(True)
        self.volume.add_css_class("volume-fader")
        
        initial_volume_percent = round(self.app.get_volume() * 100)
        self.volume.set_value(max(0, min(100, initial_volume_percent)))
        self.volume.connect("value-changed", self.on_volume_changed)
        
        self.vu_meter_grid.attach(self.volume, 4, 0, 1, 1)
        self.volume_indicator = self.create_label("Vol", xalign=0.5)
        self.vu_meter_grid.attach(self.volume_indicator, 4, 1, 1, 1)

        # Apply custom styling for the gradient
        self._setup_vu_meter_style()

        self.play_button = self.create_button(
            icon_name="media-playback-start",
            tooltip="Play or Resume",
            callback=lambda _: self.app.play_or_resume()
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
            callback=lambda _: self.app.stop()
        )
        self.playback_controls.append(self.stop_button)

        self.next_button = self.create_button(
            icon_name="media-skip-forward",
            tooltip="Next",
            callback=lambda _: self.app.skip()
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
            background-image: linear-gradient(to top, #2ecc71 0%, #2ecc71 65%, #f1c40f 85%, #e74c3c 100%);
            border-radius: 2px;
        }
        .vu-meter trough {
            min-width: 14px;
            min-height: 80px;
            background-color: rgba(255, 255, 255, 0.05);
            border-radius: 2px;
        }
        .volume-fader trough {
            min-width: 14px;
            min-height: 80px;
        }
        .volume-fader slider {
            border-radius: 0; /* Makes the slider handle rectangular */
        }
        .vu-scale-label {
            font-size: 0.65rem;
            color: rgba(255, 255, 255, 0.4);
            font-family: monospace;
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

    def on_pause_resume(self, _button):
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
