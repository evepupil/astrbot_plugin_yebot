import asyncio
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.jobs import JobScheduler, MemoryJobStore
from yebot.runtime.memory import MemoryService, SQLiteMemoryStore
from yebot.runtime.model_ratings import ModelRatingsClient
from yebot.runtime.system_info import SystemInfoCollector, TokenUsageTracker
from yebot.runtime.token_calculator import TokenCalculator
from yebot.runtime.tools import ToolContext, ToolResultCode
from yebot.runtime.tools.onebot import (
    OneBotActionClient,
    OneBotToolRuntime,
    _validate_public_url,
    resolve_event_action_client,
)


class FakeActionClient:
    def __init__(self, responses: Mapping[str, object]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        response = self.responses.get(action, {})
        if isinstance(response, BaseException):
            raise response
        return response


def tool_context(role: UserRole, group_id: str = "100") -> ToolContext:
    return ToolContext(Identity("42", group_id, role, role.value))


def runtime(
    client: FakeActionClient,
    *,
    dry_run: bool = True,
    memory_service: MemoryService | None = None,
    model_ratings_client: ModelRatingsClient | None = None,
    token_calculator: TokenCalculator | None = None,
    system_info_collector: SystemInfoCollector | None = None,
    token_usage_tracker: TokenUsageTracker | None = None,
    event: object | None = None,
) -> OneBotToolRuntime:
    return OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=dry_run,
        memory_service=memory_service,
        model_ratings_client=model_ratings_client,
        token_calculator=token_calculator,
        system_info_collector=system_info_collector,
        token_usage_tracker=token_usage_tracker,
        event=event,
    )


def test_get_members_calls_onebot_and_sanitizes_result() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": [
                {
                    "user_id": 42,
                    "nickname": " Alice ",
                    "card": "A",
                    "role": "member",
                    "join_time": 123,
                },
            ],
        },
    )

    result = asyncio.run(
        runtime(client).execute("group.get_members", {}, tool_context(UserRole.MEMBER))
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "group_id": "100",
        "member_count": 1,
        "members": [
            {"user_id": "42", "nickname": "Alice", "card": "A", "role": "member"}
        ],
    }
    assert client.calls == [("get_group_member_list", {"group_id": 100})]


def test_cron_event_resolves_action_client_from_platform_context() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(action: str, **params: object) -> object:
        calls.append((action, params))
        return {"status": "ok"}

    platform = SimpleNamespace(bot=SimpleNamespace(call_action=call_action))
    event = SimpleNamespace(
        bot=None,
        context_obj=SimpleNamespace(
            get_platform_inst=lambda platform_id: (
                platform if platform_id == "aiocqhttp" else None
            )
        ),
        get_platform_id=lambda: "aiocqhttp",
    )

    client = resolve_event_action_client(event)

    assert client is not None
    assert asyncio.run(client.call_action("get_group_member_list", group_id=100)) == {
        "status": "ok"
    }
    assert calls == [("get_group_member_list", {"group_id": 100})]


def test_reminder_list_is_shared_by_current_group() -> None:
    client = FakeActionClient({})
    scheduler = JobScheduler(MemoryJobStore())
    job = scheduler.create_reminder(
        Identity("77", "100", UserRole.MEMBER, "member"),
        delay_seconds=60,
        message="停止刷屏",
    )
    runtime_instance = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        scheduler=scheduler,
    )

    result = asyncio.run(
        runtime_instance.execute("reminder.list", {}, tool_context(UserRole.MEMBER))
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "jobs": [
            {
                "job_id": job.job_id,
                "kind": "reminder",
                "status": "pending",
                "group_id": "100",
                "owner_id": "77",
                "message": "停止刷屏",
                "run_at": job.run_at.isoformat(),
                "attempts": 0,
                "last_error": None,
            }
        ]
    }
    assert client.calls == []


