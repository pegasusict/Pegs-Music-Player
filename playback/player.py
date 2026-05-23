from pathlib import Path
import logging
import math
import gi
gi.require_version("Gst", "1.0")

from gi.repository import Gst, GLib

logger = logging.getLogger(__name__)


class PlaybackEngine:
    def __init__(self):
        Gst.init(None)

        self._player = Gst.ElementFactory.make("playbin", "player")
        if not self._player:
            logger.critical(
                "GStreamer 'playbin' element could not be created. "
                "Check if gst-plugins-base is installed."
            )
            import sys
            sys.exit(1)

        self._bus = self._player.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_message)

        # Keep a limiter after per-track ReplayGain volume adjustment to catch peaks.
        try:
            norm_filter = Gst.parse_bin_from_description(
                "audioconvert ! audioresample ! rglimiter ! audioconvert", True
            )
            self._player.set_property("audio-filter", norm_filter)
            self._limiter_available = True
        except Exception as e:
            self._limiter_available = False
            logger.warning("Audio limiter filter could not be initialized: %s", e)

        self._on_track_end = None
        self._on_error = None
        self._state = "stopped"
        self._user_volume = 1.0
        self._track_gain_multiplier = 1.0

    # -------------------------------------------------
    # Basic control
    # -------------------------------------------------

    def play(
        self,
        path: str,
        replaygain_track_gain_db: float | None = None,
        replaygain_track_peak: float | None = None,
    ):
        self._track_gain_multiplier = self._replaygain_multiplier(
            replaygain_track_gain_db,
            replaygain_track_peak,
        )
        self._player.set_property("uri", self._to_uri(path))
        self._apply_effective_volume()
        self._player.set_state(Gst.State.PLAYING)
        self._state = "playing"

    def shutdown(self):
        """Cleanly releases GStreamer resources and stops threads."""
        self._player.set_state(Gst.State.NULL)
        self._player.set_property("uri", None)
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None
        self._state = "stopped"

    def stop(self):
        self._player.set_state(Gst.State.NULL)
        self._track_gain_multiplier = 1.0
        self._apply_effective_volume()
        self._state = "stopped"

    def pause(self):
        self._player.set_state(Gst.State.PAUSED)
        self._state = "paused"

    def resume(self):
        self._player.set_state(Gst.State.PLAYING)
        self._state = "playing"

    def set_volume(self, volume: float):
        self._user_volume = max(0.0, min(1.0, volume))
        self._apply_effective_volume()

    def get_volume(self) -> float:
        return self._user_volume

    @property
    def limiter_available(self) -> bool:
        return self._limiter_available

    @property
    def state(self) -> str:
        return self._state

    # -------------------------------------------------
    # Position / duration (NEW)
    # -------------------------------------------------

    def get_position(self) -> int:
        """Current position in nanoseconds"""
        success, pos = self._player.query_position(Gst.Format.TIME)
        return pos if success else 0

    def get_duration(self) -> int:
        """Total duration in nanoseconds"""
        success, dur = self._player.query_duration(Gst.Format.TIME)
        return dur if success else 0

    def seek(self, nanoseconds: int):
        self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            nanoseconds,
        )

    # -------------------------------------------------
    # Events
    # -------------------------------------------------

    def set_on_track_end(self, callback):
        self._on_track_end = callback

    def set_on_error(self, callback):
        self._on_error = callback

    def _on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            self._player.set_state(Gst.State.NULL)
            self._state = "stopped"
            if self._on_track_end:
                GLib.idle_add(self._on_track_end)
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self._player.set_state(Gst.State.NULL)
            self._state = "stopped"

            if self._on_error:
                GLib.idle_add(self._on_error, str(error), debug)

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def _to_uri(self, path: str) -> str:
        return Path(path).resolve().as_uri()

    def _apply_effective_volume(self) -> None:
        effective_volume = self._user_volume * self._track_gain_multiplier
        self._player.set_property("volume", max(0.0, min(4.0, effective_volume)))

    def _replaygain_multiplier(
        self,
        gain_db: float | None,
        peak: float | None,
    ) -> float:
        if gain_db is None:
            return 1.0

        multiplier = math.pow(10.0, gain_db / 20.0)

        if peak and peak > 0:
            multiplier = min(multiplier, 1.0 / peak)

        return max(0.0, min(4.0, multiplier))
