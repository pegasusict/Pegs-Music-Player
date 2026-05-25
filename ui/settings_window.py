import copy
import logging
from pathlib import Path

from gi.repository import Gtk

import config
from ui.ui_helpers import UIHelpersMixin

logger = logging.getLogger(__name__)

class SettingsWindow(Gtk.Window, UIHelpersMixin):
    def __init__(self, controller):
        super().__init__(title="Settings", modal=True)
        self.controller = controller
        self.set_default_size(500, 450)

        # Load current config directly from the source
        self.config = self.controller.app.get_raw_config()
        self.timeslot_widgets = []

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(18)
        main_box.set_margin_bottom(18)
        main_box.set_margin_start(18)
        main_box.set_margin_end(18)
        self.set_child(main_box)

        # Error Display Area
        self.error_label = Gtk.Label()
        self.error_label.set_use_markup(True)
        self.error_label.set_visible(False)
        main_box.append(self.error_label)

        # Scrollable area for all settings
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        main_box.append(scroll)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        scroll.set_child(content_box)

        # Library & General Section
        content_box.append(self.create_label("Library & General", css_class="title-4", xalign=0))

        # General Settings List
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        content_box.append(list_box)

        # Editable fields
        self.base_folder_entry = self._add_path_row(
            list_box, "Music Library Path", self.config.get("base_folder", ""),
            tooltip="The root directory where your music is stored. Subfolders in timeslots are relative to this path."
        )
        self.db_path_entry = self._add_entry_row(
            list_box, "Database SQLite Path", self.config.get("db_path", ""),
            tooltip="The location of the application database. This cannot be changed while the app is running."
        )
        self.db_path_entry.set_sensitive(False)
        
        self.daily_folder_entry = self._add_path_row(
            list_box, "Daily Folder", self.config.get("daily_folder", ""),
            tooltip="Folder containing tracks for daily events (e.g., jingles). Relative to the Music Library Path."
        )
        
        self.duration_spin = Gtk.SpinButton.new_with_range(30, 900, 1)
        self.duration_spin.set_value(float(self.config.get("average_track_duration_seconds", 210)))
        self._add_widget_row(
            list_box, "Avg Duration (sec)", self.duration_spin,
            tooltip="Fallback duration used for queue planning when a file's actual duration cannot be read from metadata.")

        # Playback Section
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        content_box.append(self.create_label("Playback", css_class="title-4", xalign=0))
        
        playback_list = Gtk.ListBox()
        playback_list.set_selection_mode(Gtk.SelectionMode.NONE)
        playback_list.add_css_class("boxed-list")
        content_box.append(playback_list)

        self.crossfade_spin = Gtk.SpinButton.new_with_range(0, 10, 0.1)
        self.crossfade_spin.set_value(float(self.config.get("crossfade_seconds", 3.5)))
        self._add_widget_row(playback_list, "Crossfade (sec)", self.crossfade_spin,
                            tooltip="Duration of crossfade between consecutive tracks.")

        self.ui_fade_spin = Gtk.SpinButton.new_with_range(0, 5, 0.05)
        self.ui_fade_spin.set_value(float(self.config.get("ui_fade_seconds", 0.25)))
        self._add_widget_row(playback_list, "UI Fade (sec)", self.ui_fade_spin,
                            tooltip="Duration of fades when pausing, stopping, or resuming.")

        # Compressor Section
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        content_box.append(self.create_label("Dynamic Compression (SC4)", css_class="title-4", xalign=0))
        
        comp_list = Gtk.ListBox()
        comp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        comp_list.add_css_class("boxed-list")
        content_box.append(comp_list)

        comp_cfg = self.config.get("compressor", {})
        
        self.comp_threshold_spin = Gtk.SpinButton.new_with_range(-60, 0, 1)
        self.comp_threshold_spin.set_value(float(comp_cfg.get("threshold_level", -20.0)))
        self._add_widget_row(comp_list, "Threshold (dB)", self.comp_threshold_spin, tooltip="Level at which compression starts.")

        self.comp_ratio_spin = Gtk.SpinButton.new_with_range(1, 20, 0.5)
        self.comp_ratio_spin.set_value(float(comp_cfg.get("ratio", 4.0)))
        self._add_widget_row(comp_list, "Ratio (n:1)", self.comp_ratio_spin, tooltip="Amount of compression applied above threshold.")

        self.comp_attack_spin = Gtk.SpinButton.new_with_range(0.1, 100, 0.5)
        self.comp_attack_spin.set_value(float(comp_cfg.get("attack_time", 1.5)))
        self._add_widget_row(comp_list, "Attack (ms)", self.comp_attack_spin, tooltip="How fast the compressor reacts.")

        self.comp_release_spin = Gtk.SpinButton.new_with_range(1, 500, 5)
        self.comp_release_spin.set_value(float(comp_cfg.get("release_time", 32.5)))
        self._add_widget_row(comp_list, "Release (ms)", self.comp_release_spin, tooltip="How fast the compressor recovers.")

        self.comp_gain_spin = Gtk.SpinButton.new_with_range(0, 24, 1)
        self.comp_gain_spin.set_value(float(comp_cfg.get("makeup_gain", 0.0)))
        self._add_widget_row(comp_list, "Makeup Gain (dB)", self.comp_gain_spin, tooltip="Boost the signal after compression.")

        # Separator
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Logging Section
        content_box.append(self.create_label("Logging", css_class="title-4", xalign=0))

        log_list = Gtk.ListBox()
        log_list.set_selection_mode(Gtk.SelectionMode.NONE)
        log_list.add_css_class("boxed-list")
        content_box.append(log_list)

        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.log_level_combo = Gtk.ComboBoxText()
        for lvl in levels:
            self.log_level_combo.append_text(lvl)
        current_lvl = self.config.get("logging", {}).get("level", "INFO")
        self.log_level_combo.set_active(levels.index(current_lvl) if current_lvl in levels else 1)
        self._add_widget_row(
            log_list, "Log Level", self.log_level_combo,
            tooltip="Controls the verbosity of the logs. DEBUG is the most detailed."
        )

        self.log_file_entry = self._add_entry_row(
            log_list, "Log File Path", self.config.get("logging", {}).get("file", ""),
            tooltip="Path to the log file. Absolute paths are used as-is; relative paths are stored in the user cache."
        )

        # Separator
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Timeslots Section
        ts_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ts_header.append(self.create_label("Timeslots", css_class="title-4", xalign=0))
        
        ts_header.append(self.create_button("Add Slot", callback=lambda _: self._add_timeslot_ui()))
        content_box.append(ts_header)

        self.timeslots_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.append(self.timeslots_container)

        for slot in self.config.get("timeslots", []):
            self._add_timeslot_ui(slot)

        # Action buttons
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_box.append(actions)

        actions.append(self.create_button("Reset to Defaults", css_class="destructive-action", callback=self.on_reset_clicked))

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        actions.append(spacer)

        actions.append(self.create_button("Cancel", callback=lambda _: self.close()))

        actions.append(self.create_button("Save & Apply", css_class="suggested-action", callback=self.on_save_clicked))

    def _add_entry_row(self, listbox, label, value, tooltip=None):
        entry = Gtk.Entry()
        entry.set_text(str(value))
        entry.set_hexpand(True)
        if tooltip:
            entry.set_tooltip_text(tooltip)
        self._add_widget_row(listbox, label, entry, tooltip)
        return entry

    def _add_widget_row(self, listbox, label_text, widget, tooltip=None):
        """Helper to add a standard widget row to a ListBox."""
        row = self.create_list_row(label_text, widget, tooltip)
        listbox.append(row)

    def _create_path_input(self, value, append=False, tooltip=None):
        """Returns a Gtk.Box containing an Entry and a Browse button."""
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_hexpand(True)

        entry = Gtk.Entry()
        entry.set_text(str(value))
        if tooltip:
            entry.set_tooltip_text(tooltip)
        entry.set_hexpand(True)
        hbox.append(entry)

        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.set_tooltip_text("Browse folder...")
        browse_btn.connect("clicked", self._on_browse_folder, entry, append)
        hbox.append(browse_btn)

        return hbox, entry

    def _add_path_row(self, listbox, label, value, tooltip=None):
        """Helper to create a ListBox row with an Entry and a Browse button."""
        hbox, entry = self._create_path_input(value, tooltip=tooltip)
        row = self.create_list_row(label, hbox, tooltip=tooltip, widget_halign=Gtk.Align.FILL)
        listbox.append(row)
        return entry

    def _on_browse_folder(self, _btn, entry, append=False):
        """Opens a native folder selection dialog and updates the provided entry.
        If append is True, adds the folder to a comma-separated list.
        Attempts to make paths relative to the Library Path."""
        native = Gtk.FileChooserNative.new(
            "Select Folder", self, Gtk.FileChooserAction.SELECT_FOLDER, "_Select", "_Cancel"
        )
        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    path_str = file.get_path()
                    
                    # Try to make path relative to Library Path
                    base_path = self.base_folder_entry.get_text()
                    if base_path:
                        try:
                            abs_base = Path(base_path).expanduser().resolve()
                            abs_path = Path(path_str).expanduser().resolve()
                            if abs_path.is_relative_to(abs_base):
                                path_str = str(abs_path.relative_to(abs_base))
                        except (ValueError, Exception):
                            pass

                    if append:
                        current = [s.strip() for s in entry.get_text().split(",") if s.strip()]
                        if path_str not in current:
                            current.append(path_str)
                        entry.set_text(", ".join(current))
                    else:
                        entry.set_text(path_str)
            dialog.destroy()
        native.connect("response", on_response)
        native.show()

    def _add_timeslot_ui(self, slot_data=None):
        """Adds a UI block for a single timeslot."""
        if slot_data is None:
            slot_data = {"name": "new_slot", "start": "00:00", "end": "00:00", "folders": [], "each_iteration_folder": "NOT_IN_USE"}

        frame = Gtk.Frame()
        inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner_box.set_margin_top(10)
        inner_box.set_margin_bottom(10)
        inner_box.set_margin_start(10)
        inner_box.set_margin_end(10)
        frame.set_child(inner_box)

        # Row 1: Name and Delete
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        name_entry = Gtk.Entry()
        name_entry.set_text(slot_data.get("name", "new_slot"))
        name_entry.set_placeholder_text("Slot Name")
        name_entry.set_tooltip_text("A unique identifier for this timeslot.")
        name_entry.set_hexpand(True)
        top_row.append(name_entry)
        
        del_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        del_btn.set_tooltip_text("Remove this timeslot.")
        top_row.append(del_btn)
        inner_box.append(top_row)

        # Row 2: Times
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        start_entry = Gtk.Entry()
        start_entry.set_text(slot_data.get("start", "00:00"))
        start_entry.set_placeholder_text("Start (HH:MM)")
        start_entry.set_tooltip_text("Format: HH:MM. The time this slot begins.")
        end_entry = Gtk.Entry()
        end_entry.set_text(slot_data.get("end", "00:00"))
        end_entry.set_placeholder_text("End (HH:MM)")
        end_entry.set_tooltip_text("Format: HH:MM. The time this slot ends.")
        time_row.append(Gtk.Label(label="From:"))
        time_row.append(start_entry)
        time_row.append(Gtk.Label(label="To:"))
        time_row.append(end_entry)
        inner_box.append(time_row)

        # Row 3: Folders (Multi-select via browse button)
        inner_box.append(Gtk.Label(label="Folders:", xalign=0))
        folders_hbox, folders_entry = self._create_path_input(
            ", ".join(slot_data.get("folders", [])), append=True,
            tooltip="Subfolders (inside the Library Path) to pull tracks from. Separate multiple with commas."
        )
        folders_entry.set_placeholder_text("Folders (comma separated)")
        inner_box.append(folders_hbox)

        inner_box.append(Gtk.Label(label="Once-per-cycle Folder:", xalign=0))
        iter_hbox, iter_entry = self._create_path_input(
            slot_data.get("each_iteration_folder", "NOT_IN_USE"), append=False,
            tooltip="Tracks in this folder play exactly once per cycle through the timeslot. Set to 'NOT_IN_USE' to disable."
        )
        iter_entry.set_placeholder_text("Iteration Folder")
        inner_box.append(iter_hbox)

        # Connect delete button now that entries are created
        del_btn.connect("clicked", lambda _: self._remove_timeslot_ui(frame, widgets))

        widgets = {
            "name": name_entry, "start": start_entry, "end": end_entry,
            "folders": folders_entry, "iter": iter_entry, "frame": frame
        }
        self.timeslot_widgets.append(widgets)
        self.timeslots_container.append(frame)

    def _remove_timeslot_ui(self, frame, widgets):
        self.timeslots_container.remove(frame)
        self.timeslot_widgets.remove(widgets)

    def on_save_clicked(self, _btn):
        # Update local config dict
        self.config["base_folder"] = self.base_folder_entry.get_text()
        self.config["db_path"] = self.db_path_entry.get_text()
        self.config["daily_folder"] = self.daily_folder_entry.get_text()
        self.config["average_track_duration_seconds"] = int(self.duration_spin.get_value())
        self.config["crossfade_seconds"] = float(self.crossfade_spin.get_value())
        self.config["ui_fade_seconds"] = float(self.ui_fade_spin.get_value())
        self.config["compressor"] = {
            "rms_peak": 0.0, # Kept at 0.0 default
            "attack_time": float(self.comp_attack_spin.get_value()),
            "release_time": float(self.comp_release_spin.get_value()),
            "threshold_level": float(self.comp_threshold_spin.get_value()),
            "ratio": float(self.comp_ratio_spin.get_value()),
            "knee_radius": 2.0, # Kept at 2.0 default
            "makeup_gain": float(self.comp_gain_spin.get_value()),
        }
        self.config["logging"] = {
            "level": self.log_level_combo.get_active_text(),
            "file": self.log_file_entry.get_text()
        }
        
        # Gather timeslots
        new_timeslots = []
        for w in self.timeslot_widgets:
            folders = [f.strip() for f in w["folders"].get_text().split(",") if f.strip()]
            new_timeslots.append({
                "name": w["name"].get_text(),
                "start": w["start"].get_text(),
                "end": w["end"].get_text(),
                "folders": folders,
                "each_iteration_folder": w["iter"].get_text()
            })
        self.config["timeslots"] = new_timeslots

        # Validation Check
        errors = config.verify_timeslot_continuity(new_timeslots)
        if errors:
            error_text = "<b>Cannot save settings:</b>\n" + "\n".join(f"• {e}" for e in errors)
            self.error_label.set_markup(f"<span foreground='red'>{error_text}</span>")
            self.error_label.set_visible(True)
            return
        
        # Pass to backend to save and apply
        self.controller.app.apply_config(self.config)
        self.close()

    def on_reset_clicked(self, _btn):
        """Shows a confirmation dialog before resetting settings."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Reset settings to defaults?",
        )
        dialog.format_secondary_text(
            "This will revert all fields in this window to factory values. "
            "Note: Changes are not saved until you click 'Save & Apply'."
        )

        def on_response(msg_dialog, response_id):
            if response_id == Gtk.ResponseType.OK:
                self._perform_reset()
            msg_dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def _perform_reset(self):
        """Internal method to perform the actual UI reset."""
        logger.info("Resetting settings UI to defaults.")
        # Use a deep copy to ensure we don't accidentally modify the module-level constant
        defaults = copy.deepcopy(config.DEFAULT_CONFIG_SCHEMA)

        # Update basic entries
        self.base_folder_entry.set_text(str(defaults.get("base_folder", "")))
        self.db_path_entry.set_text(str(defaults.get("db_path", "")))
        self.daily_folder_entry.set_text(str(defaults.get("daily_folder", "")))
        self.duration_spin.set_value(float(defaults.get("average_track_duration_seconds", 210)))
        self.crossfade_spin.set_value(float(defaults.get("crossfade_seconds", 3.5)))
        self.ui_fade_spin.set_value(float(defaults.get("ui_fade_seconds", 0.25)))

        comp_defaults = defaults.get("compressor", {})
        self.comp_threshold_spin.set_value(float(comp_defaults.get("threshold_level", -20.0)))
        self.comp_ratio_spin.set_value(float(comp_defaults.get("ratio", 4.0)))
        self.comp_attack_spin.set_value(float(comp_defaults.get("attack_time", 1.5)))
        self.comp_release_spin.set_value(float(comp_defaults.get("release_time", 32.5)))
        self.comp_gain_spin.set_value(float(comp_defaults.get("makeup_gain", 0.0)))

        # Update logging
        log_cfg = defaults.get("logging", {})
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        lvl = log_cfg.get("level", "INFO")
        self.log_level_combo.set_active(levels.index(lvl) if lvl in levels else 1)
        self.log_file_entry.set_text(str(log_cfg.get("file", "")))

        # Clear existing timeslot widgets
        while self.timeslot_widgets:
            w = self.timeslot_widgets[0]
            self._remove_timeslot_ui(w["frame"], w)

        # Re-populate default timeslots
        for slot in defaults.get("timeslots", []):
            self._add_timeslot_ui(slot)

        # Clear any validation errors
        self.error_label.set_visible(False)
