"""Input shaping for AstrBot's restricted sticker agent."""

from __future__ import annotations


def build_sticker_consider_arguments(
    *,
    should_collect: bool = False,
    asset_kind: str = "other",
    reaction_ready: bool = False,
    confidence: float = 0.0,
    meaning: str = "",
    tags: list[str] | None = None,
    image_index: float = 0.0,
) -> dict[str, object]:
    """Build a fail-closed argument payload for the sticker tool."""

    index: object = image_index
    if isinstance(image_index, float) and image_index.is_integer():
        index = int(image_index)
    arguments: dict[str, object] = {
        "should_collect": should_collect,
        "asset_kind": asset_kind,
        "reaction_ready": reaction_ready,
        "meaning": meaning,
        "image_index": index,
        "confidence": confidence,
    }
    if tags is not None:
        arguments["tags"] = tags
    return arguments
