"""Resolve a replied image into a temporary sticker reference."""

from __future__ import annotations

from collections.abc import Callable

from ..image_generation import ImageGenerationError, resolve_reply_image
from ..replies import ActionClient
from .service import StickerImageRef

ImageComponentFactory = Callable[[str], object | None]


async def resolve_replied_sticker_image(
    event: object,
    action_client: ActionClient | None,
    *,
    max_bytes: int,
    component_factory: ImageComponentFactory,
) -> StickerImageRef | None:
    """Read the first replied image and wrap it for the sticker service."""

    image = await resolve_reply_image(
        event,
        action_client,
        max_bytes=max_bytes,
    )
    if image is None:
        return None
    component = component_factory(image.data_url)
    if component is None:
        raise ImageGenerationError("replied sticker image data is invalid")
    return StickerImageRef(
        component,
        source_message_id=image.message_id,
        source_user_id=image.source_user_id,
        provider_url=image.data_url,
    )


def explicit_reply_collect_recent_shortcut(value: object) -> dict[str, object] | None:
    """Stop history collection when an explicit reply was already resolved."""

    if isinstance(value, StickerImageRef):
        return {
            "status": "success",
            "summary": (
                "history lookup skipped because the replied image is already "
                "attached; call yebot_sticker_consider once with image_index 0"
            ),
            "result": {
                "candidate_images": 1,
                "collected": False,
                "reason": "explicit_reply_already_attached",
                "next_tool": "yebot_sticker_consider",
                "image_index": 0,
            },
        }
    if value == "unreadable":
        return {
            "status": "success",
            "summary": "the replied image is unreadable; no history lookup was run",
            "result": {
                "candidate_images": 0,
                "collected": False,
                "reason": "quoted_image_unreadable",
            },
        }
    return None
