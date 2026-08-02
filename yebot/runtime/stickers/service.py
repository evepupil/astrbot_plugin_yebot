"""Bridge AstrBot image components to the persistent sticker store."""

from __future__ import annotations

import base64
import inspect
import mimetypes
from collections.abc import Mapping
from pathlib import Path

from ...domain.identity import Identity
from .models import StickerRecord
from .store import StickerAddResult, StickerStore


def extract_image_components(event: object) -> tuple[object, ...]:
    """Return image components without importing AstrBot internals in domain code."""

    get_messages = getattr(event, "get_messages", None)
    messages = get_messages() if callable(get_messages) else ()
    if not isinstance(messages, (list, tuple)):
        return ()
    result: list[object] = []
    for component in messages:
        component_type = str(getattr(component, "type", "")).lower()
        if (
            component_type in {"image", "componenttype.image"}
            or type(component).__name__.lower() == "image"
        ):
            result.append(component)
    return tuple(result)


class StickerService:
    """Apply model decisions and return bounded metadata for Agent tool calls."""

    def __init__(self, store: StickerStore) -> None:
        self.store = store

    async def image_urls(self, event: object) -> tuple[str, ...]:
        """Resolve current image components into provider-readable local paths."""

        result: list[str] = []
        for component in extract_image_components(event):
            path_method = getattr(component, "convert_to_file_path", None)
            if callable(path_method):
                candidate = path_method()
                path_value = (
                    await candidate if inspect.isawaitable(candidate) else candidate
                )
                if isinstance(path_value, str) and path_value:
                    result.append(path_value)
                    continue
            base64_method = getattr(component, "convert_to_base64", None)
            if not callable(base64_method):
                continue
            candidate = base64_method()
            encoded = await candidate if inspect.isawaitable(candidate) else candidate
            if isinstance(encoded, str) and encoded:
                result.append(
                    f"data:image/jpeg;base64,{encoded.removeprefix('base64://')}"
                )
        return tuple(result)

    async def consider(
        self,
        event: object,
        identity: Identity,
        arguments: Mapping[str, object],
    ) -> object:
        should_collect = arguments.get("should_collect")
        if not isinstance(should_collect, bool):
            raise ValueError("should_collect must be a boolean")
        if not should_collect:
            return {"collected": False, "reason": "model_decided_not_useful"}
        meaning = arguments.get("meaning", "")
        if not isinstance(meaning, str):
            raise ValueError("meaning must be a string")
        if should_collect and not meaning.strip():
            raise ValueError("meaning is required when collecting a sticker")
        index = arguments.get("image_index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("image_index must be a non-negative integer")
        components = extract_image_components(event)
        if index >= len(components):
            return {
                "collected": False,
                "reason": "image_not_found",
                "image_count": len(components),
            }
        blob, suffix, media_type = await _read_image(components[index])
        tags = arguments.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError("tags must be an array")
        result = self.store.add(
            blob,
            media_type=media_type,
            meaning=meaning,
            tags=(str(tag) for tag in tags if isinstance(tag, str)),
            group_id=identity.group_id,
            source_message_id=_event_message_id(event),
            source_user_id=identity.user_id,
            suffix=suffix,
        )
        return _serialize_add(result)

    def search(self, identity: Identity, arguments: Mapping[str, object]) -> object:
        query = arguments.get("query", "")
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        records = self.store.search(query, group_id=identity.group_id, limit=limit)
        return {
            "count": len(records),
            "stickers": [_serialize(record) for record in records],
        }

    def get_for_send(
        self, identity: Identity, sticker_id: str
    ) -> tuple[StickerRecord, Path]:
        record = self.store.get(sticker_id, group_id=identity.group_id)
        if record is None:
            raise KeyError("sticker not found")
        return record, self.store.file_path(record)

    def mark_used(self, identity: Identity, sticker_id: str) -> StickerRecord:
        record = self.store.mark_used(sticker_id, group_id=identity.group_id)
        if record is None:
            raise KeyError("sticker not found")
        return record


async def _read_image(component: object) -> tuple[bytes, str, str]:
    path_method = getattr(component, "convert_to_file_path", None)
    path: str | None = None
    if callable(path_method):
        candidate = path_method()
        path_value = await candidate if inspect.isawaitable(candidate) else candidate
        if isinstance(path_value, str) and path_value:
            path = path_value
    if path is not None:
        data = Path(path).read_bytes()
        suffix = Path(path).suffix.lower() or ".jpg"
    else:
        base64_method = getattr(component, "convert_to_base64", None)
        if not callable(base64_method):
            raise ValueError("image source is unavailable")
        candidate = base64_method()
        encoded = await candidate if inspect.isawaitable(candidate) else candidate
        if not isinstance(encoded, str):
            raise ValueError("image base64 source is invalid")
        data = base64.b64decode(encoded.removeprefix("base64://"), validate=True)
        suffix = ".jpg"
    media_type = mimetypes.guess_type(f"image{suffix}")[0] or "image/jpeg"
    if not media_type.startswith("image/"):
        raise ValueError("sticker source is not an image")
    return data, suffix, media_type


def _event_message_id(event: object) -> str:
    message_obj = getattr(event, "message_obj", None)
    return str(getattr(message_obj, "message_id", "")).strip()[:128]


def _serialize_add(result: StickerAddResult) -> dict[str, object]:
    return {
        "collected": True,
        "duplicate": result.duplicate,
        "sticker": _serialize(result.record),
    }


def _serialize(record: StickerRecord) -> dict[str, object]:
    return {
        "sticker_id": record.sticker_id,
        "meaning": record.meaning,
        "tags": list(record.tags),
        "media_type": record.media_type,
        "use_count": record.use_count,
        "source_group_id": record.group_id,
    }
