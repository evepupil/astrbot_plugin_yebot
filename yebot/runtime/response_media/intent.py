"""Parse explicit Chinese text/voice response preferences."""

from __future__ import annotations

import re

from .models import ResponseMode, ResponseModeIntent

_SPACE = re.compile(r"\s+")
_PERSIST_WORD = re.compile(r"(?:以后|之后|今后|默认|一直|总是)")
_CLEAR_WORD = re.compile(r"(?:清除|取消|删除|恢复默认|重置)")
_MEDIA_WORD = re.compile(r"(?:语音|文字|文本|打字)")
_REPLY_WORD = re.compile(r"(?:回复|回答|说|讲|发|念|朗读|读出来|说话)")


def parse_response_mode_intent(text: str) -> ResponseModeIntent:
    """Recognize only direct requests to control the bot's reply medium."""

    normalized = _SPACE.sub("", text.strip())
    if not normalized:
        return ResponseModeIntent()

    persistent = bool(_PERSIST_WORD.search(normalized))
    if _CLEAR_WORD.search(normalized) and (
        "偏好" in normalized
        or "回复方式" in normalized
        or "回复模式" in normalized
        or persistent
    ):
        return ResponseModeIntent(persist=True, clear_preference=True)

    if not _MEDIA_WORD.search(normalized):
        return ResponseModeIntent()
    if not persistent and not _REPLY_WORD.search(normalized):
        return ResponseModeIntent()

    has_voice = "语音" in normalized
    has_text = "文字" in normalized or "文本" in normalized or "打字" in normalized
    if has_voice and has_text:
        mode = ResponseMode.DUAL
    elif has_voice:
        mode = ResponseMode.VOICE
    elif has_text:
        mode = ResponseMode.TEXT
    else:
        return ResponseModeIntent()
    return ResponseModeIntent(mode=mode, persist=persistent)
