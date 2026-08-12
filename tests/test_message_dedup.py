from types import SimpleNamespace

from yebot.runtime.message_dedup import (
    is_duplicate_response,
    is_successful_message_send,
)


def test_duplicate_response_ignores_explicit_at_marker() -> None:
    assert is_duplicate_response(
        "请看这条消息",
        ("[CQ:at,qq=42] 请看这条消息",),
    )


def test_duplicate_response_requires_non_empty_exact_text() -> None:
    assert not is_duplicate_response("", ("",))
    assert not is_duplicate_response("请看这条消息", ("请看另一条消息",))


def test_successful_message_send_excludes_failures_and_dry_runs() -> None:
    successful = SimpleNamespace(
        ok=True,
        value={
            "action": "send_group_msg",
            "dry_run": False,
            "result": {"status": "ok", "retcode": 0},
        },
    )
    failed = SimpleNamespace(
        ok=True,
        value={
            "action": "send_group_msg",
            "dry_run": False,
            "result": {"status": "failed", "retcode": 1200},
        },
    )
    onebot_message_id = SimpleNamespace(
        ok=True,
        value={
            "action": "send_group_msg",
            "dry_run": False,
            "result": {"message_id": 123},
        },
    )
    dry_run = SimpleNamespace(
        ok=True,
        value={"action": "send_group_msg", "dry_run": True},
    )

    assert is_successful_message_send(successful)
    assert is_successful_message_send(onebot_message_id)
    assert not is_successful_message_send(failed)
    assert not is_successful_message_send(dry_run)
