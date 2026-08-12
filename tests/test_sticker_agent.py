from yebot.runtime.stickers import (
    build_sticker_consider_arguments,
    reserve_automatic_sticker_search,
    should_queue_automatic_sticker,
)


def test_automatic_sticker_run_searches_at_most_once() -> None:
    state: dict[str, bool] = {}

    assert reserve_automatic_sticker_search(state)
    assert not reserve_automatic_sticker_search(state)


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
            has_image=False,
            group_reply_allowed=True,
            observe_only=False,
            background_mode=False,
            background_tools_allowed=False,
            blacklisted=False,
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
