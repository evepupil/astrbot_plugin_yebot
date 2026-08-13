"""Persistent, shared sticker collection and retrieval."""

from .agent import (
    build_sticker_consider_arguments,
    reserve_automatic_sticker_search,
)
from .auto import (
    automatic_sticker_key,
    is_registered_automatic_sticker_event,
    release_automatic_sticker_run,
    reserve_automatic_sticker_event,
    reserve_automatic_sticker_run,
    reserve_automatic_sticker_send_attempt,
    should_queue_automatic_sticker,
)
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
from .intent import is_explicit_replied_sticker_save_request
from .models import StickerRecord
from .native import NativeSticker, NativeStickerClient, parse_native_sticker
from .reply import (
    explicit_reply_collect_recent_shortcut,
    resolve_replied_sticker_image,
)
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
    "explicit_reply_collect_recent_shortcut",
    "resolve_replied_sticker_image",
    "HistoryImageSource",
    "extract_history_image_sources",
    "enrich_history_image_source",
    "parse_native_sticker",
    "STICKER_CAPTION_PROMPT_VERSION",
    "StickerCaptionCache",
    "image_reference_fingerprint",
    "build_sticker_consider_arguments",
    "is_explicit_replied_sticker_save_request",
    "reserve_automatic_sticker_search",
    "automatic_sticker_key",
    "is_registered_automatic_sticker_event",
    "release_automatic_sticker_run",
    "reserve_automatic_sticker_event",
    "reserve_automatic_sticker_run",
    "reserve_automatic_sticker_send_attempt",
    "should_queue_automatic_sticker",
]
