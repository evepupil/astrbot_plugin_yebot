"""Deterministic, low-frequency participation policy."""

from __future__ import annotations

import random
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from .identity import Identity


class DecisionCode(StrEnum):
    """Reason returned to the runtime for an observation."""

    NOT_GROUP = "not_group"
    QUIET_HOURS = "quiet_hours"
    MENTION_REQUIRED = "mention_required"
    DAILY_LIMIT = "daily_limit"
    COOLDOWN = "cooldown"
    PROBABILITY = "probability"
    OBSERVE_ONLY = "observe_only"
    ALLOW = "allow"


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    observe_only: bool = True
    cooldown_seconds: int = 60
    quiet_hours_start: int = 0
    quiet_hours_end: int = 7
    daily_reply_limit: int = 20
    reply_probability: float = 0.2
    require_mention: bool = True

    def __post_init__(self) -> None:
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if not 0 <= self.quiet_hours_start <= 23:
            raise ValueError("quiet_hours_start must be between 0 and 23")
        if not 0 <= self.quiet_hours_end <= 23:
            raise ValueError("quiet_hours_end must be between 0 and 23")
        if self.daily_reply_limit < 0:
            raise ValueError("daily_reply_limit must be non-negative")
        if not 0 <= self.reply_probability <= 1:
            raise ValueError("reply_probability must be between 0 and 1")


@dataclass(slots=True)
class _ScopeState:
    day: date
    reply_count: int = 0
    next_allowed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    code: DecisionCode
    should_reply: bool
    scope_key: str


class LowFrequencyPolicy:
    """Apply group, time, mention, quota, cooldown, and probability gates."""

    def __init__(
        self,
        config: PolicyConfig,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self._rng = rng or random.Random()
        self._states: MutableMapping[str, _ScopeState] = {}

    def evaluate(
        self,
        identity: Identity,
        now: datetime,
        *,
        mentioned: bool,
    ) -> PolicyDecision:
        """Return a decision without changing quota or cooldown state."""

        scope_key = identity.group_id
        if not identity.is_group:
            return PolicyDecision(DecisionCode.NOT_GROUP, False, scope_key)

        state = self._state_for(scope_key, now)
        if self._is_quiet_hour(now.hour):
            return PolicyDecision(DecisionCode.QUIET_HOURS, False, scope_key)
        if self.config.require_mention and not mentioned:
            return PolicyDecision(DecisionCode.MENTION_REQUIRED, False, scope_key)
        if state.reply_count >= self.config.daily_reply_limit:
            return PolicyDecision(DecisionCode.DAILY_LIMIT, False, scope_key)
        if state.next_allowed_at is not None and now < state.next_allowed_at:
            return PolicyDecision(DecisionCode.COOLDOWN, False, scope_key)
        if self._rng.random() >= self.config.reply_probability:
            return PolicyDecision(DecisionCode.PROBABILITY, False, scope_key)
        if self.config.observe_only:
            return PolicyDecision(DecisionCode.OBSERVE_ONLY, False, scope_key)
        return PolicyDecision(DecisionCode.ALLOW, True, scope_key)

    def commit(self, identity: Identity, now: datetime) -> None:
        """Consume one reply allowance after a real response was sent."""

        if not identity.is_group:
            return
        state = self._state_for(identity.group_id, now)
        state.reply_count += 1
        state.next_allowed_at = now + timedelta(seconds=self.config.cooldown_seconds)

    def _state_for(self, scope_key: str, now: datetime) -> _ScopeState:
        state = self._states.get(scope_key)
        if state is None or state.day != now.date():
            state = _ScopeState(day=now.date())
            self._states[scope_key] = state
        return state

    def _is_quiet_hour(self, hour: int) -> bool:
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end
