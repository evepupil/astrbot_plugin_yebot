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


@dataclass(frozen=True, slots=True)
class GroupReplyDecision:
    """A transient, explainable decision for one group message."""

    should_call_llm: bool
    reason: GroupReplyReason
    needs_ai_judgement: bool = False


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
        "You are a quiet group-chat reply gate for a QQ bot. Decide only whether "
        "the main assistant should answer this message. Return one JSON object "
        'with exactly one boolean field: {"should_reply": true} or '
        '{"should_reply": false}. Do not answer the user.\n\n'
        "Allow only when the current message and context show that the user is "
        "talking to this bot or continuing a conversation with it. A message "
        "that is merely overheard group chatter must be denied. Deny messages "
        "with no useful conversational content, including contextless requests "
        "such as 'what are you talking about?', 'what is X?', or 'what does X "
        "mean?'. A direct, concrete question addressed to the bot is allowed.\n\n"
        f"Current message:\n{current}\n\n"
        f"Quoted reply context:\n{referenced}\n\n"
        f"Recent group history (sender labels are redacted):\n{recent}"
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
