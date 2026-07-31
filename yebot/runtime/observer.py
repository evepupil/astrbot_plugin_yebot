"""Group-event observation adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from ..domain.identity import Identity, is_bot_mentioned, parse_identity
    from ..domain.policy import LowFrequencyPolicy, PolicyDecision
except ImportError:
    from yebot.domain.identity import Identity, is_bot_mentioned, parse_identity
    from yebot.domain.policy import LowFrequencyPolicy, PolicyDecision


@dataclass(frozen=True, slots=True)
class Observation:
    """Safe event summary used for logs and future routing."""

    identity: Identity
    decision: PolicyDecision
    mentioned: bool
    post_type: str
    message_type: str


def observe_event(
    raw_event: Mapping[str, Any],
    *,
    owner_ids: Iterable[str],
    bot_id: str,
    policy: LowFrequencyPolicy,
    now: datetime,
) -> Observation | None:
    """Filter non-message events and return a redacted observation summary."""

    if raw_event.get("post_type") != "message":
        return None
    if raw_event.get("message_type") != "group":
        return None

    identity = parse_identity(raw_event, owner_ids)
    mentioned = is_bot_mentioned(raw_event, bot_id)
    decision = policy.evaluate(identity, now, mentioned=mentioned)
    return Observation(
        identity=identity,
        decision=decision,
        mentioned=mentioned,
        post_type="message",
        message_type="group",
    )
