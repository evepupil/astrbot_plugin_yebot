"""Small, conservative checks for explicit memory-write requests."""

from dataclasses import dataclass

from .models import MemoryKind, MemoryScope

_WRITE_PREFIXES = (
    "请记住",
    "帮我记住",
    "我想让你记住",
    "记住",
    "记一下",
    "记下",
    "以后都",
    "以后请",
    "今后都",
    "今后请",
)
_QUESTION_SUFFIXES = ("吗", "么", "？", "?")
_TRIM_CHARS = " \t\r\n:：,，。;；"
_NON_REQUESTS = ("记住了", "记住啦", "记住没", "记住没有")


@dataclass(frozen=True, slots=True)
class MemoryWriteIntent:
    """A bounded write request extracted from an explicit user instruction."""

    scope: MemoryScope
    kind: MemoryKind
    topic: str
    content: str


def parse_explicit_memory_write_request(
    text: str,
    *,
    is_group_chat: bool = False,
) -> MemoryWriteIntent | None:
    """Extract a conservative write intent without treating ordinary chat as memory."""

    normalized = " ".join(text.split())
    if (
        not normalized
        or normalized in _NON_REQUESTS
        or normalized.endswith(_QUESTION_SUFFIXES)
    ):
        return None

    content = ""
    for prefix in sorted(_WRITE_PREFIXES, key=len, reverse=True):
        if normalized.startswith(prefix):
            content = normalized[len(prefix) :].lstrip(_TRIM_CHARS)
            break
    if not content:
        return None

    group_markers = ("本群", "群规", "当前群", "群里")
    bot_markers = ("机器人", "人设", "主人", "bot")
    preference_markers = ("喜欢", "偏好", "习惯", "回答", "回复", "风格")
    if is_group_chat:
        if any(marker in content for marker in group_markers + bot_markers):
            kind = MemoryKind.RULE
            topic = "群规"
        elif any(marker in content for marker in preference_markers):
            kind = MemoryKind.PREFERENCE
            topic = "群偏好"
        else:
            kind = MemoryKind.FACT
            topic = content[:120]
        return MemoryWriteIntent(MemoryScope.GROUP, kind, topic, content)

    if any(marker in content for marker in group_markers):
        scope = MemoryScope.GROUP
        kind = MemoryKind.RULE
        topic = "群规"
    elif any(marker in content for marker in bot_markers):
        scope = MemoryScope.BOT
        kind = MemoryKind.RULE
        topic = "机器人规则"
    elif any(marker in content for marker in preference_markers):
        scope = MemoryScope.USER
        kind = MemoryKind.PREFERENCE
        topic = "用户偏好"
    else:
        scope = MemoryScope.USER
        kind = MemoryKind.FACT
        topic = content[:120]
    return MemoryWriteIntent(scope, kind, topic, content)


def is_explicit_memory_write_request(
    text: str,
    *,
    is_group_chat: bool = False,
) -> bool:
    """Return whether text starts with an unambiguous memory-write request."""

    return (
        parse_explicit_memory_write_request(text, is_group_chat=is_group_chat)
        is not None
    )
