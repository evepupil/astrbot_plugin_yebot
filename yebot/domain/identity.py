"""Resolve a OneBot event into the minimum identity data YeBot needs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class UserRole(StrEnum):
    """YeBot's coarse-grained role model."""

    OWNER = "owner"
    GROUP_ADMIN = "group_admin"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class Identity:
    """Identity facts extracted from one event, without retaining message text."""

    user_id: str
    group_id: str
    role: UserRole
    sender_role: str

    @property
    def is_group(self) -> bool:
        return bool(self.group_id)


def normalize_id(value: Any) -> str:
    """Normalize QQ IDs while rejecting missing or non-scalar values."""

    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def parse_identity(
    raw_event: Mapping[str, Any],
    owner_ids: Iterable[str],
) -> Identity:
    """Resolve owner, current-group admin, and member roles.

    Owner IDs are global configuration. The ``sender.role`` value is trusted only
    for the current group, so a group admin never becomes a global owner.
    """

    sender_value = raw_event.get("sender")
    sender: Mapping[str, Any] = (
        sender_value if isinstance(sender_value, Mapping) else {}
    )
    user_id = normalize_id(sender.get("user_id") or raw_event.get("user_id"))
    group_id = normalize_id(raw_event.get("group_id"))
    sender_role = normalize_id(sender.get("role")).lower() or "member"
    configured_owners = {normalize_id(value) for value in owner_ids}
    configured_owners.discard("")

    if user_id in configured_owners:
        role = UserRole.OWNER
    elif group_id and sender_role in {"owner", "admin"}:
        role = UserRole.GROUP_ADMIN
    else:
        role = UserRole.MEMBER

    return Identity(
        user_id=user_id,
        group_id=group_id,
        role=role,
        sender_role=sender_role,
    )


_AT_PATTERN = re.compile(r"\[CQ:at,qq=(?P<qq>[^,\]]+)]")


def is_bot_mentioned(raw_event: Mapping[str, Any], bot_id: str) -> bool:
    """Check OneBot array segments and legacy CQ text for a bot mention."""

    normalized_bot_id = normalize_id(bot_id)
    if not normalized_bot_id:
        return False

    message = raw_event.get("message")
    if isinstance(message, list):
        for segment in message:
            if not isinstance(segment, Mapping):
                continue
            if normalize_id(segment.get("type")).lower() != "at":
                continue
            data = segment.get("data")
            if (
                isinstance(data, Mapping)
                and normalize_id(data.get("qq")) == normalized_bot_id
            ):
                return True

    if isinstance(message, str):
        return any(
            normalize_id(match.group("qq")) == normalized_bot_id
            for match in _AT_PATTERN.finditer(message)
        )
    return False
