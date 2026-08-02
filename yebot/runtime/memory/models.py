"""Stable data contracts for scoped YeBot memories."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MemoryScope(StrEnum):
    """The owner of a memory record."""

    USER = "user"
    GROUP = "group"
    BOT = "bot"


class MemoryKind(StrEnum):
    """The meaning of one durable record."""

    FACT = "fact"
    PREFERENCE = "preference"
    RULE = "rule"
    SUMMARY = "summary"


class MemoryStatus(StrEnum):
    """Lifecycle state retained for history and soft deletion."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A bounded, structured memory without the original message body."""

    memory_id: str
    scope: MemoryScope
    scope_id: str
    subject_id: str
    topic: str
    kind: MemoryKind
    content: str
    tags: tuple[str, ...]
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    source_request_id: str = ""
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        memory_id = self.memory_id.strip()
        scope_id = self.scope_id.strip()
        subject_id = self.subject_id.strip()
        topic = " ".join(self.topic.split())
        content = " ".join(self.content.split())
        tags = tuple(
            dict.fromkeys(
                " ".join(tag.split()).lower() for tag in self.tags if tag.strip()
            )
        )
        confidence = float(self.confidence)
        if not memory_id or not scope_id or not topic or not content:
            raise ValueError("memory identity and content must not be empty")
        if len(topic) > 120 or len(content) > 1000:
            raise ValueError("memory content exceeds its bound")
        if any(len(tag) > 40 for tag in tags) or len(tags) > 10:
            raise ValueError("memory tags exceed their bound")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("memory confidence must be between 0 and 1")
        object.__setattr__(self, "memory_id", memory_id)
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "updated_at", _utc(self.updated_at))
        object.__setattr__(
            self, "expires_at", _utc(self.expires_at) if self.expires_at else None
        )
        object.__setattr__(self, "source_request_id", self.source_request_id.strip())
        object.__setattr__(
            self,
            "supersedes_id",
            self.supersedes_id.strip() if self.supersedes_id else None,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
