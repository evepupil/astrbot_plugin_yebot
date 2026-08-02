import asyncio
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.memory import MemoryService, SQLiteMemoryStore
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
) -> OneBotToolRuntime:
    return OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=dry_run,
        memory_service=memory_service,
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
