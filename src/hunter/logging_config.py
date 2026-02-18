"""Configure loguru: rotation, level, format."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(config: dict | None = None) -> None:
    config = config or {}
    log_cfg = config.get("logging", {})
    level = log_cfg.get("level", "INFO")
    rotation = log_cfg.get("rotation", "10 MB")
    retention = log_cfg.get("retention", "7 days")

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=level,
    )
    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / "hunter_{time:YYYY-MM-DD}.log",
        rotation=rotation,
        retention=retention,
        level=level,
        encoding="utf-8",
    )
