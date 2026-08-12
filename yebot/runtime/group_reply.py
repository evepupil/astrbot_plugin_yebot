"""Context-aware gates for ordinary group replies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GroupReplyReason(StrEnum):
    """Stable reasons for deciding whether a group message reaches the LLM."""

    DIRECT_ADDRESS = "direct_address"
    REPLY_TO_BOT = "reply_to_bot"
    EMPTY_CONTENT = "empty_content"
    NEEDS_JUDGEMENT = "needs_judgement"
    AI_ALLOW = "ai_allow"
    AI_DENY = "ai_deny"
    JUDGEMENT_UNAVAILABLE = "judgement_unavailable"


_CLARIFICATION_MARKERS = (
    "你这是在说什么",
    "你这是在说啥",
    "你在说什么鬼东西",
    "你在说什么鬼",
    "你在说什么",
    "你在说啥",
    "你说什么",
    "你说啥",
    "说的啥",
    "你想表达什么",
    "能说清楚吗",
    "具体说说",
    "详细说说",
    "说清楚点",
    "解释一下",
    "解释下",
    "没听懂",
    "听不懂",
    "没明白",
    "不明白",
    "不懂",
    "是什么意思",
    "什么意思",
    "啥意思",
    "这是什么",
    "这啥",
    "什么情况",
    "啥情况",
    "怎么回事",
    "咋回事",
    "怎么了",
    "咋了",
)
_CONFUSION_PREFIXES = (
    "我没听懂",
    "我听不懂",
    "我没明白",
    "我不明白",
    "我不懂",
)
_CLARIFICATION_CONNECTORS = ("能不能", "能否", "你能", "请", "可以")
_ANSWERING_MARKERS = (
    "解释",
    "意思是",
    "指的是",
    "指的就是",
    "简单说",
    "可以理解",
    "原因是",
    "因为",
    "答案是",
    "这里是",
    "也就是",
    "所谓",
)
_DEFINITION_QUESTION = re.compile(
    r"[\w\u3400-\u9fff]{1,32}(?:是什么意思|什么意思|是什么|是啥|啥意思)$",
    re.UNICODE,
)
_NO_RESPONSE_PLACEHOLDER = re.compile(
    r"(?:没有回应|没有回复|无人回应|无人回复)这是.{1,48}"
    r"(?:在|和|与|跟).{1,64}(?:互动|聊天|对话|交流|说话)(?:中)?$",
    re.UNICODE,
)
_IMAGE_NO_RESPONSE_PLACEHOLDER = re.compile(
    r"(?:"
    r"(?:图片|图像)(?:已经|已)?查看(?:完毕|完成)?"
    r"|(?:已经|已)?查看(?:了)?(?:图片|图像)"
    r")(?:暂时)?(?:没有|无)(?:需要|要|可)?回复(?:的)?内容$",
    re.UNICODE,
)
_BRACKETED_META_RESPONSE = re.compile(
    r"^\s*\[[^\[\]]+\]\s*$",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class GroupReplyDecision:
    """A transient, explainable decision for one group message."""

    should_call_llm: bool
    reason: GroupReplyReason
    needs_ai_judgement: bool = False


def astrbot_call_llm_flag(should_call_llm: bool) -> bool:
    """Convert our allow/deny decision to AstrBot's blocking flag."""

    return not should_call_llm


def _normalize_group_reply_text(text: str) -> str:
    normalized = re.sub(r"[\W_]+", "", text.casefold(), flags=re.UNICODE)
    return re.sub(r"[啊呀吗嘛呢哦哟诶哈]+", "", normalized)


def is_no_response_placeholder(text: str) -> bool:
    """Return whether text is a model-generated no-response meta message."""

    normalized = _normalize_group_reply_text(text)
    if not normalized or len(normalized) > 160:
        return False
    return any(
        pattern.fullmatch(normalized) is not None
        for pattern in (
            _NO_RESPONSE_PLACEHOLDER,
            _IMAGE_NO_RESPONSE_PLACEHOLDER,
        )
    )


def is_bracketed_meta_response(text: str) -> bool:
    """Return whether the whole response is wrapped in square brackets."""

    return _BRACKETED_META_RESPONSE.fullmatch(text) is not None


