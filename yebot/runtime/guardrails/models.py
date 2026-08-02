"""Data contracts for confirmations, quotas, and minimal audit records."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType


class GuardrailCode(StrEnum):
    """Stable outcomes produced before a tool handler is called."""

    ALLOW = "allow"
    CONFIRMATION_REQUIRED = "confirmation_required"
    INVALID_CONFIRMATION = "invalid_confirmation"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    CONFIRMATION_REPLAYED = "confirmation_replayed"
    QUOTA_EXCEEDED = "quota_exceeded"
    CONCURRENCY_LIMIT = "concurrency_limit"
    TARGET_PROTECTED = "target_protected"
    IDEMPOTENT_REPLAY = "idempotent_replay"


@dataclass(frozen=True, slots=True)
class GuardrailSettings:
    """Bounded defaults for side-effecting tool calls."""

    confirmation_ttl_seconds: int = 120
    daily_action_limit: int = 100
    daily_kick_limit: int = 20
    max_concurrent_actions: int = 2
    confirmation_tools: frozenset[str] = frozenset({"group.kick_member"})

    def __post_init__(self) -> None:
        if self.confirmation_ttl_seconds < 1:
            raise ValueError("confirmation_ttl_seconds must be positive")
        if self.daily_action_limit < 1:
            raise ValueError("daily_action_limit must be positive")
        if self.daily_kick_limit < 1:
            raise ValueError("daily_kick_limit must be positive")
        if self.max_concurrent_actions < 1:
            raise ValueError("max_concurrent_actions must be positive")
        normalized = frozenset(tool.strip().lower() for tool in self.confirmation_tools)
        if any(not tool for tool in normalized):
            raise ValueError("confirmation_tools must not contain empty names")
        object.__setattr__(self, "confirmation_tools", normalized)


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """A one-time action proposal bound to its original actor and group."""

    token: str
    tool_name: str
    arguments: Mapping[str, object]
    actor_id: str
    group_id: str
    request_id: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", self.token.strip())
        object.__setattr__(self, "tool_name", self.tool_name.strip().lower())
        object.__setattr__(self, "actor_id", self.actor_id.strip())
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "expires_at", _utc(self.expires_at))
        if not self.token or not self.tool_name or not self.actor_id:
            raise ValueError("confirmation identity fields must not be empty")
        if self.expires_at <= self.created_at:
            raise ValueError("confirmation must expire after it is created")


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    """Decision returned to the gateway before handler execution."""

    code: GuardrailCode
    token: str | None = None
    pending: PendingConfirmation | None = None
    cached_result: object | None = None

    @property
    def allowed(self) -> bool:
        return self.code is GuardrailCode.ALLOW


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Minimal, redacted record for one control-plane transition."""

    event_id: str
    timestamp: datetime
    actor_id: str
    group_id: str
    tool_name: str
    outcome: str
    request_id: str = ""
    target_user_id: str = ""
    details: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", self.event_id.strip())
        object.__setattr__(self, "timestamp", _utc(self.timestamp))
        object.__setattr__(self, "actor_id", self.actor_id.strip())
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "tool_name", self.tool_name.strip().lower())
        object.__setattr__(self, "outcome", self.outcome.strip().lower())
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "target_user_id", self.target_user_id.strip())
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


def confirmation_expiry(created_at: datetime, ttl_seconds: int) -> datetime:
    """Return a timezone-normalized expiry without relying on local time."""

    return _utc(created_at) + timedelta(seconds=ttl_seconds)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_probability(value: float) -> None:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
