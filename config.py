import copy
from datetime import time
import logging
from pathlib import Path
import sys
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.yaml"
CURRENT_CONFIG_VERSION = 1  # Increment this when the config schema changes

# Global variables that hold the current configuration values
DB_PATH: str
BASE_FOLDER: Path
SUPPORTED_EXTENSIONS: set[str]
AVERAGE_TRACK_DURATION_SECONDS: int
DAILY_FOLDER: str
TIMESLOTS: list[dict[str, Any]]
LOG_LEVEL: str
LOG_FILE: str
CROSSFADE_SECONDS: float
UI_FADE_SECONDS: float
SILENCE_THRESHOLD: float
AUTOQUEUE_PREPOPULATE_COUNT: int
COMPRESSOR_SETTINGS: Dict[str, float]

# Define the full default configuration schema
DEFAULT_CONFIG_SCHEMA: Dict[str, Any] = {
    "version": CURRENT_CONFIG_VERSION,
    "db_path": "~/.music_player.db", # Default database path
    "base_folder": "INSERT_YOUR_MUSIC_FOLDER_PATH_HERE", # Placeholder for user's music folder
    "average_track_duration_seconds": 210,
    "crossfade_seconds": 3.5,
    "ui_fade_seconds": 0.25,
    "silence_threshold_db": -60.0,
    "autoqueue_prepopulate_count": 5,
    "supported_extensions": [".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aac", ".mp2"], # Supported audio file extensions
    "compressor": {
        "rms_peak": 0.0,
        "attack_time": 1.5,
        "release_time": 32.5,
        "threshold_level": -20.0,
        "ratio": 4.0,
        "knee_radius": 2.0,
        "makeup_gain": 0.0,
    },
    "daily_folder": "NOT_IN_USE", # Folder for daily special tracks (e.g., daily jingles)
    "logging": {
        "level": "INFO",
        "file": "~/.cache/pegasus-player/pegasus_player.log"
    },
    "timeslots": [
        {
            "name": "morning",
            "start": "07:00",
            "end": "13:00",
            "folders": ["morning", "shared"], # Folders for regular tracks during this slot
            "each_iteration_folder": "every_morning" # Folder for tracks played once per slot iteration
        },
        {
            "name": "afternoon",
            "start": "13:00",
            "end": "03:00",  # This crosses midnight
            "folders": ["afternoon", "shared"],
            "each_iteration_folder": "every_afternoon"
        },
        {
            "name": "night",
            "start": "03:00",
            "end": "07:00",
            "folders": ["night"],
            "each_iteration_folder": "NOT_IN_USE"
        }
    ],
}

