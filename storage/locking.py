"""File locking helpers for safe JSON mutation."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock


def lock_path_for(target: Path) -> Path:
    """Return the sidecar lock file path for a JSON document."""
    return target.with_suffix(target.suffix + ".lock")


@contextmanager
def locked_json_file(target: Path, timeout: float = 30.0) -> Iterator[None]:
    """Acquire an exclusive lock before reading or writing JSON."""
    lock = FileLock(lock_path_for(target), timeout=timeout)
    with lock:
        yield
