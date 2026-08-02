"""NapCat's native custom-face actions and response normalization."""

from __future__ import annotations

import hashlib
import inspect
import logging
import re
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_LOGGER = logging.getLogger(__name__)


class ActionCallable(Protocol):
    """Callable shape exposed by AstrBot's OneBot adapter."""

    def __call__(self, action: str, **params: object) -> Awaitable[object] | object: ...


@dataclass(frozen=True, slots=True)
class NativeSticker:
    """Identifiers returned by NapCat for a personal custom face.

    Standard ``mface`` fields are available for some QQ/NapCat versions. The
    personal-emoji detail API used by the current deployment instead returns a
    resource ID and URL, which are still useful for native collection and image
    sending even though they cannot form an ``mface`` segment.
    """

    emoji_id: str
    emoji_package_id: int
    key: str
    res_id: str = ""
    md5: str = ""
    summary: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if not (self.emoji_id.strip() and self.key.strip()) and not (
            self.res_id.strip() or self.url.strip()
        ):
            raise ValueError("native sticker requires mface or personal-face fields")
        if self.emoji_package_id < 0:
            raise ValueError("native sticker package ID must be non-negative")

    @property
    def has_native_face(self) -> bool:
        """Whether the response contains the fields required by ``mface``."""

        return bool(self.emoji_id.strip() and self.key.strip())


class NativeStickerClient:
    """Call NapCat custom-face actions without coupling the store to OneBot."""

    def __init__(self, call_action: ActionCallable) -> None:
        self._call_action = call_action

    async def add(
        self, path: Path, *, md5: str = "", summary: str
    ) -> NativeSticker | None:
        normalized_md5 = md5.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{32}", normalized_md5):
            normalized_md5 = hashlib.md5(path.read_bytes()).hexdigest()
        response = await self._call(
            "add_custom_face",
            file=str(path),
            file_name=path.name,
            md5=normalized_md5,
            is_origin=True,
        )
        _LOGGER.info("native sticker add response=%s", _compact_response(response))
        candidate = parse_native_sticker(
            response, fallback_md5=normalized_md5, summary=summary
        )
        if candidate is not None:
            return candidate
        # Some NapCat versions return only a success flag from add_custom_face.
        # The detail action is the stable source of the identifiers needed to send.
        return await self._find_detail(normalized_md5)

    async def list_details(self, *, count: int = 48) -> tuple[NativeSticker, ...]:
        response = await self._call("fetch_custom_face_detail", count=count)
        _LOGGER.info("native sticker detail response=%s", _compact_response(response))
        return parse_native_stickers(response)

    async def _find_detail(self, md5: str) -> NativeSticker | None:
        normalized = md5.strip().lower()
        for item in await self.list_details():
            if item.md5 and item.md5.lower() == normalized:
                return item
        return None

    async def _call(self, action: str, **params: object) -> object:
        result = self._call_action(action, **params)
        if inspect.isawaitable(result):
            return await result
        return result


def parse_native_stickers(value: object) -> tuple[NativeSticker, ...]:
    """Extract native faces from NapCat's wrapper or list-shaped response."""

    candidates: list[NativeSticker] = []
    for item in _iter_mappings(value):
        parsed = parse_native_sticker(item)
        if parsed is not None and parsed not in candidates:
            candidates.append(parsed)
    return tuple(candidates)


def parse_native_sticker(
    value: object,
    *,
    fallback_md5: str = "",
    summary: str = "",
) -> NativeSticker | None:
    """Normalize camelCase/snake_case fields across NapCat releases."""

    mapping = _best_mapping(value)
    if mapping is None:
        return None
    emoji_id = _text(mapping, "emoji_id", "emojiId", "emojiID")
    key = _text(mapping, "key", "emoji_key", "emojiKey")
    package = _integer(
        mapping,
        "emoji_package_id",
        "emojiPackageId",
        "package_id",
        "packageId",
        "epId",
        default=0,
    )
    if package is None or package < 0:
        return None
    return NativeSticker(
        emoji_id=emoji_id,
        emoji_package_id=package,
        key=key,
        res_id=_text(mapping, "res_id", "resId", "resource_id", "resourceId"),
        md5=_text(mapping, "md5", "file_md5", "fileMd5") or fallback_md5,
        summary=_text(mapping, "summary", "faceName", "desc", "description") or summary,
        url=_text(mapping, "url", "image_url", "imageUrl"),
    )


def _iter_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        result.append(value)
        for key in (
            "data",
            "result",
            "emojiInfoList",
            "emoji_info_list",
            "emojiInfo",
            "emoji_info",
            "items",
        ):
            nested = value.get(key)
            result.extend(_iter_mappings(nested))
    elif isinstance(value, list | tuple):
        for item in value:
            result.extend(_iter_mappings(item))
    return tuple(result)


def _best_mapping(value: object) -> Mapping[str, object] | None:
    for mapping in _iter_mappings(value):
        has_mface = _text(mapping, "emoji_id", "emojiId", "emojiID") and _text(
            mapping, "key", "emoji_key", "emojiKey"
        )
        has_personal_face = _text(
            mapping, "res_id", "resId", "resource_id", "resourceId"
        ) or _text(mapping, "url", "image_url", "imageUrl")
        if has_mface or has_personal_face:
            return mapping
    return None


def _text(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str | int | float) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    return ""


def _integer(mapping: Mapping[str, object], *keys: str, default: int) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    return default


def _compact_response(value: object, *, limit: int = 1800) -> str:
    """Keep action diagnostics useful without dumping image payloads."""

    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}..."
