"""Data contracts for the local sticker library."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class StickerRecord:
    """A deduplicated image with the model's semantic description."""

    sticker_id: str
    digest: str
    relative_path: str
    media_type: str
    meaning: str
    tags: tuple[str, ...]
    group_id: str
    source_message_id: str
    source_user_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    use_count: int = 0

    def __post_init__(self) -> None:
        required = {
            "sticker_id": self.sticker_id,
            "digest": self.digest,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "meaning": self.meaning,
            "group_id": self.group_id,
        }
        if any(
            not isinstance(value, str) or not value.strip()
            for value in required.values()
        ):
            raise ValueError("sticker identity and meaning fields must not be empty")
        if self.use_count < 0:
            raise ValueError("sticker use_count must be non-negative")
        object.__setattr__(self, "sticker_id", self.sticker_id.strip())
        object.__setattr__(self, "digest", self.digest.strip().lower())
        object.__setattr__(self, "relative_path", self.relative_path.strip())
        object.__setattr__(self, "media_type", self.media_type.strip().lower())
        object.__setattr__(self, "meaning", self.meaning.strip()[:500])
        object.__setattr__(self, "tags", _clean_tags(self.tags))
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(
            self, "source_message_id", self.source_message_id.strip()[:128]
        )
        object.__setattr__(self, "source_user_id", self.source_user_id.strip()[:64])
        object.__setattr__(self, "created_at", _utc(self.created_at))


def _clean_tags(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = str(value).strip().lower()[:40]
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result[:20])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
