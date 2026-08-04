"""Pure parsers for natural-language job requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class ReminderIntent:
    """A validated reminder request extracted from one user message."""

    delay_seconds: int
    message: str
    target_user_id: str | None = None
    target_hint: str = ""


@dataclass(frozen=True, slots=True)
class ReminderParse:
    """Parser output that distinguishes an unrelated message from bad input."""

    intent: ReminderIntent | None
    error: str | None = None

    @property
    def is_request(self) -> bool:
        return self.intent is not None or self.error is not None


_REMINDER_WORDS = re.compile(r"(?:提醒|通知|叫醒)")
_TIME_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>秒|分钟|分|小时|时|天|日|周)\s*(?P<after>后)?"
)
_MENTION_PATTERN = re.compile(
    r"(?:\[CQ:at,qq=(?P<cq>\d+)[^\]]*\]|\[At:(?P<astr>\d+)\]|@(?P<plain>\d+))"
)
_TARGET_WORD_PATTERN = re.compile(
    r"^(?:某人|某个(?:人|群友)|我|你|他|她|ta|TA|这个人)\s*"
)
_REMINDER_START_PATTERN = re.compile(r"^(?:定时\s*)?(?:提醒|通知|叫醒)")
_POLITE_PREFIX = re.compile(r"^(?:请|帮我|麻烦|拜托)\s*")

_UNIT_SECONDS = {
    "秒": Decimal(1),
    "分": Decimal(60),
    "分钟": Decimal(60),
    "时": Decimal(3600),
    "小时": Decimal(3600),
    "天": Decimal(86400),
    "日": Decimal(86400),
    "周": Decimal(604800),
}


def parse_reminder_request(
    text: str,
    *,
    mentioned_user_ids: tuple[str, ...] = (),
) -> ReminderParse:
    """Parse a bounded Chinese reminder command.

    A request is considered explicit when it contains a reminder verb and a
    relative duration such as ``10 分钟后``. The parser deliberately refuses
    absolute dates and missing arguments so the caller can ask for the missing
    detail instead of inventing a schedule.
    """

    normalized = _clean_text(text)
    if not _REMINDER_WORDS.search(normalized):
        return ReminderParse(None)

    time_match = _TIME_PATTERN.search(normalized)
    if time_match is None and not _REMINDER_START_PATTERN.match(normalized):
        return ReminderParse(None)
    if time_match is None:
        return ReminderParse(None, "time_missing")

    try:
        amount = Decimal(time_match.group("number"))
        delay = int(amount * _UNIT_SECONDS[time_match.group("unit")])
    except (InvalidOperation, KeyError):
        return ReminderParse(None, "time_invalid")
    if delay < 1 or delay > 2_592_000:
        return ReminderParse(None, "time_out_of_range")

    command_match = _REMINDER_WORDS.search(normalized)
    assert command_match is not None
    command_start = command_match.start()
    command_end = command_match.end()
    time_start = time_match.start()
    time_end = time_match.end()

    if command_end <= time_start:
        # ``提醒 @某人 10 分钟后 开会``
        target_text = normalized[command_end:time_start]
        message = normalized[time_end:]
    elif time_end <= command_start:
        # ``10 分钟后提醒 @某人 开会``
        target_text = ""
        message = normalized[command_end:]
    else:
        return ReminderParse(None, "syntax_invalid")

    target_ids = tuple(
        dict.fromkeys(value.strip() for value in mentioned_user_ids if value.strip())
    )
    if len(target_ids) > 1:
        return ReminderParse(None, "multiple_targets")
    target_user_id = target_ids[0] if target_ids else None

    target_text = _MENTION_PATTERN.sub(" ", target_text)
    target_hint = target_text.strip()
    message = _MENTION_PATTERN.sub(" ", message)
    message = _TARGET_WORD_PATTERN.sub("", message.strip())
    if not message:
        return ReminderParse(None, "message_missing")

    if target_user_id is not None:
        message = f"[CQ:at,qq={target_user_id}] {message}"
    return ReminderParse(
        ReminderIntent(delay, message, target_user_id, target_hint),
    )


def _clean_text(text: str) -> str:
    """Normalize user text while retaining the words needed by the parser."""

    value = text.strip()
    if not value:
        return ""
    value = _MENTION_PATTERN.sub(" ", value)
    value = _POLITE_PREFIX.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
