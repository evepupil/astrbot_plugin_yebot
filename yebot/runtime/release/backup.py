"""Atomic JSON configuration backup and rollback helpers."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class ConfigBackupError(ValueError):
    """Raised when a configuration cannot be safely backed up or restored."""


class ConfigBackup:
    """Keep versioned JSON snapshots outside the live configuration file."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def backup(self, source: str | Path) -> Path:
        source_path = Path(source)
        payload = self._read_json(source_path)
        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = (
            self.directory / f"{source_path.stem}-{timestamp}-{uuid4().hex[:8]}.json"
        )
        self._write_json(target, payload)
        return target

    def restore(self, backup: str | Path, target: str | Path) -> Path:
        payload = self._read_json(Path(backup))
        target_path = Path(target)
        self._write_json(target_path, payload)
        return target_path

    def list_backups(self) -> tuple[Path, ...]:
        if not self.directory.exists():
            return ()
        return tuple(sorted(self.directory.glob("*.json"), reverse=True))

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ConfigBackupError(f"invalid config JSON: {path}") from error
        if not isinstance(value, dict):
            raise ConfigBackupError("configuration root must be an object")
        return value

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
