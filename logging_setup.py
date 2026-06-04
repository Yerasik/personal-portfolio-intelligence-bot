"""Application-wide logging configuration."""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str, log_dir: str | Path) -> None:
    """Configure root logging to stdout and a rotating file under log_dir."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "portfolio-bot.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    logging.getLogger(__name__).debug("Logging initialized at %s", log_file)