def test_get_recent_speakers_reads_distinct_members_from_history() -> None:
    client = FakeActionClient(
        {
            "get_group_msg_history": {
                "data": {
                    "messages": [
                        {
                            "time": 10,
                            "sender": {
                                "user_id": "11",
                                "nickname": "older",
                                "role": "member",
                            },
                        },
                        {
                            "time": 30,
                            "sender": {
                                "user_id": "22",
                                "nickname": "newer",
                                "role": "member",
                            },
                        },
                        {
                            "time": 20,
                            "sender": {
                                "user_id": "11",
                                "nickname": "older",
                                "role": "member",
                            },
                        },
                    ]
                }
            }
        }
    )

    result = asyncio.run(
        runtime(client).execute(
            "group.get_recent_speakers",
            {"limit": 2},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "group_id": "100",
        "speaker_count": 2,
        "speakers": [
            {"user_id": "22", "nickname": "newer", "card": "", "role": "member"},
            {"user_id": "11", "nickname": "older", "card": "", "role": "member"},
        ],
    }
    assert client.calls == [("get_group_msg_history", {"group_id": 100, "count": 20})]


def test_get_random_member_excludes_protected_and_admin_members() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": [
                {"user_id": "1592829658", "nickname": "bot", "role": "member"},
                {"user_id": "42", "nickname": "actor", "role": "admin"},
                {"user_id": "88", "nickname": "owner", "role": "owner"},
                {"user_id": "99", "nickname": "eligible", "role": "member"},
            ]
        }
    )
    context = ToolContext(
        Identity("42", "100", UserRole.GROUP_ADMIN, "admin"),
        protected_target_ids=("1592829658", "88"),
    )

    result = asyncio.run(
        runtime(client).execute("group.get_random_member", {}, context)
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value["member"]["user_id"] == "99"  # type: ignore[index]


def test_memory_tools_use_the_same_gateway_and_scope_policy(tmp_path: Path) -> None:
    service = MemoryService(SQLiteMemoryStore(tmp_path / "memory.db"))
    client = FakeActionClient({})
    runtime_instance = runtime(client, memory_service=service)

    remembered = asyncio.run(
        runtime_instance.execute(
            "memory.remember",
            {"topic": "称呼", "content": "叫我乙"},
            tool_context(UserRole.MEMBER, group_id=""),
        )
    )
    assert remembered.code is ToolResultCode.SUCCESS
    memory_id = remembered.value["memory_id"]  # type: ignore[index]

    recalled = asyncio.run(
        runtime_instance.execute(
            "memory.recall",
            {"query": "称呼"},
            tool_context(UserRole.MEMBER, group_id=""),
        )
    )
    assert recalled.code is ToolResultCode.SUCCESS
    assert recalled.value["memories"][0]["memory_id"] == memory_id  # type: ignore[index]

    other_actor = asyncio.run(
        runtime_instance.execute(
            "memory.recall",
            {"query": "称呼"},
            ToolContext(Identity("99", "", UserRole.MEMBER, "member")),
        )
    )
    assert other_actor.code is ToolResultCode.SUCCESS
    assert other_actor.value == {"memories": []}


def test_memory_group_write_denial_is_returned_as_role_denied(tmp_path: Path) -> None:
    service = MemoryService(SQLiteMemoryStore(tmp_path / "memory.db"))
    result = asyncio.run(
        runtime(FakeActionClient({}), memory_service=service).execute(
            "memory.remember",
            {"scope": "group", "topic": "群规", "content": "管理员维护"},
            tool_context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.ROLE_DENIED


def test_member_cannot_invoke_kick_action() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "group.kick_member",
            {"user_id": "99"},
            tool_context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.ROLE_DENIED
    assert client.calls == []


@pytest.mark.parametrize("sender_id", [99, 1592829658])
def test_admin_can_recall_a_member_or_bot_message(sender_id: int) -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "message_id": 123,
                    "group_id": 100,
                    "sender": {"user_id": sender_id},
                }
            },
            "delete_msg": {"status": "ok", "retcode": 0},
        }
    )

    result = asyncio.run(
        runtime(client, dry_run=False).execute(
            "message.recall",
            {"message_id": 123},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "message_id": "123",
        "recalled": True,
        "result": {
            "dry_run": False,
            "action": "delete_msg",
            "params": {"message_id": 123},
            "result": {"status": "ok", "retcode": 0},
        },
    }
    assert client.calls == [
        ("get_msg", {"message_id": 123}),
        ("delete_msg", {"message_id": 123}),
    ]


def test_member_cannot_recall_a_message() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "message.recall",
            {"message_id": 123},
            tool_context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.ROLE_DENIED
    assert client.calls == []


def test_admin_can_read_recent_messages_for_recall_without_current_command() -> None:
    client = FakeActionClient(
        {
            "get_group_msg_history": {
                "data": {
                    "messages": [
                        {
                            "message_id": 10,
                            "time": 10,
                            "sender": {
                                "user_id": 90,
                                "nickname": "较早",
                                "role": "member",
                            },
                            "message": [{"type": "text", "data": {"text": "较早内容"}}],
                        },
                        {
                            "message_id": 20,
                            "time": 20,
                            "sender": {
                                "user_id": 91,
                                "nickname": "目标",
                                "role": "member",
                            },
                            "message": [
                                {"type": "image", "data": {"file": "secret-url"}}
                            ],
                        },
                        {
                            "message_id": 30,
                            "time": 30,
                            "sender": {
                                "user_id": 42,
                                "nickname": "管理员",
                                "role": "admin",
                            },
                            "message": [
                                {"type": "text", "data": {"text": "撤回刚才那条"}}
                            ],
                        },
                    ]
                }
            }
        }
    )
    event = SimpleNamespace(message_obj=SimpleNamespace(raw_message={"message_id": 30}))

    result = asyncio.run(
        runtime(client, event=event).execute(
            "message.get_recent_for_recall",
            {"limit": 2},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "group_id": "100",
        "messages": [
            {
                "message_id": "20",
                "sender": {
                    "user_id": "91",
                    "nickname": "目标",
                    "card": "",
                    "role": "member",
                },
                "content": "[图片]",
            },
            {
                "message_id": "10",
                "sender": {
                    "user_id": "90",
                    "nickname": "较早",
                    "card": "",
                    "role": "member",
                },
                "content": "较早内容",
            },
        ],
    }
    assert client.calls == [("get_group_msg_history", {"group_id": 100, "count": 20})]


def test_member_cannot_read_recent_messages_for_recall() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "message.get_recent_for_recall",
            {"limit": 2},
            tool_context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.ROLE_DENIED
    assert client.calls == []


def test_recall_rejects_a_message_from_another_group() -> None:
    client = FakeActionClient({"get_msg": {"data": {"group_id": 200}}})

    result = asyncio.run(
        runtime(client, dry_run=False).execute(
            "message.recall",
            {"message_id": 123},
            tool_context(UserRole.OWNER),
        )
    )

    assert result.code is ToolResultCode.EXECUTION_ERROR
    assert result.error == "PermissionError"
    assert client.calls == [("get_msg", {"message_id": 123})]


def test_owner_forward_scene_uses_target_nickname_and_onebot_nodes() -> None:
    client = FakeActionClient(
        {
            "get_group_member_info": {
                "data": {"user_id": 99, "nickname": "小李", "card": ""}
            },
            "send_group_forward_msg": {"status": "ok", "retcode": 0},
        }
    )
    nodes = [
        {"speaker": "target", "content": "怎么又轮到我了"},
        {"speaker": "群友甲", "content": "因为你最会整活"},
        {"speaker": "target", "content": "那我先撤退"},
    ]

    result = asyncio.run(
        runtime(client, dry_run=False).execute(
            "message.forward_scene",
            {"target_user_id": "99", "nodes": nodes},
            tool_context(UserRole.OWNER),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "node_count": 3,
        "target_nickname": "小李",
        "sent": True,
        "result": {
            "dry_run": False,
            "action": "send_group_forward_msg",
            "params": {
                "group_id": 100,
                "messages": [
                    {
                        "type": "node",
                        "data": {
                            "user_id": "99",
                            "nickname": "小李",
                            "content": [
                                {"type": "text", "data": {"text": "怎么又轮到我了"}}
                            ],
                        },
                    },
                    {
                        "type": "node",
                        "data": {
                            "user_id": "0",
                            "nickname": "群友甲",
                            "content": [
                                {"type": "text", "data": {"text": "因为你最会整活"}}
                            ],
                        },
                    },
                    {
                        "type": "node",
                        "data": {
                            "user_id": "99",
                            "nickname": "小李",
                            "content": [
                                {"type": "text", "data": {"text": "那我先撤退"}}
                            ],
                        },
                    },
                ],
            },
            "result": {"status": "ok", "retcode": 0},
        },
    }
    assert client.calls[0] == (
        "get_group_member_info",
        {"group_id": 100, "user_id": 99},
    )
    assert client.calls[1][0] == "send_group_forward_msg"


def test_non_owner_cannot_send_forward_scene() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "message.forward_scene",
            {
                "target_user_id": "99",
                "nodes": [
                    {"speaker": "target", "content": "第一条"},
                    {"speaker": "群友甲", "content": "第二条"},
                    {"speaker": "群友乙", "content": "第三条"},
                ],
            },
            tool_context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.ROLE_DENIED
    assert client.calls == []


def test_admin_mutation_is_dry_run_by_default() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "group.mute_member",
            {"user_id": "99", "duration_seconds": 60},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "dry_run": True,
        "action": "set_group_ban",
        "params": {"group_id": 100, "user_id": 99, "duration": 60},
    }
    assert client.calls == []


def test_mute_uses_short_default_when_duration_is_omitted() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "group.mute_member",
            {"user_id": "99"},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "dry_run": True,
        "action": "set_group_ban",
        "params": {"group_id": 100, "user_id": 99, "duration": 60},
    }
    assert client.calls == []


def test_disabled_dry_run_maps_mute_to_onebot_action() -> None:
    client = FakeActionClient({"set_group_ban": {"status": "ok", "retcode": 0}})

    result = asyncio.run(
        runtime(client, dry_run=False).execute(
            "group.unmute_member",
            {"user_id": "99"},
            tool_context(UserRole.OWNER),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "dry_run": False,
        "action": "set_group_ban",
        "params": {"group_id": 100, "user_id": 99, "duration": 0},
        "result": {"status": "ok", "retcode": 0},
    }
    assert client.calls == [
        ("set_group_ban", {"group_id": 100, "user_id": 99, "duration": 0})
    ]


def test_non_numeric_onebot_id_is_wrapped_without_calling_platform() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client).execute(
            "group.get_members",
            {},
            tool_context(UserRole.MEMBER, group_id="group-x"),
        )
    )

    assert result.code is ToolResultCode.EXECUTION_ERROR
    assert result.error == "ValueError"
    assert client.calls == []


