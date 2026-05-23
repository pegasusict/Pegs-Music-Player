# application/playback_controller.py

import logging
from typing import Optional

from domain.track import Track

logger = logging.getLogger(__name__)


class PlaybackController:

    def __init__(self, player, selector, history):
        self.player = player
        self.selector = selector
        self.history = history

        self.current_track: Optional[Track] = None

        self.player.set_on_track_end(self._on_track_end)

    # -----------------------------------------------------

    def start(self):
        self._play_next()

    def skip(self):
        self._play_next()

    def stop(self):
        self.player.stop()

    # -----------------------------------------------------

    def _play_next(self):
        track = self.selector.select_next()

        if not track:
            logger.info("No track available")
            return

        self.current_track = track

        logger.info("Now playing: %s - %s", track.artist, track.path.name)

        self.history.log_play(track)

        self.player.play(
            str(track.path),
            track.replaygain_track_gain_db,
            track.replaygain_track_peak,
        )

    def _on_track_end(self):
        self._play_next()
