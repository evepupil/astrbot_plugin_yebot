from types import SimpleNamespace

from yebot.runtime.group_blacklist import (
    event_group_id,
    is_blacklisted_event,
    normalize_group_id,
    normalize_group_ids,
)


def group_event(group_id: object) -> object:
    return SimpleNamespace(
        message_obj=SimpleNamespace(
            raw_message={
                "message_type": "group",
                "group_id": group_id,
            }
        )
    )


def test_group_ids_accept_list_string_and_json_forms() -> None:
    assert normalize_group_ids(["00100", "200", "not-a-group"]) == {
        "100",
        "200",
    }
    assert normalize_group_ids("100, 300") == {"100", "300"}
    assert normalize_group_ids('["400", "500"]') == {"400", "500"}


def test_group_event_matching_ignores_private_and_non_numeric_ids() -> None:
    event = group_event("00100")

    assert normalize_group_id("00100") == "100"
    assert event_group_id(event) == "100"
    assert is_blacklisted_event(event, frozenset({"100"}))
    assert not is_blacklisted_event(
        SimpleNamespace(
            message_obj=SimpleNamespace(
                raw_message={"message_type": "private", "user_id": "100"}
            )
        ),
        frozenset({"100"}),
    )
