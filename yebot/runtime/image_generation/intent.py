"""Recognize explicit natural-language image-generation requests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...domain.identity import is_bot_mentioned

_CQ_CODE_PATTERN = re.compile(r"\[CQ:[^\]]+]", re.IGNORECASE)
_IMAGE_INTENT_PATTERNS = (
    re.compile(
        r"^(?:请帮我|帮我|麻烦你|麻烦|请你|请|给我|替我|我想(?:要)?(?:让你)?|想要|来|整)?"
        r"\s*(?:画|绘制|描绘|生图|生成(?:一张|一幅|一副)?|做图|做一张图|来一张|整一张)"
        r"\s*(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:draw|generate\s+(?:an?\s+)?image|create\s+(?:an?\s+)?image)"
        r"\s+(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
)
_IMAGE_EDIT_PATTERNS = (
    re.compile(
        r"^(?:把|將|将)?\s*(?:这张|這張|这幅|這幅|该|該|它|原|参考|參考)?"
        r"(?:图|圖|图片|圖片)?\s*"
        r"(?:改成|改为|改為|变成|變成|重绘成|重繪成|重绘为|重繪為|换成|換成|"
        r"修改成|修改为|修改為)\s*(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:以|按照|根据|根據)\s*(?:这张图|這張圖|原图|原圖|参考图|參考圖)"
        r"\s*(?:为参考|為參考)?[，,:\s]*(?:生成|画成|畫成|重绘|重繪)?"
        r"[，,:\s]*(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:edit|transform|restyle)\s+(?:this\s+image\s+)?"
        r"(?:into|as)\s+(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
)


def _normalize_image_request(message: str) -> str:
    normalized = _CQ_CODE_PATTERN.sub(" ", message)
    return " ".join(normalized.replace("\r", " ").splitlines()).strip()


def extract_image_prompt(message: str) -> str | None:
    """Return the requested image description when ``message`` is imperative."""

    normalized = _normalize_image_request(message)
    if not normalized:
        return None

    for pattern in _IMAGE_INTENT_PATTERNS:
        match = pattern.match(normalized)
        if match is None:
            continue
        prompt = match.group("prompt").strip()
        return prompt[:32_000] or None
    return None


def extract_image_edit_prompt(message: str) -> str | None:
    """Return an explicit transformation description for a referenced image."""

    normalized = _normalize_image_request(message)
    if not normalized:
        return None

    for pattern in _IMAGE_EDIT_PATTERNS:
        match = pattern.match(normalized)
        if match is None:
            continue
        prompt = match.group("prompt").strip()
        return prompt[:32_000] or None
    return None


def is_group_image_request_addressed(
    raw_event: Mapping[str, Any],
    bot_id: str,
) -> bool:
    """Require an explicit bot mention before handling a group image request."""

    return is_bot_mentioned(raw_event, bot_id)