def _merge_configs(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merges overlay dictionary into base dictionary.
    Values from overlay overwrite values in base.
    New keys in overlay are added to base.
    """
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _merge_configs(base[key], value)
        else:
            base[key] = value
    return base

def _insert_dummy_values(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inserts dummy values for critical fields if they are missing or default
    and require user attention. This is primarily for the generated config file.
    """    # Only mark as dummy if it's the default value AND the path doesn't exist, or if it's explicitly empty.
    current_base_folder = config.get("base_folder")
    if (current_base_folder == DEFAULT_CONFIG_SCHEMA["base_folder"] and not Path(current_base_folder).expanduser().exists()) \
       or not current_base_folder:
        config["base_folder"] = "PATH_TO_YOUR_MUSIC_FOLDER_HERE"
        logger.warning("Please update 'base_folder' in config.yaml to your music directory.")

    for slot in config.get("timeslots", []):
        # Only insert dummy if folders are explicitly empty and not already marked NOT_IN_USE
        if not slot.get("folders") or (slot.get("folders") == [""] and "NOT_IN_USE" not in slot.get("folders", [])):
            slot["folders"] = ["DUMMY_FOLDER_FOR_TIMESLOT"]
            logger.warning(f"Timeslot '{slot.get('name', 'UNKNOWN')}' has no folders. Please update 'folders' in config.yaml.")

        # Handle the each_iteration_folder
        iter_folder = slot.get("each_iteration_folder")
        if not iter_folder or (iter_folder == "" and iter_folder != "NOT_IN_USE"):
            slot["each_iteration_folder"] = f"DUMMY_ITERATION_FOLDER_FOR_{slot['name'].upper()}"
            logger.warning(f"Iteration folder for timeslot '{slot['name']}' is empty. Please update 'each_iteration_folder' in config.yaml.")

    if not config.get("daily_folder"):
        config["daily_folder"] = "DUMMY_DAILY_FOLDER"
        logger.warning("Daily folder is empty. Please update 'daily_folder' in config.yaml.")

    return config

def migrate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Applies migration logic to update older config versions."""
    version = config.get("version", 0)  # Assume version 0 if not present

    if version < 1:
        logger.info("Migrating config from version 0 to 1.")
        # Example migration: if a new field 'new_setting' was added in v1
        # config['new_setting'] = DEFAULT_CONFIG_SCHEMA['new_setting']
        config['version'] = 1
        # Add any specific migration logic here if schema changes between versions
        # For now, merging with default schema handles most additions.

    # Add more `if version < X:` blocks for future migrations

    return config

def load_config() -> dict[str, Any]:
    """Loads the YAML configuration file, applies defaults, migrates, and saves."""
    loaded_config: Dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded_config = yaml.safe_load(f) or {}  # Handle empty file
        except yaml.YAMLError as e:
            logger.error(f"Error parsing config.yaml: {e}. Using default configuration.")
            loaded_config = {}
    else:
        logger.info(f"config.yaml not found at {CONFIG_FILE}. Creating with default values.")

    # Start with a deep copy of the default schema
    final_config = copy.deepcopy(DEFAULT_CONFIG_SCHEMA)
    # Merge loaded config into the default schema to apply user settings
    final_config = _merge_configs(final_config, loaded_config)

    # Apply migrations
    final_config = migrate_config(final_config)

    # Insert dummy values for critical fields if they are still at their default/empty
    final_config = _insert_dummy_values(final_config)

    # Ensure the version is updated to the current application version
    final_config['version'] = CURRENT_CONFIG_VERSION

    # Save the potentially updated/migrated config back to file
    try:
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(final_config, f, sort_keys=False)
    except Exception as e:
        logger.error(f"Failed to write updated config.yaml: {e}")

    _update_module_globals(final_config)
    return final_config

def _update_module_globals(cfg: Dict[str, Any]):
    """Updates the module-level global variables with values from the provided config."""
    global DB_PATH, BASE_FOLDER, SUPPORTED_EXTENSIONS, AVERAGE_TRACK_DURATION_SECONDS, DAILY_FOLDER, TIMESLOTS, LOG_LEVEL, LOG_FILE, CROSSFADE_SECONDS, UI_FADE_SECONDS, SILENCE_THRESHOLD, COMPRESSOR_SETTINGS, AUTOQUEUE_PREPOPULATE_COUNT
    
    DB_PATH = str(Path(cfg["db_path"]).expanduser())
    BASE_FOLDER = Path(cfg["base_folder"]).expanduser()
    SUPPORTED_EXTENSIONS = set(cfg["supported_extensions"])
    AVERAGE_TRACK_DURATION_SECONDS = int(cfg["average_track_duration_seconds"])
    DAILY_FOLDER = str(cfg["daily_folder"])
    LOG_LEVEL = cfg.get("logging", {}).get("level", "INFO")
    LOG_FILE = cfg.get("logging", {}).get("file", "~/.cache/pegasus-player/pegasus_player.log")
    CROSSFADE_SECONDS = float(cfg.get("crossfade_seconds", 3.5))
    UI_FADE_SECONDS = float(cfg.get("ui_fade_seconds", 0.25))
    SILENCE_THRESHOLD = float(cfg.get("silence_threshold_db", -60.0))
    AUTOQUEUE_PREPOPULATE_COUNT = int(cfg.get("autoqueue_prepopulate_count", 5))

    # Map config (underscores) to GStreamer LADSPA properties (hyphens)
    comp = cfg.get("compressor", DEFAULT_CONFIG_SCHEMA["compressor"])
    COMPRESSOR_SETTINGS = {
        "rms-peak": float(comp.get("rms_peak", 0.0)),
        "attack-time": float(comp.get("attack_time", 1.5)),
        "release-time": float(comp.get("release_time", 32.5)),
        "threshold-level": float(comp.get("threshold_level", -20.0)),
        "ratio": float(comp.get("ratio", 4.0)),
        "knee-radius": float(comp.get("knee_radius", 2.0)),
        "makeup-gain": float(comp.get("makeup_gain", 0.0)),
    }

    # Parse timeslots into a format compatible with the domain model
    TIMESLOTS = []
    for slot_data in cfg.get("timeslots", []):
        try:
            TIMESLOTS.append({
                "name": slot_data["name"],
                "start": time.fromisoformat(slot_data["start"]),
                "end": time.fromisoformat(slot_data["end"]), # type: ignore
                "folders": slot_data["folders"], # type: ignore
                "each_iteration_folder": slot_data.get("each_iteration_folder", "NOT_IN_USE") # type: ignore
            })
        except KeyError as e:
            logger.error(f"Malformed timeslot entry in config.yaml: missing key '{e}'. Skipping slot: {slot_data}")
        except ValueError as e:
            logger.error(f"Invalid time format in timeslot entry: {e}. Skipping slot: {slot_data}")

def save_config(config_data: dict[str, Any]):
    """Persists a configuration dictionary to the YAML file."""
    try:
        # Ensure version is set correctly
        config_data['version'] = CURRENT_CONFIG_VERSION
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(config_data, f, sort_keys=False)
        # After saving, reload the config to update module-level globals
        load_config()
        logger.info("Configuration saved successfully to config.yaml")
    except Exception as e:
        logger.error(f"Failed to save configuration: {e}")

def update_average_duration(new_value: int):
    """Updates the global average track duration and persists it to config.yaml."""
    global AVERAGE_TRACK_DURATION_SECONDS
    AVERAGE_TRACK_DURATION_SECONDS = new_value
    try:
        with open(CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f) or {}
        data["average_track_duration_seconds"] = new_value
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, sort_keys=False)
        logger.info(f"Updated config.yaml average_track_duration_seconds to {new_value}")
    except Exception as e:
        logger.error(f"Failed to update config.yaml: {e}")

# Initial load to populate globals when module is imported
load_config()

def validate_config():
    """Performs quality checks on the loaded configuration."""
    # We reuse the logic below but raise the error for application startup
    raw_slots = []
    with open(CONFIG_FILE, "r") as f:
        data = yaml.safe_load(f) or {}
        raw_slots = data.get("timeslots", [])
    
    errors = verify_timeslot_continuity(raw_slots)
    
    # Add path checks
    errors = []

    # 1. Check Base Path
    if str(BASE_FOLDER) == str(Path("PATH_TO_YOUR_MUSIC_FOLDER_HERE").expanduser()):
        errors.append(f"Base music folder is still the dummy value: '{BASE_FOLDER}'. Please update 'base_folder' in config.yaml to a valid path.")
    elif not BASE_FOLDER.exists():
        errors.append(f"Base music folder does not exist: '{BASE_FOLDER}'. Please update 'base_folder' in config.yaml.")

    # 2. Check for Overlapping Timeslots
    intervals = []
    for slot in TIMESLOTS:
        s_min = slot["start"].hour * 60 + slot["start"].minute
        e_min = slot["end"].hour * 60 + slot["end"].minute
        
        if s_min < e_min:
            intervals.append((s_min, e_min, slot["name"]))
        else:
            intervals.append((s_min, 1440, slot["name"]))
            intervals.append((0, e_min, slot["name"]))

    
    continuity_errors = verify_timeslot_continuity(raw_slots)
    errors.extend(continuity_errors)

    # 3. Verify Folders
    required_subfolders = set()
    required_subfolders.add(DAILY_FOLDER)
    for slot in TIMESLOTS:
        for folder_name in slot["folders"]:
            if "DUMMY_FOLDER" not in folder_name and folder_name != "NOT_IN_USE": # Don't validate dummy or NOT_IN_USE folders
                required_subfolders.add(folder_name)
        # Also validate the each_iteration_folder
        folder = slot.get("each_iteration_folder")
        if folder and "DUMMY_ITERATION_FOLDER" not in folder and folder != "NOT_IN_USE":
            required_subfolders.add(folder)

    for folder in required_subfolders:
        full_path = BASE_FOLDER / folder
        if not full_path.exists():
            logger.warning(f"Configured folder missing on disk: '{full_path}'. Please create this folder or update config.yaml.")

    if errors:
        for error in errors:
            logger.error(f"CONFIG ERROR: {error}")
        raise ValueError("Invalid configuration. Please check config.yaml and logs for details.")


def verify_timeslot_continuity(timeslots_data: list[dict]) -> list[str]:
    """
    Checks if the provided timeslots are valid, non-overlapping, 
    and cover exactly 24 hours.
    """
    errors = []
    if not timeslots_data:
        return ["At least one timeslot must be defined."]

    intervals = []
    for slot in timeslots_data:
        try:
            s_str, e_str = slot.get("start", ""), slot.get("end", "")
            s_h, s_m = map(int, s_str.split(':'))
            e_h, e_m = map(int, e_str.split(':'))
            s_min = s_h * 60 + s_m
            e_min = e_h * 60 + e_m

            if s_min == e_min:
                errors.append(f"Slot '{slot['name']}' has zero duration ({s_str}).")
                continue

            if s_min < e_min:
                intervals.append((s_min, e_min, slot["name"]))
            else: # Midnight wrap
                intervals.append((s_min, 1440, slot["name"]))
                intervals.append((0, e_min, slot["name"]))
        except (ValueError, AttributeError):
            errors.append(f"Invalid time format in slot '{slot.get('name', 'Unknown')}'. Use HH:MM.")

    if errors: return errors

    intervals.sort()
    
    # Check for gaps and overlaps
    if intervals[0][0] != 0:
        errors.append(f"The schedule must start at 00:00. Gap found before '{intervals[0][2]}'.")

    for i in range(len(intervals) - 1):
        curr_end = intervals[i][1]
        next_start = intervals[i+1][0]
        
        if curr_end > next_start and intervals[i][2] != intervals[i+1][2]:
            errors.append(f"Overlap: '{intervals[i][2]}' ends at {_format_minutes(curr_end)}, but '{intervals[i+1][2]}' starts at {_format_minutes(next_start)}.")
        elif curr_end < next_start:
            errors.append(f"Gap: There is unscheduled time between {_format_minutes(curr_end)} and {_format_minutes(next_start)}.")

    if intervals[-1][1] != 1440:
        errors.append(f"The schedule must end at 24:00 (00:00). Gap found after '{intervals[-1][2]}'.")

    return errors

def _format_minutes(minutes: int) -> str:
    """Helper to format minutes-from-midnight back to HH:MM."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

try:
    validate_config()
except ValueError as e:
    logger.critical(f"Application will not start due to configuration errors: {e}")
    sys.exit(1)
except Exception as e:
    logger.critical(f"An unexpected error occurred during configuration validation: {e}")
    sys.exit(1)
