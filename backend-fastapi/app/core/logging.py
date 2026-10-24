"""
Logging configuration using Loguru.
Outputs to both console and rotating log files.
"""

import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings


def setup_logging():
    """Configure Loguru with console + file sinks."""

    # Remove default handler
    logger.remove()

    # Console sink — colored, human-readable
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File sink — rotating, structured
    log_dir = Path(settings.LOG_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "pathfindar_{time:YYYY-MM-DD}.log"),
        level=settings.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )

    logger.info(f"Logging initialized — level={settings.LOG_LEVEL}, path={log_dir}")
