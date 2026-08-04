import asyncio
from types import SimpleNamespace

from yebot.domain.identity import UserRole
from yebot.runtime.targeting import TargetResolver, TargetSource, TargetStatus
from yebot.runtime.tools import (
    ToolContext,
    build_background_tool_context,
    extract_background_event_context,
)


class FakeActionClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        return self.responses.get(action, {})


class FreshRoleActionClient(FakeActionClient):
    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__(responses)
        self.uncached_calls: list[tuple[str, dict[str, object]]] = []

    async def call_uncached(self, action: str, **params: object) -> object:
        self.uncached_calls.append((action, params))
        return await self.call_action(action, **params)


class CronEvent:
    def __init__(self, extras: dict[str, object]) -> None:
        self._extras = extras
        self.unified_msg_origin = "aiocqhttp:GroupMessage:100"
        self.message_obj = SimpleNamespace(raw_message="scheduled task")

    def get_extra(self, key: str, default: object = None) -> object:
        return self._extras.get(key, default)

    def get_platform_name(self) -> str:
        return "cron"


def test_cron_metadata_extracts_group_executor_and_run_id() -> None:
    metadata = extract_background_event_context(
        CronEvent(
            {
                "cron_payload": {
                    "session": "aiocqhttp:GroupMessage:100",
                    "sender_id": "42",
                },
                "cron_job": {
                    "id": "job-1",
                    "run_started_at": "2026-08-04T12:00:00+00:00",
                },
            }
        )
    )

    assert metadata is not None
    assert metadata.group_id == "100"
    assert metadata.executor_id == "42"
    assert metadata.platform_id == "aiocqhttp"
    assert metadata.request_id.startswith("cron:job-1:")


def test_cron_executor_group_role_is_resolved_before_gateway() -> None:
    client = FakeActionClient({"get_group_member_info": {"data": {"role": "admin"}}})
    context = asyncio.run(
        build_background_tool_context(
            CronEvent(
                {
                    "cron_payload": {
                        "session": "aiocqhttp:GroupMessage:100",
                        "sender_id": "42",
                    },
                    "cron_job": {"id": "job-1"},
                }
            ),
            owner_ids=("900",),
            action_client=client,
        )
    )

    assert context is not None
    assert context.identity.role is UserRole.GROUP_ADMIN
    assert context.identity.group_id == "100"
    assert client.calls == [("get_group_member_info", {"group_id": 100, "user_id": 42})]
    assert (
        ToolContext(
            identity=context.identity,
            target_group_id=context.group_id,
            background=context,
        ).background
        is context
    )


def test_cron_owner_does_not_need_group_role_lookup() -> None:
    client = FakeActionClient({})
    context = asyncio.run(
        build_background_tool_context(
            CronEvent(
                {
                    "cron_payload": {
                        "session": "aiocqhttp:GroupMessage:100",
                        "sender_id": "900",
                    },
                    "cron_job": {"id": "job-1"},
                }
            ),
            owner_ids=("900",),
            action_client=client,
        )
    )

    assert context is not None
    assert context.identity.role is UserRole.OWNER
    assert client.calls == []


def test_cron_group_role_lookup_bypasses_read_cache_when_available() -> None:
    client = FreshRoleActionClient(
        {"get_group_member_info": {"data": {"role": "admin"}}}
    )
    context = asyncio.run(
        build_background_tool_context(
            CronEvent(
                {
                    "cron_payload": {
                        "session": "aiocqhttp:GroupMessage:100",
                        "sender_id": "42",
                    },
                    "cron_job": {"id": "job-1"},
                }
            ),
            owner_ids=(),
            action_client=client,
        )
    )

    assert context is not None
    assert context.identity.role is UserRole.GROUP_ADMIN
    assert client.uncached_calls == [
        ("get_group_member_info", {"group_id": 100, "user_id": 42})
    ]


def test_cron_target_resolution_uses_explicit_group_without_raw_message() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": {
                "data": [{"user_id": 99, "nickname": "Alice", "card": ""}]
            }
        }
    )
    event = CronEvent({})
    result = asyncio.run(
        TargetResolver(client).resolve(
            event,
            target_hint="mute Alice",
            actor_id="42",
            group_id="100",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.NAME


def test_cron_target_resolution_can_exclude_configured_bot_id() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": [],
            "get_group_msg_history": {
                "data": {
                    "messages": [
                        {
                            "time": 20,
                            "sender": {"user_id": "1592829658", "nickname": "bot"},
                        },
                        {
                            "time": 10,
                            "sender": {"user_id": "99", "nickname": "Alice"},
                        },
                    ]
                }
            },
        }
    )
    result = asyncio.run(
        TargetResolver(client).resolve(
            CronEvent({}),
            target_hint="禁言最近说话的人",
            actor_id="42",
            bot_id="1592829658",
            group_id="100",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.RECENT_SPEAKER
