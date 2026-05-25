import logging
import math
from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib, GstController

import config


logger = logging.getLogger(__name__)

class PlaybackEngine:
    def __init__(self):
        Gst.init(None)

        # We use two playbins to allow overlapping audio during crossfades
        self._player_a = self._create_player("player_a")
        self._player_b = self._create_player("player_b")
        self._players = [self._player_a, self._player_b]
        self._active_index = 0

        # Configuration
        self._on_track_end = None
        self._on_error = None
        self._state = "stopped"
        self._vu_meter_callback = None # New: Callback for VU meter updates
        self._user_volume = 1.0
        self._track_gain_multiplier = 1.0
        self._crossfade_duration = 3.5
        self._ui_fade_duration = 0.25

    def _create_player(self, name: str) -> Gst.Element:
        player = Gst.ElementFactory.make("playbin", name)
        if not player:
            logger.critical(f"GStreamer 'playbin' ({name}) could not be created.")
            import sys
            sys.exit(1)

        bus = player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

        # Apply audio processing chain
        try:
            norm_filter = Gst.parse_bin_from_description(
                "audioconvert ! audioresample ! "
                "rgvolume ! "
                "ladspa-sc4-1882-so-sc4 name=compressor ! "
                "ladspa-fast-lookahead-limiter-1913-so-fastlookaheadlimiter limit=-1 release-time=0.1 ! " # Limiter
                "level name=vu_meter interval=100000000 post-messages=true ! " # VU Meter (100ms interval)
                "audioconvert", True
            )
            player.set_property("audio-filter", norm_filter)
            self._limiter_available = True
        except Exception as e:
            self._limiter_available = False
            logger.warning(f"LADSPA processing chain failed for {name}: {e}")
        self.update_audio_filters()
        
        return player

    def _get_active_player(self):
        return self._players[self._active_index]

    def _get_inactive_player(self):
        return self._players[1 - self._active_index]

    def _apply_fade(self, player, start_vol, end_vol, duration_sec):
        """Smoothly ramps volume using GStreamer's Controller API."""
        cs = GstController.InterpolationControlSource()
        cs.set_property("mode", GstController.InterpolationMode.LINEAR)
        
        # Bind the control source to the 'volume' property of the playbin
        player.add_control_binding(Gst.DirectControlBinding.new(player, "volume", cs))
        
        duration_ns = int(duration_sec * Gst.SECOND)
        # Set the ramp points (relative to the start of the fade)
        cs.set(0, start_vol)
        cs.set(duration_ns, end_vol)

    def update_audio_filters(self):
        """Updates the compressor element properties on all players using current config."""
        for p in self._players:
            # The 'audio-filter' property holds the GstBin we created
            audio_filter_bin = p.get_property("audio-filter")
            if not audio_filter_bin:
                continue

            compressor = audio_filter_bin.get_by_name("compressor")
            if compressor:
                for prop, value in config.COMPRESSOR_SETTINGS.items():
                    try:
                        compressor.set_property(prop, value)
                    except Exception as e:
                        logger.error(f"Failed to update compressor property {prop}: {e}")

    # -------------------------------------------------
    # Basic control
    # -------------------------------------------------

    def set_crossfade_duration(self, seconds: float):
        self._crossfade_duration = seconds

    def set_ui_fade_duration(self, seconds: float):
        self._ui_fade_duration = seconds

    def play(
        self,
        path: str,
        replaygain_track_gain_db: float | None = None,
        replaygain_track_peak: float | None = None,
    ):
        old_player = self._get_active_player()
        
        # Switch active player
        self._active_index = 1 - self._active_index
        new_player = self._get_active_player()

        self._track_gain_multiplier = self._replaygain_multiplier(
            replaygain_track_gain_db,
            replaygain_track_peak,
        )
        target_vol = self._user_volume * self._track_gain_multiplier

        new_player.set_state(Gst.State.READY)
        new_player.set_property("uri", self._to_uri(path))

        if self._state == "playing" and self._crossfade_duration > 0:
            # Crossfade: Fade out current, fade in next
            self._apply_fade(old_player, old_player.get_property("volume"), 0.0, self._crossfade_duration)
            
            new_player.set_property("volume", 0.0)
            new_player.set_state(Gst.State.PLAYING)
            self._apply_fade(new_player, 0.0, target_vol, self._crossfade_duration)
            
            # Clean up old player after fade completes
            GLib.timeout_add(int(self._crossfade_duration * 1000), old_player.set_state, Gst.State.NULL)
        else:
            # Cold start or stopped state
            new_player.set_property("volume", target_vol)
            new_player.set_state(Gst.State.PLAYING)
            old_player.set_state(Gst.State.NULL)

        self._state = "playing"

    def shutdown(self):
        for p in self._players:
            p.set_state(Gst.State.NULL)
        self._state = "stopped"

    def stop(self):
        active = self._get_active_player()
        self._apply_fade(active, active.get_property("volume"), 0.0, self._ui_fade_duration)
        
        def finish_stop():
            for p in self._players:
                p.set_state(Gst.State.NULL)
            self._state = "stopped"
            return False
        
        GLib.timeout_add(int(self._ui_fade_duration * 1000), finish_stop)

    def pause(self):
        active = self._get_active_player()
        self._apply_fade(active, active.get_property("volume"), 0.0, self._ui_fade_duration)
        
        def finish_pause():
            active.set_state(Gst.State.PAUSED)
            self._state = "paused"
            return False
            
        GLib.timeout_add(int(self._ui_fade_duration * 1000), finish_pause)

    def resume(self):
        active = self._get_active_player()
        target_vol = self._user_volume * self._track_gain_multiplier
        
        active.set_property("volume", 0.0)
        active.set_state(Gst.State.PLAYING)
        self._apply_fade(active, 0.0, target_vol, self._ui_fade_duration)
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
        success, pos = self._get_active_player().query_position(Gst.Format.TIME)
        return pos if success else 0

    def get_duration(self) -> int:
        """Total duration in nanoseconds"""
        success, dur = self._get_active_player().query_duration(Gst.Format.TIME)
        return dur if success else 0

    def seek(self, nanoseconds: int):
        self._get_active_player().seek_simple(
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
        # Only process EOS/Error for the currently active player to avoid
        # fading-out tracks triggering logic for the next track prematurely.
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            if message.src == self._get_active_player():
                self._state = "stopped"
                if self._on_track_end:
                    GLib.idle_add(self._on_track_end)
        elif msg_type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            message.src.set_state(Gst.State.NULL)
            self._state = "stopped"

            if self._on_error:
                GLib.idle_add(self._on_error, str(error), debug)
        elif msg_type == Gst.MessageType.ELEMENT:
            # Handle messages from the 'level' element
            # Ensure the message is from the active player's VU meter
            active_player_filter_bin = self._get_active_player().get_property("audio-filter")
            if active_player_filter_bin:
                active_vu_meter_element = active_player_filter_bin.get_by_name("vu_meter")
                if message.src == active_vu_meter_element:
                    if self._vu_meter_callback:
                        structure = message.get_structure()
                        if structure and structure.get_name() == "level":
                            # The 'level' element posts messages with 'peak' and 'rms' arrays
                            peak_values = [structure.get_nth_double("peak", i) for i in range(structure.n_fields("peak"))]
                            rms_values = [structure.get_nth_double("rms", i) for i in range(structure.n_fields("rms"))]
                            
                            # Convert dB to linear scale (0.0 to 1.0) for UI (assuming -60dB to 0dB range)
                            peak_linear = [min(1.0, max(0.0, (v + 60.0) / 60.0)) for v in peak_values]
                            rms_linear = [min(1.0, max(0.0, (v + 60.0) / 60.0)) for v in rms_values]
    
                            GLib.idle_add(self._vu_meter_callback, peak_linear, rms_linear)

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def _to_uri(self, path: str) -> str:
        return Path(path).resolve().as_uri()

    def _apply_effective_volume(self) -> None:
        effective_volume = self._user_volume * self._track_gain_multiplier
        self._get_active_player().set_property("volume", max(0.0, min(4.0, effective_volume)))

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

    def set_vu_meter_callback(self, callback: Callable[[list[float], list[float]], None]):
        """Sets a callback function to receive VU meter updates (peak and RMS levels)."""
        self._vu_meter_callback = callback
