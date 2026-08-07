from yebot.runtime.interaction import PokeEvent, parse_poke_event


def test_parse_group_poke_uses_nested_sender_and_bot_id_fallback() -> None:
    event = parse_poke_event(
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "group_id": 100,
            "user_id": 42,
            "target_id": 1592829658,
            "sender": {"user_id": 42, "nickname": " 小李 ", "card": "群友"},
        },
        bot_id="1592829658",
    )

    assert event is not None
    assert event == PokeEvent(
        sender_id="42",
        target_id="1592829658",
        group_id="100",
        self_id="1592829658",
        sender_name="小李",
        sender_card="群友",
        message_type="group",
    )
    assert event.is_targeting_self
    assert "群友" in event.prompt_text()


def test_parse_group_poke_keeps_non_bot_target_as_observation() -> None:
    event = parse_poke_event(
        {
            "post_type": "notice",
            "sub_type": "poke",
            "group_id": "100",
            "sender_id": "42",
            "target_id": "99",
            "self_id": "1592829658",
        }
    )

    assert event is not None
    assert not event.is_targeting_self
    assert event.is_group


def test_parse_poke_rejects_non_poke_or_incomplete_payloads() -> None:
    assert parse_poke_event({"post_type": "message", "sub_type": "poke"}) is None
    assert (
        parse_poke_event({"post_type": "notice", "sub_type": "poke", "sender_id": "42"})
        is None
    )
