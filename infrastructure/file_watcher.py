from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class FileWatcher:
    """
    Watches folders for newly created audio files and emits Track objects
    via the provided callback.

    Production-grade considerations:
    - Recursive folder watching
    - Extension filtering
    - Debounce for partially written files
    - Thread-safe start/stop/reconfigure
    - Clean shutdown
    """

    def __init__(
        self,
        folders: Iterable[Path],
        supported_extensions: set[str],
        on_new_track: Callable[[Path], None],
        write_stability_delay: float = 1.5,
    ) -> None:
        self._folders = [Path(f).expanduser().resolve() for f in folders]
        self._extensions = {ext.lower() for ext in supported_extensions}
        self._on_new_track = on_new_track
        self._write_stability_delay = write_stability_delay

        self._observer: Observer | None = None
        self._lock = threading.RLock()
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Starts the file watcher, initializing the observer and event handlers."""
        with self._lock:
            if self._running:
                return

            self._observer = Observer()
            handler = _EventHandler(self)

            for folder in self._folders:
                if folder.exists():
                    logger.info("Watching folder: %s", folder)
                    self._observer.schedule(handler, str(folder), recursive=True)
                else:
                    logger.warning("Folder does not exist: %s", folder)

            self._observer.start()
            self._running = True

    def stop(self) -> None:
        """Stops the file watcher, stopping the observer."""
        observer = None
        with self._lock:
            if not self._running or not self._observer:
                return

            logger.info("Stopping FileWatcher...")
            self._running = False
            observer = self._observer
            self._observer = None

        if observer:
            # Join outside the lock to allow the stability loop to acquire 
            # the lock, see that we are no longer running, and exit.
            observer.stop()
            observer.join()

    def reconfigure(self, folders: Iterable[Path]) -> None:
        """
        Switch watched folders (used by Scheduler when time window changes).
        """
        self.stop()
        with self._lock:
            self._folders = [Path(f).expanduser().resolve() for f in folders]
        self.start()

    def set_supported_extensions(self, supported_extensions: set[str]) -> None:
        """Update the file extensions that should be treated as audio files."""
        with self._lock:
            self._extensions = {ext.lower() for ext in supported_extensions}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_path(self, path: Path) -> None:
        """Handles a new file path, checking if it is a valid audio file and stable before invoking the callback."""
        if not path.is_file():
            return

        if path.suffix.lower() not in self._extensions:
            return

        if not self._wait_until_stable(path):
            logger.debug("File did not stabilize: %s", path)
            return

        try:
            self._on_new_track(path)
            logger.info("New track discovered: %s", path)
        except Exception:
            logger.exception("Failed processing new file: %s", path)

    def _wait_until_stable(self, path: Path) -> bool:
        """
        Wait until file size stops changing (prevents enqueueing half-written files).
        """
        try:
            previous_size = -1
            stable_for = 0.0

            while stable_for < self._write_stability_delay:
                with self._lock:
                    if not self._running:
                        return False
                current_size = path.stat().st_size

                if current_size == previous_size:
                    stable_for += 0.2
                else:
                    stable_for = 0.0
                    previous_size = current_size

                time.sleep(0.2)

            return True
        except FileNotFoundError:
            return False


# ----------------------------------------------------------------------
# Watchdog event handler
# ----------------------------------------------------------------------


class _EventHandler(FileSystemEventHandler):
    """Internal event handler for watchdog that delegates to the FileWatcher."""
    def __init__(self, watcher: FileWatcher) -> None:
        self._watcher = watcher

    def on_created(self, event) -> None:
        """Handle newly created files in the watched folders."""
        if isinstance(event, FileCreatedEvent):
            self._watcher._handle_path(Path(event.src_path))

    def on_moved(self, event) -> None:
        """Handle files moved into the watched folders (e.g. completed downloads)."""
        if isinstance(event, FileMovedEvent):
            self._watcher._handle_path(Path(event.dest_path))
