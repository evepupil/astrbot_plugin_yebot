from yebot.runtime.jobs import parse_reminder_request


def test_parse_reminder_with_minutes_and_message() -> None:
    parsed = parse_reminder_request("10分钟后提醒我开会")

    assert parsed.intent is not None
    assert parsed.intent.delay_seconds == 600
    assert parsed.intent.message == "开会"
    assert parsed.intent.target_user_id is None


def test_parse_reminder_with_at_target_before_time() -> None:
    parsed = parse_reminder_request(
        "提醒 [At:42] 30秒后喝水",
        mentioned_user_ids=("42",),
    )

    assert parsed.intent is not None
    assert parsed.intent.delay_seconds == 30
    assert parsed.intent.target_user_id == "42"
    assert parsed.intent.message == "[CQ:at,qq=42] 喝水"


def test_parse_reminder_supports_time_before_command_and_long_units() -> None:
    parsed = parse_reminder_request("过1小时后提醒某人 散步")

    assert parsed.intent is not None
    assert parsed.intent.delay_seconds == 3600
    assert parsed.intent.message == "散步"


def test_parse_reminder_rejects_missing_time_or_message() -> None:
    assert parse_reminder_request("定时提醒某人开会").error == "time_missing"
    assert parse_reminder_request("提醒我10分钟后").error == "message_missing"


def test_parse_reminder_rejects_ambiguous_targets() -> None:
    parsed = parse_reminder_request(
        "10分钟后提醒开会",
        mentioned_user_ids=("42", "43"),
    )

    assert parsed.error == "multiple_targets"


def test_unrelated_text_does_not_claim_reminder_intent() -> None:
    parsed = parse_reminder_request("今天聊聊提醒这个词")

    assert not parsed.is_request
