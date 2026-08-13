"""Bridge AstrBot image components to the persistent sticker store."""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from ...domain.identity import Identity
from .models import StickerKind, StickerRecord
from .native import NativeStickerClient
from .store import StickerAddResult, StickerStore

_LOGGER = logging.getLogger(__name__)
_COLLECTIBLE_STICKER_KINDS = frozenset(
    {
        StickerKind.MEME,
        StickerKind.REACTION_STICKER,
        StickerKind.CARTOON_REACTION,
    }
)
STICKER_IMAGE_REFS_EXTRA = "yebot.sticker.image_refs"


@dataclass(frozen=True, slots=True)
class StickerImageRef:
    """An image component plus its source message when it came from history."""

    component: object
    source_message_id: str = ""
    source_user_id: str = ""
    provider_url: str = ""


def extract_image_components(event: object) -> tuple[object, ...]:
    """Return image components without importing AstrBot internals in domain code."""

    return tuple(ref.component for ref in extract_image_refs(event))


def extract_image_refs(event: object) -> tuple[StickerImageRef, ...]:
    """Return current-event images or explicitly attached historical images."""

    get_extra = getattr(event, "get_extra", None)
    historical = get_extra(STICKER_IMAGE_REFS_EXTRA, ()) if callable(get_extra) else ()
    if isinstance(historical, (list, tuple)):
        attached = tuple(
            item for item in historical if isinstance(item, StickerImageRef)
        )
        if attached:
            return attached
    get_messages = getattr(event, "get_messages", None)
    messages = get_messages() if callable(get_messages) else ()
    if isinstance(messages, (list, tuple)):
        result = [
            StickerImageRef(component)
            for component in messages
            if _is_image_component(component)
        ]
        if result:
            return tuple(result)
    return ()


class StickerService:
    """Apply model decisions and return bounded metadata for Agent tool calls."""

    def __init__(
        self,
        store: StickerStore,
        native_client: NativeStickerClient | None = None,
        *,
        min_auto_collect_confidence: float = 0.9,
        native_sync_timeout_seconds: float = 3.0,
    ) -> None:
        if (
            not isfinite(min_auto_collect_confidence)
            or not 0 <= min_auto_collect_confidence <= 1
        ):
            raise ValueError("minimum sticker confidence must be between 0 and 1")
        if (
            not isfinite(native_sync_timeout_seconds)
            or native_sync_timeout_seconds <= 0
        ):
            raise ValueError("native sticker sync timeout must be positive")
        self.store = store
        self.native_client = native_client
        self.min_auto_collect_confidence = min_auto_collect_confidence
        self.native_sync_timeout_seconds = native_sync_timeout_seconds

    async def image_urls(self, event: object) -> tuple[str, ...]:
        """Resolve current image components into provider-readable local paths."""

        result: list[str] = []
        for ref in extract_image_refs(event):
            if ref.provider_url:
                result.append(ref.provider_url)
                continue
            component = ref.component
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
        asset_kind = _sticker_kind(arguments.get("asset_kind"))
        if asset_kind not in _COLLECTIBLE_STICKER_KINDS:
            return {
                "collected": False,
                "reason": "unsuitable_image_kind",
                "asset_kind": asset_kind.value,
            }
        if arguments.get("reaction_ready") is not True:
            return {"collected": False, "reason": "not_a_standalone_reaction"}
        confidence = _confidence(arguments.get("confidence"))
        if confidence < self.min_auto_collect_confidence:
            return {
                "collected": False,
                "reason": "confidence_below_threshold",
                "confidence": confidence,
                "minimum_confidence": self.min_auto_collect_confidence,
            }
        meaning = arguments.get("meaning", "")
        if not isinstance(meaning, str):
            raise ValueError("meaning must be a string")
        if should_collect and not meaning.strip():
            raise ValueError("meaning is required when collecting a sticker")
        index = arguments.get("image_index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("image_index must be a non-negative integer")
        refs = extract_image_refs(event)
        if index >= len(refs):
            return {
                "collected": False,
                "reason": "image_not_found",
                "image_count": len(refs),
            }
        ref = refs[index]
        blob, suffix, media_type = await _read_image_ref(ref)
        tags = arguments.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError("tags must be an array")
        result = self.store.add(
            blob,
            media_type=media_type,
            meaning=meaning,
            tags=(str(tag) for tag in tags if isinstance(tag, str)),
            group_id=identity.group_id,
            source_message_id=ref.source_message_id or _event_message_id(event),
            source_user_id=ref.source_user_id or identity.user_id,
            asset_kind=asset_kind,
            confidence=confidence,
            suffix=suffix,
        )
        native_pending = False
        try:
            record, native_synced = await asyncio.wait_for(
                self.ensure_native(result.record),
                timeout=self.native_sync_timeout_seconds,
            )
        except TimeoutError:
            record = result.record
            native_synced = False
            native_pending = self.native_client is not None
            _LOGGER.warning(
                "native sticker sync timed out after local save sticker=%s",
                record.sticker_id,
            )
        payload = _serialize_add(StickerAddResult(record, result.duplicate))
        payload["native_synced"] = native_synced
        payload["native_sync_pending"] = native_pending
        return payload

    def list_for_review(self, limit: int) -> object:
        return {
            "stickers": [
                _serialize_review_record(record)
                for record in self.store.list_recent(limit)
            ]
        }

    def delete(self, sticker_id: str) -> object:
        record = self.store.delete(sticker_id)
        return {
            "sticker_id": sticker_id.strip(),
            "deleted": record is not None,
            "meaning": record.meaning if record is not None else "",
        }

    def find_for_reply(self, message_id: str, message: object) -> StickerRecord | None:
        """Resolve a saved sticker from a YeBot message being replied to."""

        tracked = self.store.find_by_sent_message_id(message_id)
        if tracked is not None:
            return tracked
        records = self.store.list_all()
        for segment in _message_segments(message):
            segment_type = str(segment.get("type", "")).strip().lower()
            data = segment.get("data")
            payload = data if isinstance(data, Mapping) else {}
            if segment_type == "mface":
                match = _match_native_face(records, payload)
            elif segment_type == "image":
                match = _match_image(records, payload)
            else:
                continue
            if match is not None:
                return match
        return None

    async def ensure_native(self, record: StickerRecord) -> tuple[StickerRecord, bool]:
        """Add one local record to QQ's custom-face library when needed."""

        if self.native_client is None or record.has_native_asset:
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
        if face is None or not (face.has_native_face or face.res_id or face.url):
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
            native_url=face.url,
        )
        return (updated or record), updated is not None

    async def migrate_existing(self) -> tuple[int, int]:
        """Best-effort migration of old local stickers to QQ native storage."""

        if self.native_client is None:
            return 0, 0
        attempted = 0
        synced = 0
        for record in self.store.list_all():
            if record.has_native_asset:
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
        fallback = False
        if not records and query.strip():
            # The agent often describes the requested reaction with words that
            # are absent from the saved tags. Returning recent global
            # candidates gives it a chance to choose instead of treating the
            # library as empty.
            bounded_limit = max(1, min(limit, 20))
            records = self.store.list_recent(bounded_limit)
            fallback = bool(records)
        return {
            "count": len(records),
            "fallback": fallback,
            "stickers": [_serialize(record) for record in records],
        }

    def get_for_send(
        self, identity: Identity, sticker_id: str
    ) -> tuple[StickerRecord, Path]:
        record = self.store.get(sticker_id, group_id=identity.group_id)
        if record is None:
            raise KeyError("sticker not found")
        return record, self.store.file_path(record)

    def mark_used(
        self,
        identity: Identity,
        sticker_id: str,
        *,
        sent_message_id: str = "",
    ) -> StickerRecord:
        record = self.store.mark_used(
            sticker_id,
            group_id=identity.group_id,
            sent_message_id=sent_message_id,
        )
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


