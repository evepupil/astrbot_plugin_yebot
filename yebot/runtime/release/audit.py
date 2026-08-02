"""Append-only, redacted audit output suitable for local operations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..guardrails.models import AuditEvent

_SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "cookie",
        "api_key",
        "access_token",
    }
)


class AuditLogWriter:
    """Write one redacted JSON object per line without retaining chat text."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event_id": event.event_id,
            "timestamp": event.timestamp.isoformat(),
            "actor_id": event.actor_id,
            "group_id": event.group_id,
            "tool_name": event.tool_name,
            "outcome": event.outcome,
            "request_id": event.request_id,
            "target_user_id": event.target_user_id,
            "details": redact_mapping(event.details),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """Remove common credential fields and truncate arbitrary values."""

    result: dict[str, object] = {}
    for key, item in value.items():
        normalized = key.strip().lower()
        if normalized in _SECRET_KEYS or any(
            secret in normalized for secret in _SECRET_KEYS
        ):
            result[key] = "[REDACTED]"
        elif isinstance(item, str):
            result[key] = item[:256]
        elif isinstance(item, (int, float, bool)) or item is None:
            result[key] = item
        else:
            result[key] = type(item).__name__
    return result
