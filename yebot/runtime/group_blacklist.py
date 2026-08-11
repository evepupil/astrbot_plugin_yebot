"""Shared group blacklist normalization and event checks."""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.identity import normalize_id, normalize_id_list


def normalize_group_id(value: object) -> str:
    """Return a canonical numeric group ID, or an empty string."""

    normalized = normalize_id(value)
    if not normalized.isdecimal():
        return ""
    return str(int(normalized))


def normalize_group_ids(value: object) -> frozenset[str]:
    """Normalize list, comma-separated, or JSON group ID configuration."""

    return frozenset(
        group_id
        for entry in normalize_id_list(value)
        if (group_id := normalize_group_id(entry))
    )


def event_group_id(event: object) -> str:
    """Extract a group ID from a standard AstrBot/OneBot message event."""

    message_obj = getattr(event, "message_obj", None)
    raw_event = getattr(message_obj, "raw_message", None)
    if not isinstance(raw_event, Mapping):
        return ""
    if raw_event.get("message_type") != "group":
        return ""
    return normalize_group_id(raw_event.get("group_id"))


def is_blacklisted_group(
    group_id: object,
    blacklisted_group_ids: frozenset[str],
) -> bool:
    """Return whether a normalized or raw group ID is blocked."""

    normalized = normalize_group_id(group_id)
    return bool(normalized and normalized in blacklisted_group_ids)


def is_blacklisted_event(
    event: object,
    blacklisted_group_ids: frozenset[str],
) -> bool:
    """Return whether a standard group message belongs to the blacklist."""

    return is_blacklisted_group(event_group_id(event), blacklisted_group_ids)


__all__ = [
    "event_group_id",
    "is_blacklisted_event",
    "is_blacklisted_group",
    "normalize_group_id",
    "normalize_group_ids",
]
