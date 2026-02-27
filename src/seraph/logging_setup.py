"""Logging configuration for Seraph.

All seraph.* loggers inherit from the root "seraph" logger.
Console output goes to stderr (critical for MCP stdio transport).
"""

from __future__ import annotations

import logging
import sys

from seraph.config import LogConfig


def setup_logging(log_config: LogConfig, *, verbose: bool = False) -> None:
    """Configure the seraph logger hierarchy.

    Args:
        log_config: Logging settings from SeraphConfig.
        verbose: If True, overrides level to DEBUG.
    """
    root_logger = logging.getLogger("seraph")

    # Avoid adding duplicate handlers on repeated calls
    if root_logger.handlers:
        return

    level = logging.DEBUG if verbose else getattr(logging, log_config.level.upper(), logging.WARNING)
    root_logger.setLevel(level)

    # Console handler on stderr (keeps stdout clean for MCP stdio)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(log_config.format))
    root_logger.addHandler(console)

    # Optional file handler
    if log_config.file:
        file_handler = logging.FileHandler(log_config.file)
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(log_config.format))
        root_logger.addHandler(file_handler)
