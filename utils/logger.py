import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import colorlog

# Test-orchchnoos chdir hiisen ued ham log directory baihgui bgaag harangdaj boldog
# tul get_logger dotor lazy-aar uuseg ulgu, modulin tushrelyl nuhulteg duudna.
_LOG_DIR = Path("logs")


def _ensure_log_dir() -> Path:
    """Resolve and create the log directory if missing."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False   # parent logger руу dup явуулахгүй

    console = colorlog.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "green",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        }
    ))
    logger.addHandler(console)

    # Test orchny shudraga (PYTEST_CURRENT_TEST) ued file handler tuusgehgui —
    # pytest chdir per test → log file path stale bolgodog
    if not os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("DISABLE_FILE_LOG"):
        try:
            log_path = _ensure_log_dir() / "trading_bot.log"
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ))
            logger.addHandler(file_handler)
        except OSError:
            # Read-only FS gh m hyzgaarlagдснnaas болж амжилтгүй болж magadgui — console only
            pass
    return logger
