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
    observed_event_token: str,
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
    if not observed_event_token.strip():
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


def reserve_automatic_sticker_event(
    consumed_tokens: set[str],
    token: str,
    *,
    max_tokens: int = 4096,
) -> bool:
    """Allow one automatic reaction reservation for one observed event."""

    normalized = token.strip()
    if not normalized or normalized in consumed_tokens:
        return False
    if len(consumed_tokens) >= max(1, max_tokens):
        consumed_tokens.clear()
    consumed_tokens.add(normalized)
    return True


def is_registered_automatic_sticker_event(
    raw_event: object,
    *,
    observed_message_key: str,
    observed_event_token: str,
    bot_id: str = "",
) -> bool:
    """Check that a reaction still belongs to one current human group event."""

    if not isinstance(raw_event, Mapping):
        return False
    if str(raw_event.get("post_type", "")).strip().lower() != "message":
        return False
    if str(raw_event.get("message_type", "")).strip().lower() != "group":
        return False
    message_key = automatic_sticker_key(raw_event)
    if (
        not message_key
        or message_key != observed_message_key.strip()
        or not observed_event_token.strip()
        or not observed_event_token.strip().startswith(f"{message_key}:")
    ):
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
    return bool(sender_id and sender_id not in bot_ids)


def reserve_automatic_sticker_run(state: dict[str, bool]) -> bool:
    """Keep automatic sticker agents from forming a delayed backlog."""

    if state.get("active", False):
        return False
    state["active"] = True
    return True


def reserve_automatic_sticker_send_attempt(state: dict[str, bool]) -> bool:
    """Allow one send-tool attempt in one automatic reaction run."""

    if state.get("send_attempted", False):
        return False
    state["send_attempted"] = True
    return True


def release_automatic_sticker_run(state: dict[str, bool]) -> None:
    """Release the single automatic sticker agent slot."""

    state["active"] = False


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
