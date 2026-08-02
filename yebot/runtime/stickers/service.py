"""Bridge AstrBot image components to the persistent sticker store."""

from __future__ import annotations

import base64
import inspect
import logging
import mimetypes
from collections.abc import Mapping
from pathlib import Path

from ...domain.identity import Identity
from .models import StickerRecord
from .native import NativeStickerClient
from .store import StickerAddResult, StickerStore

_LOGGER = logging.getLogger(__name__)


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

    def __init__(
        self,
        store: StickerStore,
        native_client: NativeStickerClient | None = None,
    ) -> None:
        self.store = store
        self.native_client = native_client

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
        record, native_synced = await self.ensure_native(result.record)
        payload = _serialize_add(StickerAddResult(record, result.duplicate))
        payload["native_synced"] = native_synced
        return payload

    async def ensure_native(self, record: StickerRecord) -> tuple[StickerRecord, bool]:
        """Add one local record to QQ's custom-face library when needed."""

        if self.native_client is None or record.has_native_face:
            return record, False
        try:
            face = await self.native_client.add(
                self.store.file_path(record),
                md5=record.md5,
                summary=record.summary or record.meaning,
            )
        except Exception as error:
            _LOGGER.warning(
                "native sticker sync failed sticker=%s error=%s",
                record.sticker_id,
                type(error).__name__,
            )
            return record, False
        if face is None:
            _LOGGER.warning(
                "native sticker sync returned no identifiers sticker=%s",
                record.sticker_id,
            )
            return record, False
        updated = self.store.attach_native(
            record.sticker_id,
            emoji_id=face.emoji_id,
            emoji_package_id=face.emoji_package_id,
            key=face.key,
            res_id=face.res_id,
            md5=face.md5 or record.digest,
            summary=face.summary or record.meaning,
        )
        return (updated or record), updated is not None

    async def migrate_existing(self) -> tuple[int, int]:
        """Best-effort migration of old local stickers to QQ native storage."""

        if self.native_client is None:
            return 0, 0
        attempted = 0
        synced = 0
        for record in self.store.list_all():
            if record.has_native_face:
                continue
            attempted += 1
            _, did_sync = await self.ensure_native(record)
            synced += int(did_sync)
        return attempted, synced

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
        "native_available": record.has_native_face,
    }
