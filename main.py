#!/usr/bin/env python3

"""Pegasus Music Player - A modern music player built with Python and GTK4.

    This music player is aimed at playing music files from specific folders during set times of the day.
      It is designed to be simple, efficient, and user-friendly, with a focus on providing a seamless music listening experience.
      Folders and 'slots' can be configured by the user, allowing for a personalized music experience that adapts to their daily routine.
      see the yaml file for further information on how to configure the application.

Roadmap:
- [ ] Github Repo and Documentation
"""



import logging
import sys
import gi  # type: ignore[import]

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='/home/pegasus/pegasus_music_player.log',
    filemode='w'
)

from infrastructure.database import Database
from runtime.bootstrap import Application
from ui.application import MusicGTKApp
from config import DB_PATH


def main():
    logging.info("Starting Pegasus Music Player...")
    logging.info("Initializing Database...")
    database = Database(DB_PATH)
    logging.info("Database Initialized. Initializing Backend Application...")
    backend = Application(database=database)
    logging.info("Backend Application Initialized. Initializing GTK Application...")
    app = MusicGTKApp(backend)
    logging.info("GTK Application Initialized. Running GTK Application...")

    app.run(sys.argv)
    logging.info("GTK Application Finished.")


if __name__ == "__main__":
    main()
