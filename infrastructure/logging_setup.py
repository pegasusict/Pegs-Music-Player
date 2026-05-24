import logging
from pathlib import Path
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def init_logging(level: str | int = logging.INFO, log_file: str = "pegasus_player.log"):
    """
    Initializes the centralized logging system for the entire application.
    Sets up a console handler and an optional file handler.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Create the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers if any (to avoid duplicate logs on re-init)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console Handler (Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File Handler
    if log_file:
        try:
            # Expand ~ and handle absolute paths. If relative, use the default cache dir.
            log_path = Path(log_file).expanduser()
            if not log_path.is_absolute():
                log_path = Path("~/.cache/pegasus-player/").expanduser() / log_path
            
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logging.info(f"File logging initialized at: {log_path}")
        except Exception as e:
            print(f"CRITICAL: Failed to initialize file logging: {e}", file=sys.stderr)