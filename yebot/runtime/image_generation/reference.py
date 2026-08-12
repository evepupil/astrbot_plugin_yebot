"""Resolve a replied OneBot image into a bounded data URL."""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import ipaddress
import mimetypes
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..replies import ActionClient, extract_reply_references
from .client import ImageGenerationError

DEFAULT_MAX_REFERENCE_BYTES = 10_000_000
ImageDownloader = Callable[[str, int], tuple[bytes, str]]
_CQ_IMAGE_PATTERN = re.compile(r"\[CQ:image,([^\]]+)]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReplyImage:
    """One image attached to a replied message, ready for the edit API."""

    message_id: str
    data_url: str
    source_user_id: str = ""


async def resolve_reply_image(
    event: object,
    action_client: ActionClient | None,
    *,
    max_bytes: int = DEFAULT_MAX_REFERENCE_BYTES,
    downloader: ImageDownloader | None = None,
) -> ReplyImage | None:
    """Fetch the first image from the first replied message, if one exists."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    references = extract_reply_references(event)
    if not references:
        return None
    if action_client is None:
        raise ImageGenerationError("reply image action is unavailable")

    reference = references[0]
    try:
        response = await _call_action(
            action_client,
            "get_msg",
            message_id=_action_message_id(reference.message_id),
        )
    except Exception as error:
        raise ImageGenerationError("failed to read the replied message") from error

    last_error: ImageGenerationError | None = None
    for source in _extract_image_sources(response):
        try:
            data_url = await _resolve_source(
                source,
                action_client,
                max_bytes=max_bytes,
                downloader=downloader,
            )
        except ImageGenerationError as error:
            last_error = error
            continue
        if data_url is not None:
            return ReplyImage(
                reference.message_id,
                data_url,
                _message_sender_id(response),
            )
    if last_error is not None:
        raise ImageGenerationError("failed to read the replied image") from last_error
    return None


async def _resolve_source(
    source: str,
    action_client: ActionClient,
    *,
    max_bytes: int,
    downloader: ImageDownloader | None,
) -> str | None:
    normalized = source.strip()
    if not normalized:
        return None
    if normalized.lower().startswith("data:"):
        return _data_url_from_data_url(normalized, max_bytes)
    if normalized.lower().startswith("base64://"):
        return _data_url_from_base64(normalized[9:], "image/jpeg", max_bytes)

    parsed = urlparse(normalized)
    if parsed.scheme.lower() in {"http", "https"}:
        fetch = downloader or _download_image
        data, media_type = await asyncio.to_thread(fetch, normalized, max_bytes)
        return _data_url_from_bytes(data, media_type, max_bytes)
    if parsed.scheme:
        return None

    local = await asyncio.to_thread(_read_local_image, normalized, max_bytes)
    if local is not None:
        return local

    try:
        response = await _call_action(action_client, "get_image", file=normalized)
    except Exception as error:
        raise ImageGenerationError("failed to resolve the replied image") from error
    for nested_source in _extract_image_sources(response):
        resolved = await _resolve_source_without_action(
            nested_source,
            max_bytes=max_bytes,
            downloader=downloader,
        )
        if resolved is not None:
            return resolved
    return None


async def _resolve_source_without_action(
    source: str,
    *,
    max_bytes: int,
    downloader: ImageDownloader | None,
) -> str | None:
    normalized = source.strip()
    if normalized.lower().startswith("data:"):
        return _data_url_from_data_url(normalized, max_bytes)
    if normalized.lower().startswith("base64://"):
        return _data_url_from_base64(normalized[9:], "image/jpeg", max_bytes)
    parsed = urlparse(normalized)
    if parsed.scheme.lower() in {"http", "https"}:
        fetch = downloader or _download_image
        data, media_type = await asyncio.to_thread(fetch, normalized, max_bytes)
        return _data_url_from_bytes(data, media_type, max_bytes)
    if parsed.scheme:
        return None
    return await asyncio.to_thread(_read_local_image, normalized, max_bytes)


async def _call_action(
    action_client: ActionClient,
    action: str,
    **params: object,
) -> object:
    result = action_client.call_action(action, **params)
    return await result if inspect.isawaitable(result) else result


def _extract_image_sources(response: object) -> tuple[str, ...]:
    data: object = response
    if isinstance(response, Mapping):
        data = response.get("data", response)
    if isinstance(data, Mapping):
        direct = _image_sources(data)
        if direct:
            return direct
        message = data.get("message")
        if isinstance(message, list):
            sources = [
                source
                for segment in message
                for source in _segment_image_sources(segment)
            ]
            return tuple(sources)
        if isinstance(message, str):
            return _cq_image_sources(message)
        message_str = data.get("message_str")
        if isinstance(message_str, str):
            return _cq_image_sources(message_str)
    if isinstance(data, list):
        return tuple(
            source for segment in data for source in _segment_image_sources(segment)
        )
    if isinstance(data, str):
        return _cq_image_sources(data)
    return ()


def _segment_image_sources(segment: object) -> tuple[str, ...]:
    if not isinstance(segment, Mapping):
        return ()
    if str(segment.get("type", "")).lower() != "image":
        return ()
    data = segment.get("data")
    payload = data if isinstance(data, Mapping) else segment
    return _image_sources(payload)


def _image_sources(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    """Return usable image references in a recovery-friendly order.

    NapCat often includes both a remote ``url`` and a QQ ``file`` identifier.
    The remote URL may be unavailable from the AstrBot container, while
    ``get_image`` can still resolve the file through the OneBot connection.
    """

    sources: list[str] = []
    for key in (
        "file",
        "path",
        "url",
        "image_url",
        "base64",
        "base64_data",
        "base64Data",
    ):
        value = mapping.get(key)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        normalized = str(value).strip()
        if not normalized:
            continue
        if key in {"base64", "base64_data", "base64Data"} and not (
            normalized.lower().startswith("data:")
            or normalized.lower().startswith("base64://")
        ):
            normalized = f"base64://{normalized}"
        if normalized not in sources:
            sources.append(normalized)
    return tuple(sources)


def _cq_image_sources(message: str) -> tuple[str, ...]:
    sources: list[str] = []
    for match in _CQ_IMAGE_PATTERN.finditer(message):
        fields: dict[str, str] = {}
        for part in match.group(1).split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = _unescape_cq(value.strip())
        for key in ("file", "path", "url", "image_url"):
            source = fields.get(key)
            if source:
                sources.append(source)
                break
    return tuple(sources)


def _message_sender_id(response: object) -> str:
    data: object = response
    if isinstance(response, Mapping):
        data = response.get("data", response)
    if not isinstance(data, Mapping):
        return ""
    sender = data.get("sender")
    if not isinstance(sender, Mapping):
        return ""
    value = sender.get("user_id", sender.get("userId"))
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()[:64]
    return ""


def _unescape_cq(value: str) -> str:
    return (
        value.replace("&#44;", ",")
        .replace("&#91;", "[")
        .replace("&#93;", "]")
        .replace("&#38;", "&")
    )


def _action_message_id(message_id: str) -> object:
    return int(message_id) if message_id.isdecimal() else message_id


def _data_url_from_data_url(value: str, max_bytes: int) -> str:
    header, separator, encoded = value.partition(",")
    if not separator or ";base64" not in header.lower():
        raise ImageGenerationError("replied image data is invalid")
    media_type = header[5:].split(";", 1)[0].lower()
    if not media_type.startswith("image/"):
        raise ImageGenerationError("replied content is not an image")
    return _data_url_from_base64(encoded, media_type, max_bytes)


def _data_url_from_base64(
    encoded: str,
    media_type: str,
    max_bytes: int,
) -> str:
    try:
        data = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageGenerationError("replied image data is invalid") from error
    return _data_url_from_bytes(data, media_type, max_bytes)


def _data_url_from_bytes(data: bytes, media_type: str, max_bytes: int) -> str:
    if not data:
        raise ImageGenerationError("replied image is empty")
    if len(data) > max_bytes:
        raise ImageGenerationError("replied image is too large")
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if not normalized_type.startswith("image/"):
        raise ImageGenerationError("replied content is not an image")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{normalized_type};base64,{encoded}"


def _read_local_image(path: str, max_bytes: int) -> str | None:
    candidate = Path(path)
    try:
        if not candidate.is_file():
            return None
        data = candidate.read_bytes()
    except (OSError, ValueError):
        return None
    media_type = mimetypes.guess_type(str(candidate))[0] or "image/jpeg"
    if not media_type.startswith("image/"):
        return None
    return _data_url_from_bytes(data, media_type, max_bytes)


def _download_image(url: str, max_bytes: int) -> tuple[bytes, str]:
    _validate_remote_url(url)
    request = Request(url, headers={"User-Agent": "YeBot/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise ImageGenerationError("replied image is too large")
            data = response.read(max_bytes + 1)
            media_type = response.headers.get("Content-Type", "")
            if not media_type.split(";", 1)[0].strip().lower().startswith("image/"):
                media_type = mimetypes.guess_type(url)[0] or media_type
            if len(data) > max_bytes:
                raise ImageGenerationError("replied image is too large")
            return data, media_type
    except ImageGenerationError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise ImageGenerationError("failed to download the replied image") from error


def _validate_remote_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ImageGenerationError("replied image URL is invalid")
    if parsed.username or parsed.password:
        raise ImageGenerationError("replied image URL is invalid")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ImageGenerationError("replied image URL is not allowed")
