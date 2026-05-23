# ui/widgets/library_panel.py

import threading
from gi.repository import Gtk, GLib
from domain.track import Track
from ui.player_controller import PlayerController

class LibraryPanel(Gtk.Box):
    def __init__(self, app_controller: PlayerController, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app_controller
        self.main_window = main_window # Reference to the main window for shared methods

        self.library_tracks: list[Track] = [] # Full list of tracks in the library
        self.recently_played_tracks: list[Track] = [] # List of recently played tracks

        # Stack switcher for Library / Recently Played views
        self.view_switcher = Gtk.StackSwitcher()
        self.append(self.view_switcher)

        # Stack to hold different views
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.view_switcher.set_stack(self.stack)
        self.append(self.stack)

        # --- Library View ---
        self.library_view_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stack.add_titled(self.library_view_box, "library_view", "Library")

        self.library_search = Gtk.SearchEntry()
        self.library_search.set_placeholder_text("Search tracks")
        self.library_search.connect("search-changed", lambda _: self.render_library_display())
        self.library_view_box.append(self.library_search)

        self.folder_filter = Gtk.ComboBoxText()
        self.folder_filter.append_text("All folders")
        self.folder_filter.set_active(0)
        self.folder_filter.connect("changed", lambda _: self.render_library_display())
        self.library_view_box.append(self.folder_filter)

        self.library_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.library_view_box.append(self.library_actions)

        self.add_manual_button = Gtk.Button(label="Add selected")
        self.add_manual_button.connect("clicked", lambda _: self.on_add_selected_tracks())
        self.library_actions.append(self.add_manual_button)

        self.play_next_button = Gtk.Button(label="Play next")
        self.play_next_button.connect("clicked", lambda _: self.on_play_next_selected_tracks())
        self.library_actions.append(self.play_next_button)

        self.library_scroll = Gtk.ScrolledWindow()
        self.library_scroll.set_vexpand(True)
        self.library_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.library_list = Gtk.ListBox()
        self.library_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.library_list.connect("row-activated", self.on_library_row_activated)
        self.library_scroll.set_child(self.library_list)
        self.library_view_box.append(self.library_scroll)

        # --- Recently Played View ---
        self.recently_played_view_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stack.add_titled(self.recently_played_view_box, "recently_played_view", "Recently Played")

        self.recently_played_scroll = Gtk.ScrolledWindow()
        self.recently_played_scroll.set_vexpand(True)
        self.recently_played_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.recently_played_list = Gtk.ListBox()
        self.recently_played_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.recently_played_list.connect("row-activated", self.on_library_row_activated) # Reuse the same handler
        self.recently_played_scroll.set_child(self.recently_played_list)
        self.recently_played_view_box.append(self.recently_played_scroll)

    # ---------------------------------------------------------
    # Library actions
    # ---------------------------------------------------------

    def on_add_selected_tracks(self):
        tracks = self._selected_library_tracks()
        if not tracks:
            return
        self.app.enqueue_manual(tracks)
        self.main_window.refresh_queue()
        self.main_window.refresh_status()

    def on_play_next_selected_tracks(self):
        tracks = self._selected_library_tracks()
        if not tracks:
            return
        self.app.enqueue_manual_next(tracks)
        self.main_window.refresh_queue()
        self.main_window.refresh_status()

    def on_library_row_activated(self, _listbox, row):
        # This handler now works for both library_list and recently_played_list
        track = getattr(row, "track", None)
        if track:
            self.app.enqueue_manual([track])
            self.main_window.refresh_queue() # Refresh queue display
            self.main_window.refresh_status()

    # ---------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------

    def _selected_library_tracks(self) -> list[Track]:
        tracks = []
        for row in self.library_list.get_selected_rows():
            track = getattr(row, "track", None)
            if track:
                tracks.append(track)
        return tracks

    def _filtered_library_tracks(self) -> list[Track]:
        query = self.library_search.get_text().strip().lower()
        active_folder = self.folder_filter.get_active_text()
        folder = None if active_folder in (None, "All folders") else active_folder

        tracks = self.library_tracks

        if folder:
            tracks = [track for track in tracks if track.folder == folder]

        if query:
            tracks = [
                track for track in tracks
                if query in self._track_search_text(track)
            ]
        return tracks

    def _track_search_text(self, track: Track) -> str:
        return f"{track.artist} {track.title} {track.path.name} {track.folder}".lower()

    def _refresh_folder_filter(self):
        current = self.folder_filter.get_active_text() or "All folders"
        folders = ["All folders"] + sorted(
            {track.folder for track in self.library_tracks if track.folder != "NOT_IN_USE"}
        )
        self.folder_filter.remove_all()
        active_index = 0
        for index, folder in enumerate(folders):
            self.folder_filter.append_text(folder)
            if folder == current:
                active_index = index
        self.folder_filter.set_active(active_index)

    # ---------------------------------------------------------
    # Update methods (called by MainWindow)
    # ---------------------------------------------------------

    def refresh_library_display(self):
        # Refresh both lists
        self.library_tracks = self.app.get_all_tracks()
        self.recently_played_tracks = self.app.get_recently_played_tracks(limit=50) # Fetch a reasonable limit
        self._refresh_folder_filter()
        self.main_window._render_list(self.library_list, self._filtered_library_tracks(), selectable=True)
        self.main_window._render_list(self.recently_played_list, self.recently_played_tracks, selectable=True)

    def refresh_recently_played_display(self):
        """Update only the recently played list."""
        self.recently_played_tracks = self.app.get_recently_played_tracks(limit=50)
        self.main_window._render_list(self.recently_played_list, self.recently_played_tracks, selectable=True)

    def render_library_display(self):
        tracks = self._filtered_library_tracks()
        self.main_window._render_list(self.library_list, tracks, selectable=True)
