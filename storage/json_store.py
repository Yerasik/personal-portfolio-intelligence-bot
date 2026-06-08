"""Low-level atomic JSON read/write with file locking."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from storage.locking import locked_json_file

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class JsonStorageError(Exception):
    """Raised when a JSON document cannot be read, validated, or written."""


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

        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            raise JsonStorageError(
                f"Malformed JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})"
            ) from exc

        if not isinstance(payload, dict):
            raise JsonStorageError(
                f"Expected a JSON object at {path}, got {type(payload).__name__}"
            )

        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise JsonStorageError(
                f"Invalid schema in {path} for {model_type.__name__}:\n{exc}"
            ) from exc

    def mutate_model(
        self,
        path: Path,
        model_type: type[TModel],
        mutator: Callable[[TModel], TModel],
    ) -> TModel:
        """Load, mutate, and save a model under a single exclusive file lock."""
        path.parent.mkdir(parents=True, exist_ok=True)

        with locked_json_file(path):
            if not path.exists():
                model = model_type()
            else:
                raw = path.read_text(encoding="utf-8")
                try:
                    payload = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError as exc:
                    raise JsonStorageError(
                        f"Malformed JSON in {path}: {exc.msg} "
                        f"(line {exc.lineno}, column {exc.colno})"
                    ) from exc
                if not isinstance(payload, dict):
                    raise JsonStorageError(
                        f"Expected a JSON object at {path}, got {type(payload).__name__}"
                    )
                try:
                    model = model_type.model_validate(payload)
                except ValidationError as exc:
                    raise JsonStorageError(
                        f"Invalid schema in {path} for {model_type.__name__}:\n{exc}"
                    ) from exc

            updated = mutator(model)
            self._atomic_write_json(path, updated.model_dump(mode="json"))
            return updated

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

        # NamedTemporaryFile defaults to 0600; widen to 0644 so the file stays
        # readable by the host user when the container writes it as root.
        os.chmod(temp_name, 0o644)

        try:
            os.replace(temp_name, path)
        except OSError as exc:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise JsonStorageError(f"Failed to write {path}: {exc}") from exc
