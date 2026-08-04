"""Content-keyed caching for sticker image descriptions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from ..cache import AsyncTTLCache, CacheStats

STICKER_CAPTION_PROMPT_VERSION = "v2"
_DEFAULT_TTL_SECONDS = 86_400.0


class StickerCaptionCache:
    """Reuse successful descriptions for the same image/model/prompt tuple."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_entries: int = 512,
        prompt_version: str = STICKER_CAPTION_PROMPT_VERSION,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._prompt_version = prompt_version
        self._cache: AsyncTTLCache[tuple[str, str, str, str], str] = AsyncTTLCache(
            max_entries=max_entries
        )

    async def get_or_load(
        self,
        image_urls: Iterable[str],
        *,
        provider_id: str,
        model_id: str,
        loader: Callable[[], Awaitable[str]],
    ) -> str:
        """Return a cached caption or call ``loader`` once for concurrent users."""

        fingerprint = await image_reference_fingerprint(image_urls)
        key = (
            self._prompt_version,
            provider_id.strip(),
            model_id.strip(),
            fingerprint,
        )
        lookup = await self._cache.get_or_load(
            key,
            loader,
            ttl_seconds=self._ttl_seconds,
            cache_result=lambda value: bool(value.strip()),
        )
        return lookup.value

    def stats(self) -> CacheStats:
        """Expose counters without exposing image keys or descriptions."""

        return self._cache.stats()


async def image_reference_fingerprint(image_urls: Iterable[str]) -> str:
    """Hash image bytes when local, with stable URL/data fallback identities."""

    digests = await asyncio.gather(
        *(asyncio.to_thread(_reference_digest, value) for value in image_urls)
    )
    hasher = hashlib.sha256()
    for digest in digests:
        hasher.update(len(digest).to_bytes(4, "big"))
        hasher.update(digest)
    return hasher.hexdigest()


def _reference_digest(reference: str) -> bytes:
    normalized = reference.strip()
    if normalized.startswith("data:") and "," in normalized:
        encoded = normalized.split(",", 1)[1]
        try:
            return hashlib.sha256(base64.b64decode(encoded, validate=False)).digest()
        except (ValueError, TypeError):
            pass
    try:
        path = Path(normalized)
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        pass
    return hashlib.sha256(normalized.encode("utf-8")).digest()