def test_event_action_client_uses_event_bot_api() -> None:
    client = FakeActionClient({"ping": {"status": "ok"}})
    event = SimpleNamespace(
        bot=SimpleNamespace(api=SimpleNamespace(call_action=client.call_action))
    )

    resolved = resolve_event_action_client(event)
    assert resolved is not None
    assert asyncio.run(resolved.call_action("ping")) == {"status": "ok"}
    assert client.calls == [("ping", {})]


def test_owner_can_read_only_file_below_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")
    client = FakeActionClient({})
    runtime_instance = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        file_root=root,
    )

    result = asyncio.run(
        runtime_instance.execute(
            "file.read",
            {"path": "note.txt"},
            tool_context(UserRole.OWNER),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {
        "path": "note.txt",
        "truncated": False,
        "text": "hello",
    }


def test_web_fetch_rejects_local_targets() -> None:
    for value in ("file:///etc/passwd", "http://localhost:8080", "http://127.0.0.1"):
        try:
            _validate_public_url(value)
        except ValueError:
            continue
        raise AssertionError(f"local URL was accepted: {value}")


def test_model_ratings_is_a_public_read_only_tool() -> None:
    client = FakeActionClient({})
    ratings = ModelRatingsClient(
        loader=lambda: {
            "ok": True,
            "day": "2026-08-03",
            "timezone": "Asia/Shanghai",
            "refresh_seconds": 300,
            "updated_at": "2026-08-03T14:19:07.363Z",
            "window": "rolling_24h",
            "window_hours": 24,
            "since": "2026-08-02T14:19:07.108Z",
            "until": "2026-08-03T14:19:07.108Z",
            "source": "public_cache",
            "models": [
                {
                    "id": "deepseek-v4-flash-max",
                    "label": "DeepSeek V4 Flash max",
                    "group": "DeepSeek V4 Flash",
                    "average": 9.1,
                    "count": 149,
                }
            ],
            "history": [],
        }
    )

    result = asyncio.run(
        runtime(client, model_ratings_client=ratings).execute(
            "model.ratings",
            {"query": "deepseek", "limit": 5},
            tool_context(UserRole.MEMBER, group_id=""),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value["returned_count"] == 1  # type: ignore[index]
    assert result.value["models"][0]["label"] == (  # type: ignore[index]
        "DeepSeek V4 Flash max"
    )
    assert client.calls == []


def test_token_calculator_is_a_public_read_only_tool() -> None:
    client = FakeActionClient({})

    result = asyncio.run(
        runtime(client, token_calculator=TokenCalculator()).execute(
            "token.calculate",
            {"total_tokens_million": 1, "scene": "domestic"},
            tool_context(UserRole.MEMBER, group_id=""),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value["source"] == "TokenCal"  # type: ignore[index]
    assert result.value["estimated_total_cost_display"] == (  # type: ignore[index]
        "$0.37"
    )
    assert client.calls == []


def test_system_info_is_owner_only_and_does_not_call_onebot() -> None:
    client = FakeActionClient({})
    collector = SystemInfoCollector(sample_interval_seconds=0)

    member_result = asyncio.run(
        runtime(
            client,
            system_info_collector=collector,
        ).execute("system.info", {}, tool_context(UserRole.MEMBER, group_id=""))
    )
    owner_result = asyncio.run(
        runtime(
            client,
            system_info_collector=collector,
        ).execute("system.info", {}, tool_context(UserRole.OWNER, group_id=""))
    )

    assert member_result.code is ToolResultCode.ROLE_DENIED
    assert owner_result.code is ToolResultCode.SUCCESS
    assert owner_result.value["status"] == "ok"  # type: ignore[index]
    assert client.calls == []


def test_system_token_stats_returns_observed_usage_for_owner() -> None:
    client = FakeActionClient({})
    tracker = TokenUsageTracker()
    tracker.record_usage({"input_other": 10, "input_cached": 5, "output": 3})

    result = asyncio.run(
        runtime(client, token_usage_tracker=tracker).execute(
            "system.token_stats",
            {},
            tool_context(UserRole.OWNER, group_id=""),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value["total_tokens"] == 18  # type: ignore[index]
    assert client.calls == []


def test_live_group_admin_cannot_mute_another_admin() -> None:
    client = FakeActionClient(
        {
            "get_group_member_info": {"data": {"role": "admin"}},
            "set_group_ban": {"status": "ok"},
        }
    )
    runtime_instance = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=False,
        protect_target_roles=True,
    )

    result = asyncio.run(
        runtime_instance.execute(
            "group.mute_member",
            {"user_id": "99", "duration_seconds": 60},
            tool_context(UserRole.GROUP_ADMIN),
        )
    )

    assert result.code is ToolResultCode.EXECUTION_ERROR
    assert result.error == "PermissionError"
    assert client.calls == [("get_group_member_info", {"group_id": 100, "user_id": 99})]
