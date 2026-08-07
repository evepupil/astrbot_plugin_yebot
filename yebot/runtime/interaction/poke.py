"""Parse OneBot poke notifications into a safe event summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...domain.identity import normalize_id


@dataclass(frozen=True, slots=True)
class PokeEvent:
    """The minimum facts needed to route a poke without retaining raw payloads."""

    sender_id: str
    target_id: str
    group_id: str
    self_id: str
    sender_name: str = ""
    sender_card: str = ""
    message_type: str = "group"

    @property
    def is_group(self) -> bool:
        return bool(self.group_id)

    @property
    def is_targeting_self(self) -> bool:
        return bool(self.self_id) and self.target_id == self.self_id

    @property
    def sender_display(self) -> str:
        return self.sender_card or self.sender_name or self.sender_id

    def prompt_text(self) -> str:
        """Render a short, model-facing description of the interaction."""

        scope = f"群 {self.group_id}" if self.group_id else "私聊"
        return (
            f"互动事件：{self.sender_display}（QQ {self.sender_id}）在{scope}戳了你。"
            "你可以自然回应；如果要回戳发送者，调用 yebot_interaction_poke，"
            "把发送者作为 target。"
        )


def parse_poke_event(
    raw_event: Mapping[str, Any],
    *,
    bot_id: str = "",
) -> PokeEvent | None:
    """Parse a OneBot ``notice/sub_type=poke`` payload.

    OneBot implementations place the sender in either ``sender_id`` or
    ``user_id`` and may include a nested ``sender`` record. The parser accepts
    both forms and discards malformed notifications before they reach routing.
    """

    if normalize_id(raw_event.get("post_type")).lower() != "notice":
        return None
    if normalize_id(raw_event.get("sub_type")).lower() != "poke":
        return None

    sender = raw_event.get("sender")
    sender_map = sender if isinstance(sender, Mapping) else {}
    sender_id = normalize_id(
        raw_event.get("sender_id")
        or raw_event.get("user_id")
        or sender_map.get("user_id")
    )
    target_id = normalize_id(raw_event.get("target_id"))
    if not sender_id or not target_id:
        return None

    group_id = normalize_id(raw_event.get("group_id"))
    self_id = normalize_id(raw_event.get("self_id")) or normalize_id(bot_id)
    message_type = _safe_text(raw_event.get("message_type"), 16) or (
        "group" if group_id else "private"
    )
    sender_name = _safe_text(sender_map.get("nickname"), 80)
    sender_card = _safe_text(sender_map.get("card"), 80)
    return PokeEvent(
        sender_id=sender_id,
        target_id=target_id,
        group_id=group_id,
        self_id=self_id,
        sender_name=sender_name,
        sender_card=sender_card,
        message_type=message_type,
    )


def _safe_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


__all__ = ["PokeEvent", "parse_poke_event"]
