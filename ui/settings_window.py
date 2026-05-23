from gi.repository import Gtk
import logging
import config

logger = logging.getLogger(__name__)

class SettingsWindow(Gtk.Window):
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

        # General Settings List
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        content_box.append(list_box)

        # Editable fields
        self.base_folder_entry = self._add_entry_row(list_box, "Music Library Path", self.config.get("base_folder", ""))
        self.db_path_entry = self._add_entry_row(list_box, "Database SQLite Path", self.config.get("db_path", ""))
        self.db_path_entry.set_sensitive(False)
        self.db_path_entry.set_tooltip_text("Changing the database path requires restarting the application.")
        self.daily_folder_entry = self._add_entry_row(list_box, "Daily Folder", self.config.get("daily_folder", ""))
        
        self.duration_spin = Gtk.SpinButton.new_with_range(30, 900, 1)
        self.duration_spin.set_value(float(self.config.get("average_track_duration_seconds", 210)))
        self._add_widget_row(list_box, "Avg Duration (sec)", self.duration_spin)

        # Timeslots Section
        ts_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ts_label = Gtk.Label(label="Timeslots")
        ts_label.add_css_class("title-4")
        ts_header.append(ts_label)
        
        add_ts_btn = Gtk.Button(label="Add Slot")
        add_ts_btn.connect("clicked", lambda _: self._add_timeslot_ui())
        ts_header.append(add_ts_btn)
        content_box.append(ts_header)

        self.timeslots_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.append(self.timeslots_container)

        for slot in self.config.get("timeslots", []):
            self._add_timeslot_ui(slot)

        # Action buttons
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_halign(Gtk.Align.END)
        main_box.append(actions)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())
        actions.append(cancel_btn)

        save_btn = Gtk.Button(label="Save & Apply")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save_clicked)
        actions.append(save_btn)

    def _add_entry_row(self, listbox, label, value):
        entry = Gtk.Entry()
        entry.set_text(str(value))
        entry.set_hexpand(True)
        self._add_widget_row(listbox, label, entry)
        return entry

    def _add_widget_row(self, listbox, label_text, widget):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(12)
        hbox.set_margin_end(12)
        
        label = Gtk.Label(label=label_text, xalign=0)
        hbox.append(label)
        
        widget.set_halign(Gtk.Align.END)
        hbox.append(widget)
        
        row.set_child(hbox)
        listbox.append(row)

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
        name_entry.set_hexpand(True)
        top_row.append(name_entry)
        
        del_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        top_row.append(del_btn)
        inner_box.append(top_row)

        # Row 2: Times
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        start_entry = Gtk.Entry()
        start_entry.set_text(slot_data.get("start", "00:00"))
        start_entry.set_placeholder_text("Start (HH:MM)")
        end_entry = Gtk.Entry()
        end_entry.set_text(slot_data.get("end", "00:00"))
        end_entry.set_placeholder_text("End (HH:MM)")
        time_row.append(Gtk.Label(label="From:"))
        time_row.append(start_entry)
        time_row.append(Gtk.Label(label="To:"))
        time_row.append(end_entry)
        inner_box.append(time_row)

        # Row 3: Folders
        folders_str = ", ".join(slot_data.get("folders", []))
        folders_entry = Gtk.Entry()
        folders_entry.set_text(folders_str)
        folders_entry.set_placeholder_text("Folders (comma separated)")
        inner_box.append(Gtk.Label(label="Folders:", xalign=0))
        inner_box.append(folders_entry)

        iter_folder = slot_data.get("each_iteration_folder", "NOT_IN_USE")
        iter_entry = Gtk.Entry()
        iter_entry.set_text(iter_folder)
        iter_entry.set_placeholder_text("Iteration Folder")
        inner_box.append(Gtk.Label(label="Once-per-cycle Folder:", xalign=0))
        inner_box.append(iter_entry)

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