async def _read_image_ref(ref: StickerImageRef) -> tuple[bytes, str, str]:
    """Read a resolved reply data URL without another media download."""

    provider_url = ref.provider_url.strip()
    if provider_url.lower().startswith("data:image/"):
        header, separator, encoded = provider_url.partition(",")
        media_type = header[5:].split(";", 1)[0].strip().lower()
        if separator and ";base64" in header.lower():
            data = base64.b64decode(encoded, validate=True)
            suffix = mimetypes.guess_extension(media_type) or ".jpg"
            return data, suffix, media_type
    return await _read_image(ref.component)


def _event_message_id(event: object) -> str:
    message_obj = getattr(event, "message_obj", None)
    return str(getattr(message_obj, "message_id", "")).strip()[:128]


def _message_segments(value: object) -> tuple[Mapping[str, object], ...]:
    data: object = value
    if isinstance(value, Mapping):
        data = value.get("data", value)
    if not isinstance(data, Mapping):
        return ()
    message = data.get("message")
    if not isinstance(message, list):
        return ()
    return tuple(item for item in message if isinstance(item, Mapping))


def _match_native_face(
    records: tuple[StickerRecord, ...],
    payload: Mapping[str, object],
) -> StickerRecord | None:
    emoji_id = _reference_text(payload, "emoji_id", "emojiId", "emojiID")
    key = _reference_text(payload, "key", "emoji_key", "emojiKey")
    res_id = _reference_text(payload, "res_id", "resId", "resource_id", "resourceId")
    package = _reference_int(
        payload,
        "emoji_package_id",
        "emojiPackageId",
        "package_id",
        "packageId",
        "epId",
    )
    matches = [
        record
        for record in records
        if (
            emoji_id
            and key
            and record.has_native_face
            and record.emoji_id == emoji_id
            and record.key == key
            and (package is None or record.emoji_package_id == package)
        )
        or (res_id and record.res_id and record.res_id == res_id)
    ]
    return matches[0] if len(matches) == 1 else None


def _match_image(
    records: tuple[StickerRecord, ...],
    payload: Mapping[str, object],
) -> StickerRecord | None:
    reference = _reference_text(
        payload,
        "url",
        "image_url",
        "imageUrl",
        "file",
    )
    if not reference:
        return None
    normalized = _normalize_media_reference(reference)
    matches = [
        record
        for record in records
        if record.native_url
        and _normalize_media_reference(record.native_url) == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def _reference_text(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    return ""


def _reference_int(mapping: Mapping[str, object], *keys: str) -> int | None:
    value = _reference_text(mapping, *keys)
    return int(value) if value.isdecimal() else None


def _normalize_media_reference(value: str) -> str:
    return value.strip().split("?", 1)[0].rstrip("/")


def _is_image_component(component: object) -> bool:
    component_type = str(getattr(component, "type", "")).lower()
    return (
        component_type in {"image", "componenttype.image"}
        or type(component).__name__.lower() == "image"
    )


def _sticker_kind(value: object) -> StickerKind:
    if not isinstance(value, str):
        raise ValueError("asset_kind must be a string")
    try:
        return StickerKind(value.strip().lower())
    except ValueError as error:
        raise ValueError("asset_kind is invalid") from error


def _confidence(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("confidence must be numeric")
    confidence = float(value)
    if not isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


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
        "asset_kind": record.asset_kind.value,
        "confidence": record.confidence,
        "native_available": record.has_native_asset,
    }


def _serialize_review_record(record: StickerRecord) -> dict[str, object]:
    value = _serialize(record)
    value["created_at"] = record.created_at.isoformat()
    return value
