"""Extract image references from bounded OneBot group message history."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ...domain.identity import normalize_id

_CQ_IMAGE_PATTERN = re.compile(r"\[CQ:image,(?P<attributes>[^\]]+)\]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class HistoryImageSource:
    """A historical image before it is converted to an AstrBot component."""

    message_id: str
    source_user_id: str
    url: str = ""
    path: str = ""
    file: str = ""
    base64_data: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", normalize_id(self.message_id))
        object.__setattr__(self, "source_user_id", normalize_id(self.source_user_id))
        object.__setattr__(self, "url", _clean(self.url, 2048))
        object.__setattr__(self, "path", _clean(self.path, 2048))
        object.__setattr__(self, "file", _clean(self.file, 512))
        object.__setattr__(self, "base64_data", _clean(self.base64_data, 16_000_000))

    @property
    def has_preview(self) -> bool:
        """Whether this source can be given to an image-capable provider."""

        return bool(self.url or self.path or self.base64_data)


def extract_history_image_sources(
    response: object,
    *,
    current_message_id: str = "",
    max_images: int = 8,
) -> tuple[HistoryImageSource, ...]:
    """Return the newest bounded image references, excluding the current event."""

    limit = max(1, min(int(max_images), 12))
    current = normalize_id(current_message_id)
    messages = _message_list(response)
    ordered = sorted(messages, key=_message_time, reverse=True)
    result: list[HistoryImageSource] = []
    seen: set[tuple[str, str]] = set()
    for message in ordered:
        message_id = normalize_id(message.get("message_id"))
        if not message_id or message_id == current:
            continue
        sender = message.get("sender")
        sender_map = sender if isinstance(sender, Mapping) else {}
        user_id = normalize_id(sender_map.get("user_id"))
        for source in _message_images(message, message_id, user_id):
            identity = (
                source.message_id,
                source.url or source.path or source.file or source.base64_data[:64],
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(source)
            if len(result) >= limit:
                return tuple(result)
    return tuple(result)


def enrich_history_image_source(
    source: HistoryImageSource,
    response: object,
) -> HistoryImageSource:
    """Merge a OneBot ``get_image`` result into an existing source."""

    details = _source_from_mapping(_unwrap_mapping(response))
    if details is None:
        return source
    return replace(
        source,
        url=details.url or source.url,
        path=details.path or source.path,
        file=details.file or source.file,
        base64_data=details.base64_data or source.base64_data,
    )


def _message_list(response: object) -> list[Mapping[str, object]]:
    data = response.get("data", response) if isinstance(response, Mapping) else response
    if isinstance(data, Mapping):
        messages = data.get("messages", data.get("message", data))
    else:
        messages = data
    if not isinstance(messages, list):
        return []
    return [item for item in messages if isinstance(item, Mapping)]


def _message_images(
    message: Mapping[str, object], message_id: str, source_user_id: str
) -> tuple[HistoryImageSource, ...]:
    chain = message.get("message")
    if isinstance(chain, list):
        result: list[HistoryImageSource] = []
        for segment in chain:
            if not isinstance(segment, Mapping):
                continue
            if str(segment.get("type", "")).strip().lower() != "image":
                continue
            data = segment.get("data")
            source = _source_from_mapping(data if isinstance(data, Mapping) else {})
            if source is not None:
                result.append(
                    replace(
                        source,
                        message_id=message_id,
                        source_user_id=source_user_id,
                    )
                )
        return tuple(result)
    if isinstance(chain, str):
        return tuple(
            replace(source, message_id=message_id, source_user_id=source_user_id)
            for source in _cq_images(chain)
        )
    return ()


def _cq_images(value: str) -> tuple[HistoryImageSource, ...]:
    result: list[HistoryImageSource] = []
    for match in _CQ_IMAGE_PATTERN.finditer(value):
        attributes: dict[str, str] = {}
        for item in match.group("attributes").split(","):
            key, separator, raw_value = item.partition("=")
            if separator:
                attributes[key.strip().lower()] = raw_value.strip()
        source = _source_from_mapping(attributes)
        if source is not None:
            result.append(source)
    return tuple(result)


def _source_from_mapping(value: Mapping[str, object]) -> HistoryImageSource | None:
    url = _first(value, "url", "image_url", "imageUrl")
    path = _first(value, "path", "local_path", "localPath")
    file = _first(value, "file", "file_id", "fileId")
    base64_data = _first(value, "base64", "base64_data", "base64Data")
    if not url and path.startswith(("http://", "https://", "data:")):
        url, path = path, ""
    if not url and file.startswith(("http://", "https://", "data:")):
        url, file = file, ""
    if url.startswith(("http://", "https://", "data:")):
        return HistoryImageSource(
            "", "", url=url, path=path, file=file, base64_data=base64_data
        )
    if path or file or base64_data:
        return HistoryImageSource("", "", path=path, file=file, base64_data=base64_data)
    return None


def _unwrap_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        data = value.get("data")
        if isinstance(data, Mapping):
            return data
        return value
    return {}


def _first(value: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (str, int, float)) and not isinstance(candidate, bool):
            text = str(candidate).strip()
            if text:
                return text
    return ""


def _message_time(message: Mapping[str, object]) -> float:
    value = message.get("time")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _clean(value: str, limit: int) -> str:
    return value.strip()[:limit]
