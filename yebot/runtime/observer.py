"""Group-event observation adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

try:
    from ..domain.identity import Identity, is_bot_mentioned, parse_identity
except ImportError:
    from yebot.domain.identity import Identity, is_bot_mentioned, parse_identity


@dataclass(frozen=True, slots=True)
class Observation:
    """Safe event summary used for logs and future routing."""

    identity: Identity
    mentioned: bool
    post_type: str
    message_type: str


def observe_event(
    raw_event: Mapping[str, Any],
    *,
    owner_ids: Iterable[str],
    bot_id: str,
) -> Observation | None:
    """Filter non-message events and return a redacted observation summary."""

    if raw_event.get("post_type") != "message":
        return None
    if raw_event.get("message_type") != "group":
        return None

    identity = parse_identity(raw_event, owner_ids)
    mentioned = is_bot_mentioned(raw_event, bot_id)
    return Observation(
        identity=identity,
        mentioned=mentioned,
        post_type="message",
        message_type="group",
    )
