# runtime/slot_runtime.py

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from scheduler.timeslot_scheduler import TimeslotScheduler
from infrastructure.file_watcher import FileWatcher


logger = logging.getLogger(__name__)


class SlotRuntime:
    """
    Orchestrates:
    - Timeslot detection
    - FileWatcher reconfiguration
    """

    def __init__(
        self,
        scheduler: TimeslotScheduler,
        filewatcher: FileWatcher,
        base_folder: Path,
        poll_interval: float = 5.0,
    ):
        self.scheduler = scheduler
        self.filewatcher = filewatcher
        self.base_folder = base_folder
        self.poll_interval = poll_interval

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_known_slot_name: Optional[str] = None # To track changes

    # -------------------------------------------------------------

    def start(self):
        if self._running:
            return

        logger.info("Starting SlotRuntime")

        self._running = True
        self.filewatcher.start()

        self._thread = threading.Thread(
            target=self._loop,
            name="SlotRuntime",
            daemon=True,
        )
        self._thread.start()

    # -------------------------------------------------------------

    def stop(self):
        if not self._running:
            return

        logger.info("Stopping SlotRuntime")
        self._running = False

        if self._thread:
            self._thread.join()

        self.filewatcher.stop()

    def trigger_reconfiguration(self):
        """
        Forces the SlotRuntime to re-evaluate the current timeslot
        and reconfigure the FileWatcher on its next loop iteration.
        """
        logger.info("SlotRuntime received trigger to reconfigure.")
        # Invalidate last known slot to force re-evaluation in the next _loop iteration.
        self._last_known_slot_name = None

    # -------------------------------------------------------------

    def _loop(self):
        while self._running:
            current_slot = self.scheduler.current_slot
            current_slot_name = current_slot.name if current_slot else None

            if current_slot_name != self._last_known_slot_name:
                self._last_known_slot_name = current_slot_name
                
                active_folders: list[str] = []
                if current_slot:
                    active_folders.extend(f for f in current_slot.folders if f != "NOT_IN_USE")
                    if current_slot.each_iteration_folder != "NOT_IN_USE":
                        active_folders.append(current_slot.each_iteration_folder)
                active_folders = list(dict.fromkeys(active_folders)) # Remove duplicates

                logger.info(
                    "Timeslot changed → %s",
                    current_slot_name if current_slot_name else "None"
                )

                # Resolve folder names to absolute paths and filter out NOT_IN_USE
                paths = [
                    (self.base_folder / f).expanduser().resolve()
                    for f in active_folders
                ]
                self.filewatcher.reconfigure(paths) # type: ignore
            
            # Use a more responsive sleep to allow quicker shutdown
            for _ in range(int(self.poll_interval / 0.1)): # Check every 0.1 seconds
                if not self._running:
                    break
                time.sleep(0.1)
