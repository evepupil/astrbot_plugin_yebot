"""Conservative intent detection for explicit replied-sticker saves."""

from __future__ import annotations

import re

_SAVE_MARKERS = (
    "保存",
    "收藏",
    "收录",
    "存一下",
    "存下",
    "收下",
    "加入表情包",
    "加到表情包",
    "加进表情包",
    "存到表情包",
)
_SAVE_NEGATIONS = (
    "不要保存",
    "别保存",
    "不用保存",
    "不再保存",
    "取消收藏",
    "删除",
    "清理",
    "移除",
)
_INFORMATION_QUESTION = re.compile(r"^(?:请问)?(?:怎么|如何|为什么|为啥|哪里|在哪)")
_INFORMATION_SUFFIXES = ("是什么意思", "什么意思")


def is_explicit_replied_sticker_save_request(text: str) -> bool:
    """Return whether current text explicitly asks to save a replied image."""

    normalized = re.sub(r"\s+", "", text.casefold())
    if (
        not normalized
        or _INFORMATION_QUESTION.match(normalized)
        or normalized.endswith(_INFORMATION_SUFFIXES)
        or any(marker in normalized for marker in _SAVE_NEGATIONS)
    ):
        return False
    return any(marker in normalized for marker in _SAVE_MARKERS)
