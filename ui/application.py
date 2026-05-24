import logging

from gi.repository import Gdk, Gio, GLib, Gtk

import config
from infrastructure.logging_setup import init_logging
from ui.main_window import MainWindow
from ui.player_controller import PlayerController

logger = logging.getLogger(__name__)

class MusicGTKApp(Gtk.Application):
    def __init__(self, backend_app):
        super().__init__(
            application_id="com.music.player.pegasus",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        # Initialize logging for the entire app session
        init_logging(config.LOG_LEVEL, config.LOG_FILE)

        self.backend_app = backend_app
        self.controller = PlayerController(backend_app)

    def do_startup(self):
        logger.debug("Starting Gtk.Application.do_startup")
        Gtk.Application.do_startup(self)
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(b"""
            .playing {
                background-color: #3465a4;
                color: white;
            }
            """)
            logger.debug("CSS Provider loaded.")
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                logger.debug("CSS Provider added to display.")
            else:
                logger.warning("Gdk.Display.get_default() returned None. Skipping CSS loading.")
        except Exception as e:
            logger.critical(f"An unexpected error occurred during CSS setup: {e}", exc_info=True)

    def do_activate(self):
        logger.info("GTK Application Activated: Creating Main Window")
        win = MainWindow(self.controller)
        win.set_application(self)
        self.controller.set_main_window(win) # Pass the main window to the controller
        win.present()
        # Start the backend in an idle callback so the window appears immediately and doesn't block UI
        GLib.idle_add(self._deferred_start_backend)

    def _deferred_start_backend(self):
        self.controller.start_backend()
        return False # Ensure this only runs once
