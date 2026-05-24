import logging
from typing import Callable
from gi.repository import Gtk, Pango

logger = logging.getLogger(__name__)

class UIHelpersMixin:
    """Mixin providing boilerplate reduction for GTK4 widget creation and updates."""

    def create_label(self, text: str="", ellipsize: Pango.EllipsizeMode=Pango.EllipsizeMode.END, max_chars: int=-1, xalign: float=None, hexpand: bool=False, css_class: str=None) -> Gtk.Label:
        """Creates a label with given options.

        Args:
            text (str, optional): The text to display in the label. Defaults to "".
            ellipsize (Pango.EllipsizeMode, optional): The ellipsis mode for the label. Defaults to Pango.EllipsizeMode.END.
            max_chars (int, optional): Maximum number of characters to display. Defaults to -1.
            xalign (float, optional): Horizontal alignment of the label. Defaults to None.
            hexpand (bool, optional): Whether the label should expand horizontally. Defaults to False.
            css_class (str, optional): CSS class to apply to the label. Defaults to None.

        Returns:
            Gtk.Label: The created Gtk.Label widget.
        """
        lbl = Gtk.Label(label=text)
        if ellipsize is not None:
            lbl.set_ellipsize(ellipsize)
        if max_chars != -1:
            lbl.set_max_width_chars(max_chars)
        if xalign is not None:
            lbl.set_xalign(xalign)
        if css_class:
            lbl.add_css_class(css_class)
        lbl.set_hexpand(hexpand)
        return lbl

    def create_button(self, label:str=None, icon_name:str=None, tooltip:str=None, callback:Callable=None, css_class:str=None) -> Gtk.Button:
        """Creates a GTK.Button

        Args:
            label (str, optional): The text to display on the button. Defaults to None.
            icon_name (str, optional): The name of the icon to display on the button. Defaults to None.
            tooltip (str, optional): The tooltip text for the button. Defaults to None.
            callback (callable, optional): The function to call when the button is clicked. Defaults to None.
            css_class (str, optional): The CSS class to apply to the button. Defaults to None.

        Returns:
            Gtk.Button: The created Gtk.Button widget.
        """
        btn = Gtk.Button()
        if label:
            btn.set_label(label)
        if icon_name:
            btn.set_icon_name(icon_name)
        if tooltip:
            btn.set_tooltip_text(tooltip)
        if callback:
            btn.connect("clicked", callback)
        if css_class:
            btn.add_css_class(css_class)
        return btn

    def update_label(self, label_widget: Gtk.Label, text: str) -> None:
        """Update a label only if the text has changed to prevent unnecessary layout cycles."""
        if label_widget.get_text() != text:
            label_widget.set_text(text)

    def format_time(self, nanoseconds: int) -> str:
        """Convert nanoseconds to a human-readable time format (H:MM:SS or M:SS)."""
        total_seconds = max(0, int(nanoseconds / 1_000_000_000))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def create_list_row(self, label_text: str, widget: Gtk.Widget, tooltip: str=None, widget_halign: Gtk.Align=Gtk.Align.END) -> Gtk.ListBoxRow:
        """Creates a standard ListBoxRow with a label on the left and a widget on the right."""
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(12)
        hbox.set_margin_end(12)

        if tooltip:
            row.set_tooltip_text(tooltip)

        hbox.append(self.create_label(label_text, xalign=0))

        widget.set_halign(widget_halign)
        hbox.append(widget)

        row.set_child(hbox)
        return row
    