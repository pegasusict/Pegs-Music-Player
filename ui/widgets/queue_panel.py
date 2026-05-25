from gi.repository import Gtk, GLib

from domain.track import Track
from ui.player_controller import PlayerController

class QueuePanel(Gtk.Box):
    def __init__(self, app_controller: PlayerController, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app_controller
        self._in_refresh = False
        self.main_window = main_window # Reference to the main window for shared methods

        self.queue_title = Gtk.Label(label="Queue")
        self.append(self.queue_title)

        # Manual queue list
        self.manual_label = Gtk.Label(label="Manual Queue")
        self.append(self.manual_label)

        self.manual_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(self.manual_actions)

        self.remove_manual_button = Gtk.Button(label="Remove selected")
        self.remove_manual_button.connect("clicked", lambda _: self.on_remove_manual_selected())
        self.manual_actions.append(self.remove_manual_button)

        self.manual_top_button = Gtk.Button(label="Top")
        self.manual_top_button.connect("clicked", lambda _: self.on_move_manual_to_top())
        self.manual_actions.append(self.manual_top_button)

        self.manual_up_button = Gtk.Button(label="Up")
        self.manual_up_button.connect("clicked", lambda _: self.on_move_manual_up())
        self.manual_actions.append(self.manual_up_button)

        self.manual_down_button = Gtk.Button(label="Down")
        self.manual_down_button.connect("clicked", lambda _: self.on_move_manual_down())
        self.manual_actions.append(self.manual_down_button)

        self.manual_bottom_button = Gtk.Button(label="Bottom")
        self.manual_bottom_button.connect("clicked", lambda _: self.on_move_manual_to_bottom())
        self.manual_actions.append(self.manual_bottom_button)

        self.clear_manual_button = Gtk.Button(label="Clear")
        self.clear_manual_button.connect("clicked", lambda _: self.on_clear_manual_queue())
        self.manual_actions.append(self.clear_manual_button)

        self.manual_scroll = Gtk.ScrolledWindow()
        self.manual_scroll.set_vexpand(True)
        self.manual_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.manual_list = Gtk.ListBox()
        self.manual_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.manual_scroll.set_child(self.manual_list)

        self.append(self.manual_scroll)

        # Auto queue list
        self.auto_label = Gtk.Label(label="Auto Queue")
        self.append(self.auto_label)

        self.auto_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(self.auto_actions)

        self.remove_auto_button = Gtk.Button(label="Remove selected")
        self.remove_auto_button.connect("clicked", lambda _: self.on_remove_auto_selected())
        self.auto_actions.append(self.remove_auto_button)

        self.autoqueue_switch = Gtk.Switch()
        self.autoqueue_switch.set_halign(Gtk.Align.END)
        self.autoqueue_switch.connect("notify::active", self.on_autoqueue_switch_activated)
        self.auto_actions.append(self.autoqueue_switch)

        self.clear_auto_button = Gtk.Button(label="Clear")
        self.clear_auto_button.connect("clicked", lambda _: self.on_clear_auto_queue())
        self.auto_actions.append(self.clear_auto_button)

        self.auto_scroll = Gtk.ScrolledWindow()
        self.auto_scroll.set_vexpand(True)
        self.auto_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.auto_list = Gtk.ListBox()
        self.auto_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.auto_scroll.set_child(self.auto_list)

        self.append(self.auto_scroll)

        # Set initial state of the switch
        self.autoqueue_switch.set_active(self.app.get_autoqueue_enabled())

    # ---------------------------------------------------------
    # Queue actions
    # ---------------------------------------------------------

    def on_remove_manual_selected(self):
        positions = self._selected_queue_positions(self.manual_list)

        if positions:
            self.app.remove_manual_queue_positions(positions)
            self.refresh_queue_display()
            self.main_window.refresh_status()

    def on_move_manual_up(self):
        self._move_manual_selection(self.app.move_manual_queue_up)

    def on_move_manual_down(self):
        self._move_manual_selection(self.app.move_manual_queue_down)

    def on_move_manual_to_top(self):
        self._move_manual_selection(self.app.move_manual_queue_to_top)

    def on_move_manual_to_bottom(self):
        self._move_manual_selection(self.app.move_manual_queue_to_bottom)

    def on_remove_auto_selected(self):
        positions = self._selected_queue_positions(self.auto_list)

        if positions:
            self.app.remove_auto_queue_positions(positions)
            self.refresh_queue_display()
            self.main_window.refresh_status()

    def on_clear_manual_queue(self):
        self.app.clear_manual_queue()
        self.refresh_queue_display()
        self.main_window.refresh_status()

    def on_clear_auto_queue(self):
        self.app.clear_auto_queue()
        self.refresh_queue_display()
        self.main_window.refresh_status()

    def on_autoqueue_switch_activated(self, switch, _pspec):
        if self._in_refresh:
            return
        self.app.set_autoqueue_enabled(switch.get_active())
        self.main_window.refresh_status()

    # ---------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------

    def _selected_queue_positions(self, listbox) -> list[int]:
        positions = []
        for row in listbox.get_selected_rows():
            position = getattr(row, "queue_position", None)
            if position is not None:
                positions.append(position)
        return sorted(positions)

    def _move_manual_selection(self, move_fn):
        positions = self._selected_queue_positions(self.manual_list)
        if not positions:
            return
        moved_positions = move_fn(positions)
        self.refresh_queue_display()
        self._select_queue_positions(self.manual_list, moved_positions)
        self.main_window.refresh_status()

    def _select_queue_positions(self, listbox, positions: list[int]) -> None:
        targets = set(positions)
        child = listbox.get_first_child()
        while child:
            if getattr(child, "queue_position", None) in targets:
                listbox.select_row(child)
            child = child.get_next_sibling()

    # ---------------------------------------------------------
    # Update methods (called by MainWindow)
    # ---------------------------------------------------------

    def refresh_queue_display(self):
        self._in_refresh = True
        snapshot = self.app.get_queue_snapshot()
        self.main_window._render_list(self.manual_list, snapshot["manual"])
        self.main_window._render_list(self.auto_list, snapshot["auto"])
        self.autoqueue_switch.set_active(self.app.get_autoqueue_enabled()) # Ensure switch state is always correct
        self._in_refresh = False
