import random
from datetime import datetime

from yebot.domain.policy import LowFrequencyPolicy, PolicyConfig
from yebot.runtime.observer import observe_event


def test_observer_drops_notice_and_request_events() -> None:
    policy = LowFrequencyPolicy(PolicyConfig(), random.Random(1))

    assert (
        observe_event(
            {"post_type": "notice", "message_type": "group", "group_id": 1},
            owner_ids=[],
            bot_id="123",
            policy=policy,
            now=datetime(2026, 7, 31, 12),
        )
        is None
    )
    assert (
        observe_event(
            {"post_type": "request", "message_type": "group", "group_id": 1},
            owner_ids=[],
            bot_id="123",
            policy=policy,
            now=datetime(2026, 7, 31, 12),
        )
        is None
    )


def test_observer_returns_redacted_summary_for_group_message() -> None:
    policy = LowFrequencyPolicy(
        PolicyConfig(
            quiet_hours_start=8,
            quiet_hours_end=9,
            reply_probability=1,
        ),
        random.Random(1),
    )
    observation = observe_event(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": 100,
            "message": [{"type": "at", "data": {"qq": 123}}],
            "raw_sensitive_text": "do not retain",
            "sender": {"user_id": 42, "role": "admin"},
        },
        owner_ids=[],
        bot_id="123",
        policy=policy,
        now=datetime(2026, 7, 31, 12),
    )

    assert observation is not None
    assert observation.identity.group_id == "100"
    assert observation.identity.role.value == "group_admin"
    assert observation.mentioned
    assert not hasattr(observation, "raw_sensitive_text")
