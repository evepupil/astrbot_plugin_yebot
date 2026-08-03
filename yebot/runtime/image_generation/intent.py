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


def extract_image_prompt(message: str) -> str | None:
    """Return the requested image description when ``message`` is imperative."""

    normalized = _CQ_CODE_PATTERN.sub(" ", message)
    normalized = " ".join(normalized.replace("\r", " ").splitlines()).strip()
    if not normalized:
        return None

    for pattern in _IMAGE_INTENT_PATTERNS:
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
