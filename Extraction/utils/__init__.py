"""
utils/__init__.py
------------------
Utility helpers: logging configuration, value conversion, path utilities.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(
    level: int = logging.INFO,
    log_file: str | Path | None = None,
) -> None:
    """
    Configure root logger with console (and optional file) handlers.

    Parameters
    ----------
    level:
        Log level (e.g. logging.DEBUG, logging.INFO).
    log_file:
        Optional path to write log output. If None, logs go to stdout only.
    """
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=handlers,
        force=True,
    )


def collect_pdfs(path: str | Path) -> list[Path]:
    """
    Return a sorted list of PDF paths.

    If *path* is a file, return it in a single-element list.
    If *path* is a directory, return all .pdf files within it.
    """
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".pdf":
        return [p]
    if p.is_dir():
        return sorted(p.glob("*.pdf"))
    return []
