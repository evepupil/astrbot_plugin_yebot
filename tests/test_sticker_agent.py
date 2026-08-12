from yebot.runtime.stickers import (
    build_sticker_consider_arguments,
    is_registered_automatic_sticker_event,
    release_automatic_sticker_run,
    reserve_automatic_sticker_event,
    reserve_automatic_sticker_run,
    reserve_automatic_sticker_search,
    reserve_automatic_sticker_send_attempt,
    should_queue_automatic_sticker,
)


def test_automatic_sticker_run_searches_at_most_once() -> None:
    state: dict[str, bool] = {}

    assert reserve_automatic_sticker_search(state)
    assert not reserve_automatic_sticker_search(state)


def test_automatic_sticker_event_and_run_are_single_use() -> None:
    consumed: set[str] = set()
    assert reserve_automatic_sticker_event(consumed, "100:101:token")
    assert not reserve_automatic_sticker_event(consumed, "100:101:token")

    run_state: dict[str, bool] = {}
    assert reserve_automatic_sticker_run(run_state)
    assert not reserve_automatic_sticker_run(run_state)
    release_automatic_sticker_run(run_state)
    assert reserve_automatic_sticker_run(run_state)

    send_state: dict[str, bool] = {}
    assert reserve_automatic_sticker_send_attempt(send_state)
    assert not reserve_automatic_sticker_send_attempt(send_state)


def _incoming_group_event(
    *, message_id: object = 101, sender_id: object = 42
) -> dict[str, object]:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": 100,
        "message_id": message_id,
        "sender": {"user_id": sender_id},
    }


def test_automatic_sticker_requires_the_current_human_message_key() -> None:
    event = _incoming_group_event()

    assert should_queue_automatic_sticker(
        event,
        response_text="有道理",
        current_text="这个方案可以试试",
        observed_message_key="100:101",
        observed_event_token="100:101:token",
        has_image=False,
        group_reply_allowed=True,
        observe_only=False,
        background_mode=False,
        background_tools_allowed=False,
        blacklisted=False,
        bot_id="999",
    )
    assert not should_queue_automatic_sticker(
        event,
        response_text="有道理",
        current_text="这个方案可以试试",
        observed_message_key="100:100",
        observed_event_token="100:101:token",
        has_image=False,
        group_reply_allowed=True,
        observe_only=False,
        background_mode=False,
        background_tools_allowed=False,
        blacklisted=False,
        bot_id="999",
    )


def test_automatic_sticker_rejects_idle_and_bot_authored_events() -> None:
    for event in (
        _incoming_group_event(message_id=""),
        _incoming_group_event(sender_id=999),
    ):
        assert not should_queue_automatic_sticker(
            event,
            response_text="有道理",
            current_text="这个方案可以试试",
            observed_message_key="100:101",
            observed_event_token="100:101:token",
            has_image=False,
            group_reply_allowed=True,
            observe_only=False,
            background_mode=False,
            background_tools_allowed=False,
            blacklisted=False,
            bot_id="999",
        )


def test_automatic_sticker_requires_an_observed_event_token() -> None:
    assert not should_queue_automatic_sticker(
        _incoming_group_event(),
        response_text="有道理",
        current_text="这个方案可以试试",
        observed_message_key="100:101",
        observed_event_token="",
        has_image=False,
        group_reply_allowed=True,
        observe_only=False,
        background_mode=False,
        background_tools_allowed=False,
        blacklisted=False,
        bot_id="999",
    )
    assert is_registered_automatic_sticker_event(
        _incoming_group_event(),
        observed_message_key="100:101",
        observed_event_token="100:101:token",
        bot_id="999",
    )


def test_automatic_sticker_registration_rejects_non_message_and_bot_events() -> None:
    event = _incoming_group_event()
    assert not is_registered_automatic_sticker_event(
        {**event, "post_type": "notice"},
        observed_message_key="100:101",
        observed_event_token="100:101:token",
        bot_id="999",
    )
    assert not is_registered_automatic_sticker_event(
        _incoming_group_event(sender_id=999),
        observed_message_key="100:101",
        observed_event_token="100:101:token",
        bot_id="999",
    )


def test_sticker_consider_defaults_fail_closed() -> None:
    assert build_sticker_consider_arguments() == {
        "should_collect": False,
        "asset_kind": "other",
        "reaction_ready": False,
        "meaning": "",
        "image_index": 0,
        "confidence": 0.0,
    }


def test_sticker_consider_arguments_normalize_integer_image_index() -> None:
    assert build_sticker_consider_arguments(
        should_collect=True,
        asset_kind="reaction_sticker",
        reaction_ready=True,
        confidence=0.95,
        meaning="开心",
        tags=["开心"],
        image_index=1.0,
    ) == {
        "should_collect": True,
        "asset_kind": "reaction_sticker",
        "reaction_ready": True,
        "meaning": "开心",
        "image_index": 1,
        "confidence": 0.95,
        "tags": ["开心"],
    }
