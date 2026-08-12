"""Pure gates for automatic sticker reactions."""

from __future__ import annotations

from collections.abc import Mapping

from ..group_reply import has_meaningful_group_content


def should_queue_automatic_sticker(
    raw_event: object,
    *,
    response_text: str,
    current_text: str,
    observed_message_key: str,
    has_image: bool,
    group_reply_allowed: bool,
    observe_only: bool,
    background_mode: bool,
    background_tools_allowed: bool,
    blacklisted: bool,
    bot_id: str = "",
) -> bool:
    """Allow a reaction only for a real, answerable current group message."""

    if (
        observe_only
        or background_mode
        or background_tools_allowed
        or blacklisted
        or not group_reply_allowed
        or not response_text.strip()
    ):
        return False
    if not isinstance(raw_event, Mapping):
        return False
    if str(raw_event.get("post_type", "")).strip().lower() != "message":
        return False
    if str(raw_event.get("message_type", "")).strip().lower() != "group":
        return False
    message_key = automatic_sticker_key(raw_event)
    if not message_key or message_key != observed_message_key.strip():
        return False
    if not _text_id(raw_event.get("group_id")):
        return False
    if not _text_id(raw_event.get("message_id")):
        return False
    sender = raw_event.get("sender")
    if not isinstance(sender, Mapping):
        return False
    sender_id = _text_id(sender.get("user_id"), sender.get("qq"))
    bot_ids = {
        value
        for value in (_text_id(bot_id), _text_id(raw_event.get("self_id")))
        if value
    }
    if not sender_id or sender_id in bot_ids:
        return False
    return has_meaningful_group_content(current_text, has_non_text_content=has_image)


def automatic_sticker_key(raw_event: object) -> str:
    """Return a stable per-message key, or empty for synthetic events."""

    if not isinstance(raw_event, Mapping):
        return ""
    group_id = _text_id(raw_event.get("group_id"))
    message_id = _text_id(raw_event.get("message_id"))
    return f"{group_id}:{message_id}" if group_id and message_id else ""


def _text_id(*values: object) -> str:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
