"""Helpers for suppressing a model reply already sent through a tool."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_OUTBOUND_AT = re.compile(
    r"\[CQ:at,qq=\d+(?:,[^\]]*)?\]"
    r"|\[At:\d+\]",
    re.IGNORECASE,
)


def normalize_sent_message(text: str) -> str:
    """Normalize one outbound message for a conservative duplicate check."""

    return " ".join(_OUTBOUND_AT.sub(" ", text).split())[:4000]


def is_duplicate_response(response_text: str, sent_texts: Iterable[str]) -> bool:
    """Return whether the final response repeats a successfully sent message."""

    normalized_response = normalize_sent_message(response_text)
    if not normalized_response:
        return False
    return any(
        normalized_response == normalize_sent_message(sent_text)
        for sent_text in sent_texts
        if isinstance(sent_text, str)
    )


def is_successful_message_send(value: object) -> bool:
    """Recognize a real ``message.send`` result, excluding dry runs."""

    if not getattr(value, "ok", False):
        return False
    payload = getattr(value, "value", None)
    if not (
        isinstance(payload, Mapping)
        and payload.get("action") == "send_group_msg"
        and payload.get("dry_run") is False
    ):
        return False
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return False
    status = result.get("status")
    retcode = result.get("retcode")
    if status == "failed" or (retcode is not None and retcode != 0):
        return False
    if status is not None and status != "ok":
        return False
    return (
        status == "ok"
        or retcode == 0
        or isinstance(result.get("message_id"), (str, int))
    )
