import logging
from gi.repository import Gdk, Gtk, GLib, Gio

from ui.main_window import MainWindow
from ui.player_controller import PlayerController


class MusicGTKApp(Gtk.Application):
    def __init__(self, backend_app):
        super().__init__(
            application_id="com.music.player.pegasus",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        self.backend_app = backend_app
        self.controller = PlayerController(backend_app)

    def do_startup(self):
        logging.debug("do_startup: Starting Gtk.Application.do_startup")
        Gtk.Application.do_startup(self)
        logging.debug("do_startup: Gtk.Application.do_startup completed.")
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(b"""
            .playing {
                background-color: #3465a4;
                color: white;
            }
            """)
            logging.debug("do_startup: CSS Provider loaded.")
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                logging.debug("do_startup: CSS Provider added to display.")
            else:
                logging.warning("do_startup: Gdk.Display.get_default() returned None. Skipping CSS loading.")
        except Exception as e:
            logging.critical(f"do_startup: An unexpected error occurred during CSS setup: {e}", exc_info=True)

    def do_activate(self):
        logging.info("GTK Application Activated: Creating Main Window")
        win = MainWindow(self.controller)
        win.set_application(self)
        self.controller.set_main_window(win) # Pass the main window to the controller
        win.present()
        # Start the backend in an idle callback so the window appears immediately and doesn't block UI
        GLib.idle_add(self._deferred_start_backend)

    def _deferred_start_backend(self):
        self.controller.start_backend()
        return False # Ensure this only runs once
