"""Session-aware logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path


_ROOT_LOGGER = "paperreader"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_LOGGER_CACHE: dict[str, logging.Logger] = {}


def get_app_logger(name: str) -> logging.Logger:
    """Return an application logger."""
    logging.basicConfig(level=logging.INFO, format=_FORMAT)
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}")


def get_session_logger(session_dir: Path, session_name: str, created_label: str) -> logging.Logger:
    """Return a file-backed logger for a session."""
    key = f"{session_name}:{created_label}"
    if key in _LOGGER_CACHE:
        return _LOGGER_CACHE[key]

    logger = logging.getLogger(f"{_ROOT_LOGGER}.session.{key}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        log_dir = session_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{session_name}_{created_label}.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)

    _LOGGER_CACHE[key] = logger
    return logger
