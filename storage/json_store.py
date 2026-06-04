"""Low-level atomic JSON read/write with file locking."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from storage.locking import locked_json_file

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class JsonStore:
    """Read and write pydantic models as JSON files on disk."""

    def read_model(self, path: Path, model_type: type[TModel]) -> TModel:
        """Load a model from disk, creating defaults when the file is missing."""
        if not path.exists():
            logger.info("Creating default JSON at %s", path)
            default = model_type()
            self.write_model(path, default)
            return default

        with locked_json_file(path):
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw) if raw.strip() else {}
            return model_type.model_validate(payload)

    def write_model(self, path: Path, model: BaseModel) -> None:
        """Persist a model using an atomic replace and an exclusive file lock."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = model.model_dump(mode="json")

        with locked_json_file(path):
            self._atomic_write_json(path, payload)

    def _atomic_write_json(self, path: Path, payload: dict[str, object]) -> None:
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temp_name = handle.name

        os.replace(temp_name, path)
