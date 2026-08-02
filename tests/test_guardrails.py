from __future__ import annotations

from datetime import UTC, datetime, timedelta

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.guardrails import (
    GuardrailCode,
    GuardrailManager,
    GuardrailSettings,
)


def identity(user_id: str = "42", group_id: str = "100") -> Identity:
    return Identity(user_id, group_id, UserRole.GROUP_ADMIN, "admin")


def test_only_kick_requires_confirmation() -> None:
    manager = GuardrailManager(token_factory=lambda: "confirm-1")

    kick = manager.begin(
        "group.kick_member",
        {"user_id": "99"},
        identity(),
        request_id="request-1",
    )
    mute = manager.begin(
        "group.mute_member",
        {"user_id": "99", "duration_seconds": 60},
        identity(),
        request_id="request-2",
    )

    assert kick.code is GuardrailCode.CONFIRMATION_REQUIRED
    assert kick.token == "confirm-1"
    assert mute.code is GuardrailCode.ALLOW
    manager.complete(
        "group.mute_member",
        {"user_id": "99", "duration_seconds": 60},
        identity(),
        request_id="request-2",
    )


def test_confirmation_is_bound_to_actor_group_and_arguments() -> None:
    manager = GuardrailManager(token_factory=lambda: "confirm-2")
    pending = manager.begin(
        "group.kick_member",
        {"user_id": "99", "reason": "spam"},
        identity(),
        request_id="request-1",
    )
    assert pending.pending is not None

    wrong_actor = manager.begin(
        "group.kick_member",
        {"user_id": "99", "reason": "spam"},
        identity("43"),
        request_id="request-1",
        confirmation_token="confirm-2",
    )
    assert wrong_actor.code is GuardrailCode.INVALID_CONFIRMATION

    accepted = manager.begin(
        "group.kick_member",
        {"user_id": "99", "reason": "spam"},
        identity(),
        request_id="request-1",
        confirmation_token="confirm-2",
    )
    assert accepted.code is GuardrailCode.ALLOW
    manager.complete(
        "group.kick_member",
        {"user_id": "99", "reason": "spam"},
        identity(),
        request_id="request-1",
    )

    replay = manager.begin(
        "group.kick_member",
        {"user_id": "99", "reason": "spam"},
        identity(),
        request_id="request-3",
        confirmation_token="confirm-2",
    )
    assert replay.code is GuardrailCode.CONFIRMATION_REPLAYED


def test_expired_confirmation_and_protected_target_fail_closed() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    manager = GuardrailManager(
        GuardrailSettings(confirmation_ttl_seconds=10),
        clock=lambda: now[0],
        token_factory=lambda: "confirm-3",
        protected_target_ids=("1592829658",),
    )
    protected = manager.begin(
        "group.kick_member",
        {"user_id": "1592829658"},
        identity(),
    )
    assert protected.code is GuardrailCode.TARGET_PROTECTED

    pending = manager.begin(
        "group.kick_member",
        {"user_id": "99"},
        identity(),
    )
    assert pending.code is GuardrailCode.CONFIRMATION_REQUIRED
    now[0] += timedelta(seconds=11)
    expired = manager.begin(
        "group.kick_member",
        {"user_id": "99"},
        identity(),
        confirmation_token="confirm-3",
    )
    assert expired.code is GuardrailCode.CONFIRMATION_EXPIRED


def test_daily_quota_and_concurrency_limits_are_enforced() -> None:
    manager = GuardrailManager(
        GuardrailSettings(daily_action_limit=10, max_concurrent_actions=1)
    )
    first = manager.begin(
        "message.send", {"message": "one"}, identity(), request_id="one"
    )
    assert first.code is GuardrailCode.ALLOW
    blocked = manager.begin(
        "message.send", {"message": "two"}, identity(), request_id="two"
    )
    assert blocked.code is GuardrailCode.CONCURRENCY_LIMIT
    manager.complete("message.send", {"message": "one"}, identity(), request_id="one")
    quota = manager.begin(
        "message.send", {"message": "two"}, identity(), request_id="two"
    )
    assert quota.code is GuardrailCode.ALLOW
    manager.complete("message.send", {"message": "two"}, identity(), request_id="two")

    limited = GuardrailManager(GuardrailSettings(daily_action_limit=1))
    assert limited.begin("message.send", {"message": "one"}, identity()).allowed
    assert (
        limited.begin("message.send", {"message": "two"}, identity()).code
        is GuardrailCode.QUOTA_EXCEEDED
    )
