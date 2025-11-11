# =========================================
# logger.py
# Purpose:
#   - Centralized rotating logger for all automation scripts
#   - Creates new log file daily, keeps history for N days
# =========================================

import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

# Default log directory (relative to project root)
ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str = "main", level: str = "info", keep_days: int = 14):
    """
    Create and configure a rotating logger.
    Args:
        name: name of the logger (module name)
        level: logging level ("debug", "info", "warning", "error")
        keep_days: number of days to keep logs
    Returns:
        logging.Logger instance
    """
    logfile = LOG_DIR / f"{name}.log"
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)
    logger.handlers.clear()

    # Rotate logs daily, keep N backups
    file_handler = TimedRotatingFileHandler(
        logfile,
        when="midnight",
        backupCount=keep_days,
        encoding="utf-8"
    )
    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("🟢 Logger initialized for '%s' (level=%s, keep=%d days)", name, level.upper(), keep_days)
    return logger