def is_contextless_clarification(text: str) -> bool:
    """Return whether text is only a short request for missing context."""

    normalized = _normalize_group_reply_text(text)
    if not normalized or len(normalized) > 80:
        return False
    if _DEFINITION_QUESTION.fullmatch(normalized):
        return True

    for prefix in _CONFUSION_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        remainder = normalized[len(prefix) :]
        for connector in _CLARIFICATION_CONNECTORS:
            if remainder.startswith(connector):
                remainder = remainder[len(connector) :]
                break
        if not remainder:
            return True
        for marker in sorted(_CLARIFICATION_MARKERS, key=len, reverse=True):
            remainder = remainder.replace(marker, "")
        return not remainder

    for marker in sorted(_CLARIFICATION_MARKERS, key=len, reverse=True):
        if normalized.startswith(marker):
            remainder = normalized[len(marker) :]
            return not any(cue in remainder for cue in _ANSWERING_MARKERS)

    remainder = normalized
    matched = False
    for marker in sorted(_CLARIFICATION_MARKERS, key=len, reverse=True):
        if marker in remainder:
            remainder = remainder.replace(marker, "")
            matched = True
    return matched and not remainder


def has_meaningful_group_content(
    text: str,
    *,
    has_non_text_content: bool = False,
) -> bool:
    """Return whether a message has content that could support a reply."""

    if has_non_text_content:
        return True
    normalized = re.sub(r"\s+", "", text)
    return bool(re.search(r"[\w\u3400-\u9fff]", normalized, re.UNICODE))


def initial_group_reply_decision(
    *,
    directly_addressed: bool,
    reply_to_bot: bool,
    current_text: str,
    has_non_text_content: bool = False,
) -> GroupReplyDecision:
    """Resolve cheap, high-confidence signals before asking the model."""

    if directly_addressed:
        return GroupReplyDecision(True, GroupReplyReason.DIRECT_ADDRESS)
    if reply_to_bot:
        return GroupReplyDecision(True, GroupReplyReason.REPLY_TO_BOT)
    if not has_meaningful_group_content(
        current_text,
        has_non_text_content=has_non_text_content,
    ):
        return GroupReplyDecision(False, GroupReplyReason.EMPTY_CONTENT)
    return GroupReplyDecision(
        False,
        GroupReplyReason.NEEDS_JUDGEMENT,
        needs_ai_judgement=True,
    )


def build_group_reply_judgement_prompt(
    current_text: str,
    reply_context: str,
    recent_context: str = "",
) -> str:
    """Build a bounded prompt for the context-only group reply judge."""

    current = current_text.strip()[:2400] or "[no text]"
    referenced = reply_context.strip()[:2400] or "[no quoted message]"
    recent = recent_context.strip()[:3600] or "[no recent group history]"
    return (
        "You are a quiet group-chat answerability gate for a QQ bot. Decide only "
        "whether the main assistant can give a useful answer from the information "
        "shown. Return one JSON object "
        'with exactly one boolean field: {"should_reply": true} or '
        '{"should_reply": false}. Do not answer the user.\n\n'
        "Allow when the current message, quoted message, or recent history gives "
        "enough concrete information for a useful response, even when nobody "
        "names the bot. Deny overheard chatter when it has no answerable point. "
        "Deny when the only plausible response would ask the user to explain "
        "what they mean, identify an undefined subject, or provide missing "
        "context. This includes short messages such as 'what are you talking "
        "about?', 'what is X?', 'what does X mean?', 'what does that mean?', "
        "or 'can you explain?'. A direct question addressed to the bot may be "
        "answered even when it asks for clarification.\n\n"
        f"Current message:\n{current}\n\n"
        f"Quoted reply context:\n{referenced}\n\n"
        f"Recent group history (sender labels include YeBot/member, QQ, nickname, "
        f"and group card when available):\n{recent}"
    )


def parse_group_reply_judgement(completion: str) -> bool | None:
    """Parse the judge output, failing closed when it is malformed."""

    text = completion.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is not None and match.group(0) not in candidates:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value: Any = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            decision = value.get("should_reply")
            if isinstance(decision, bool):
                return decision
    return None


def judgement_decision(value: bool | None) -> GroupReplyDecision:
    """Convert a parsed model result into a stable runtime decision."""

    if value is True:
        return GroupReplyDecision(True, GroupReplyReason.AI_ALLOW)
    if value is False:
        return GroupReplyDecision(False, GroupReplyReason.AI_DENY)
    return GroupReplyDecision(False, GroupReplyReason.JUDGEMENT_UNAVAILABLE)
