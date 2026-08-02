from yebot.domain.identity import (
    UserRole,
    extract_mentioned_user_ids,
    is_bot_mentioned,
    parse_identity,
)


def test_owner_id_has_global_priority_over_group_role() -> None:
    identity = parse_identity(
        {
            "group_id": 100,
            "sender": {"user_id": 42, "role": "member"},
        },
        owner_ids=["42"],
    )

    assert identity.user_id == "42"
    assert identity.group_id == "100"
    assert identity.role is UserRole.OWNER


def test_group_admin_is_scoped_to_current_group() -> None:
    identity = parse_identity(
        {
            "group_id": "100",
            "sender": {"user_id": "42", "role": "admin"},
        },
        owner_ids=[],
    )

    assert identity.role is UserRole.GROUP_ADMIN


def test_member_is_default_role() -> None:
    identity = parse_identity(
        {
            "group_id": "100",
            "sender": {"user_id": "42", "role": "member"},
        },
        owner_ids=[],
    )

    assert identity.role is UserRole.MEMBER


def test_at_segment_and_legacy_cq_mention_are_supported() -> None:
    array_event = {
        "message": [
            {"type": "text", "data": {"text": "hello"}},
            {"type": "at", "data": {"qq": 123}},
        ]
    }
    cq_event = {"message": "hello [CQ:at,qq=123]"}

    assert is_bot_mentioned(array_event, "123")
    assert is_bot_mentioned(cq_event, "123")


def test_mentioned_target_is_independent_of_message_position() -> None:
    event = {
        "message": [
            {"type": "at", "data": {"qq": "123"}},
            {"type": "text", "data": {"text": "禁言一分钟"}},
            {"type": "at", "data": {"qq": "456"}},
        ]
    }

    assert extract_mentioned_user_ids(event, excluded_ids=("123",)) == ("456",)


def test_mentioned_targets_support_cq_text_and_deduplicate() -> None:
    event = {
        "message": "禁言 [CQ:at,qq=456] 一分钟 [CQ:at,qq=456]",
    }

    assert extract_mentioned_user_ids(event) == ("456",)
