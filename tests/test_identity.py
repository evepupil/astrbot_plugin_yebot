from yebot.domain.identity import UserRole, is_bot_mentioned, parse_identity


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
