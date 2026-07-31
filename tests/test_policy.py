import random
from datetime import datetime

from yebot.domain.identity import Identity, UserRole
from yebot.domain.policy import DecisionCode, LowFrequencyPolicy, PolicyConfig


def group_identity(group_id: str = "100") -> Identity:
    return Identity("42", group_id, UserRole.MEMBER, "member")


def test_observe_only_never_allows_reply() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            observe_only=True,
            quiet_hours_start=8,
            quiet_hours_end=9,
            reply_probability=1,
        ),
        random.Random(1),
    )

    decision = policy.evaluate(
        group_identity(),
        datetime(2026, 7, 31, 12),
        mentioned=True,
    )

    assert decision.code is DecisionCode.OBSERVE_ONLY
    assert not decision.should_reply


def test_quiet_hours_and_mention_gate_are_applied() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            quiet_hours_start=0,
            quiet_hours_end=7,
            reply_probability=1,
            require_mention=True,
        ),
        random.Random(1),
    )

    assert (
        policy.evaluate(group_identity(), datetime(2026, 7, 31, 2), mentioned=True).code
        is DecisionCode.QUIET_HOURS
    )
    assert (
        policy.evaluate(
            group_identity(), datetime(2026, 7, 31, 12), mentioned=False
        ).code
        is DecisionCode.MENTION_REQUIRED
    )


def test_commit_enforces_cooldown_and_daily_limit() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            observe_only=False,
            cooldown_seconds=60,
            daily_reply_limit=2,
            quiet_hours_start=8,
            quiet_hours_end=9,
            reply_probability=1,
            require_mention=False,
        ),
        random.Random(1),
    )
    identity = group_identity()
    first = datetime(2026, 7, 31, 12)

    assert policy.evaluate(identity, first, mentioned=False).should_reply
    policy.commit(identity, first)
    assert (
        policy.evaluate(
            identity, datetime(2026, 7, 31, 12, 0, 30), mentioned=False
        ).code
        is DecisionCode.COOLDOWN
    )
    policy.commit(identity, datetime(2026, 7, 31, 12, 2))
    assert (
        policy.evaluate(identity, datetime(2026, 7, 31, 12, 4), mentioned=False).code
        is DecisionCode.DAILY_LIMIT
    )


def test_state_resets_on_the_next_day() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            observe_only=False,
            daily_reply_limit=1,
            quiet_hours_start=8,
            quiet_hours_end=9,
            reply_probability=1,
            require_mention=False,
        ),
        random.Random(1),
    )
    identity = group_identity()
    first = datetime(2026, 7, 31, 12)
    policy.commit(identity, first)

    assert policy.evaluate(
        identity, datetime(2026, 8, 1, 12), mentioned=False
    ).should_reply


def test_probability_zero_blocks_reply() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            observe_only=False,
            quiet_hours_start=8,
            quiet_hours_end=9,
            reply_probability=0,
            require_mention=False,
        ),
        random.Random(1),
    )

    decision = policy.evaluate(
        group_identity(),
        datetime(2026, 7, 31, 12),
        mentioned=False,
    )

    assert decision.code is DecisionCode.PROBABILITY
