"""Atomic local persistence for per-QQ response-medium preferences."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ...domain.identity import normalize_id
from .models import ResponseMode


class ResponseModeStore:
    """Keep one optional text, voice, or dual preference for each QQ account."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._modes: dict[str, ResponseMode] = {}
        self._load()

    def get(self, user_id: str) -> ResponseMode | None:
        return self._modes.get(normalize_id(user_id))

    def set(self, user_id: str, mode: ResponseMode) -> None:
        normalized_user_id = normalize_id(user_id)
        if not normalized_user_id:
            raise ValueError("user_id must not be empty")
        self._modes[normalized_user_id] = mode
        self._flush()

    def clear(self, user_id: str) -> bool:
        removed = self._modes.pop(normalize_id(user_id), None) is not None
        if removed:
            self._flush()
        return removed

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            modes = payload.get("modes", {}) if isinstance(payload, dict) else {}
            if not isinstance(modes, dict):
                return
            for user_id, raw_mode in modes.items():
                normalized_user_id = normalize_id(user_id)
                if not normalized_user_id or not isinstance(raw_mode, str):
                    continue
                try:
                    self._modes[normalized_user_id] = ResponseMode(raw_mode)
                except ValueError:
                    continue
        except (OSError, TypeError, ValueError):
            self._modes = {}

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "modes": {
                user_id: mode.value for user_id, mode in sorted(self._modes.items())
            },
        }
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
