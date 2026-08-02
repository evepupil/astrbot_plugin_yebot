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
    emoji_id: str = ""
    emoji_package_id: int = 0
    key: str = ""
    res_id: str = ""
    md5: str = ""
    summary: str = ""
    native_url: str = ""

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
        if (
            not isinstance(self.emoji_package_id, int)
            or isinstance(self.emoji_package_id, bool)
            or self.emoji_package_id < 0
        ):
            raise ValueError("sticker emoji_package_id must be non-negative")
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
        object.__setattr__(self, "emoji_id", self.emoji_id.strip()[:256])
        object.__setattr__(self, "key", self.key.strip()[:512])
        object.__setattr__(self, "res_id", self.res_id.strip()[:512])
        object.__setattr__(self, "md5", self.md5.strip().lower()[:64])
        object.__setattr__(self, "summary", self.summary.strip()[:500])
        object.__setattr__(self, "native_url", self.native_url.strip()[:2048])

    @property
    def has_native_face(self) -> bool:
        """Whether NapCat can send this record as a native mface segment."""

        return bool(self.emoji_id and self.key)

    @property
    def has_native_asset(self) -> bool:
        """Whether QQ returned a native personal-face resource for this record."""

        return bool(self.has_native_face or self.res_id or self.native_url)


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
