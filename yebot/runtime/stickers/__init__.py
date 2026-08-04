"""Persistent, shared sticker collection and retrieval."""

from .caption_cache import (
    STICKER_CAPTION_PROMPT_VERSION,
    StickerCaptionCache,
    image_reference_fingerprint,
)
from .history import (
    HistoryImageSource,
    enrich_history_image_source,
    extract_history_image_sources,
)
from .models import StickerRecord
from .native import NativeSticker, NativeStickerClient, parse_native_sticker
from .service import (
    STICKER_IMAGE_REFS_EXTRA,
    StickerImageRef,
    StickerService,
    extract_image_components,
    extract_image_refs,
)
from .store import StickerStore

__all__ = [
    "StickerRecord",
    "StickerService",
    "StickerStore",
    "StickerImageRef",
    "STICKER_IMAGE_REFS_EXTRA",
    "NativeSticker",
    "NativeStickerClient",
    "extract_image_components",
    "extract_image_refs",
    "HistoryImageSource",
    "extract_history_image_sources",
    "enrich_history_image_source",
    "parse_native_sticker",
    "STICKER_CAPTION_PROMPT_VERSION",
    "StickerCaptionCache",
    "image_reference_fingerprint",
]
