import asyncio
from collections.abc import Mapping

import pytest

from yebot.domain.identity import Identity, UserRole
from yebot.domain.permissions import CapabilityPolicy, PermissionScope
from yebot.runtime.guardrails import GuardrailManager
from yebot.runtime.tools import (
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_SET_MEMBER_NICKNAME,
    ParameterSpec,
    ParameterType,
    ToolContext,
    ToolDefinition,
    ToolGateway,
    ToolRegistrationError,
    ToolRegistry,
    ToolResultCode,
    ToolRisk,
    is_observe_only_allowed_tool,
)


def context(role: UserRole, group_id: str = "100") -> ToolContext:
    return ToolContext(Identity("42", group_id, role, role.value))


def echo_definition(**kwargs: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "name": "group.echo",
        "description": "Return a controlled test value.",
        "permission": "message.send",
        "parameters": (ParameterSpec("text", ParameterType.STRING, min_length=1),),
    }
    defaults.update(kwargs)
    return ToolDefinition(**defaults)  # type: ignore[arg-type]


async def echo_handler(
    request_context: ToolContext,
    arguments: Mapping[str, object],
) -> object:
    return {
        "group_id": request_context.target_group_id,
        "text": arguments["text"],
    }


def registered_gateway(
    definition: ToolDefinition | None = None,
    handler: object = echo_handler,
) -> ToolGateway:
    registry = ToolRegistry()
    registry.register(
        definition or echo_definition(),
        handler,  # type: ignore[arg-type]
    )
    return ToolGateway(registry)


def test_registered_tool_executes_with_effective_group() -> None:
    result = asyncio.run(
        registered_gateway().execute(
            "GROUP.ECHO",
            {"text": "hello"},
            context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    assert result.value == {"group_id": "100", "text": "hello"}


def test_unknown_tool_is_wrapped() -> None:
    result = asyncio.run(
        registered_gateway().execute("group.unknown", {}, context(UserRole.OWNER))
    )

    assert result.code is ToolResultCode.UNKNOWN_TOOL
    assert not result.ok


def test_invalid_parameters_do_not_call_handler() -> None:
    calls = 0

    async def handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        nonlocal calls
        calls += 1
        return None

    result = asyncio.run(
        registered_gateway(handler=handler).execute(
            "group.echo",
            {"unexpected": "value"},
            context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.INVALID_PARAMETERS
    assert calls == 0


def test_group_admin_action_is_a_permission_checked_tool() -> None:
    calls = 0

    async def handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        nonlocal calls
        calls += 1
        return "kicked"

    definition = ToolDefinition(
        name="group.kick_member",
        description="Remove one member from the current group.",
        permission="group.member.kick",
        risk=ToolRisk.HIGH,
    )
    registry = ToolRegistry()
    registry.register(definition, handler)
    gateway = ToolGateway(registry)

    member_result = asyncio.run(
        gateway.execute("group.kick_member", {}, context(UserRole.MEMBER))
    )
    admin_result = asyncio.run(
        gateway.execute("group.kick_member", {}, context(UserRole.GROUP_ADMIN))
    )

    assert member_result.code is ToolResultCode.ROLE_DENIED
    assert admin_result.code is ToolResultCode.SUCCESS
    assert calls == 1


def test_group_admin_cannot_target_another_group() -> None:
    definition = ToolDefinition(
        name="group.mute_member",
        description="Mute one member in the current group.",
        permission="group.member.mute",
    )
    registry = ToolRegistry()
    registry.register(definition, echo_handler)

    result = asyncio.run(
        ToolGateway(registry).execute(
            "group.mute_member",
            {},
            ToolContext(
                Identity("42", "100", UserRole.GROUP_ADMIN, "admin"),
                target_group_id="200",
            ),
        )
    )

    assert result.code is ToolResultCode.OUT_OF_SCOPE


def test_group_tool_requires_a_group() -> None:
    result = asyncio.run(
        registered_gateway().execute(
            "group.echo",
            {"text": "hello"},
            context(UserRole.MEMBER, ""),
        )
    )

    assert result.code is ToolResultCode.GROUP_REQUIRED


def test_timeout_is_wrapped() -> None:
    async def slow_handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        await asyncio.sleep(0.05)
        return None

    result = asyncio.run(
        registered_gateway(
            echo_definition(timeout_seconds=0.001),
            slow_handler,
        ).execute("group.echo", {"text": "hello"}, context(UserRole.MEMBER))
    )

    assert result.code is ToolResultCode.TIMEOUT


def test_handler_exception_does_not_leak_message() -> None:
    async def failing_handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        raise RuntimeError("secret details")

    result = asyncio.run(
        registered_gateway(handler=failing_handler).execute(
            "group.echo",
            {"text": "hello"},
            context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.EXECUTION_ERROR
    assert result.error == "RuntimeError"


def test_tool_can_declare_its_own_permission_policy() -> None:
    definition = ToolDefinition(
        name="member.echo",
        description="A deliberately low-risk member tool.",
        permission="custom.member.echo",
        permission_policy=CapabilityPolicy(
            frozenset({UserRole.MEMBER}), PermissionScope.GLOBAL
        ),
    )

    async def member_handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        return "ok"

    registry = ToolRegistry()
    registry.register(definition, member_handler)

    result = asyncio.run(
        ToolGateway(registry).execute(
            "member.echo",
            {},
            context(UserRole.MEMBER),
        )
    )

    assert result.code is ToolResultCode.SUCCESS


def test_duplicate_tool_names_are_rejected() -> None:
    registry = ToolRegistry()
    definition = echo_definition()
    registry.register(definition, echo_handler)

    with pytest.raises(ToolRegistrationError):
        registry.register(definition, echo_handler)


def test_tool_definition_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        echo_definition(timeout_seconds=0)


def test_group_actions_have_individual_tool_permissions() -> None:
    assert GROUP_KICK_MEMBER.name == "group.kick_member"
    assert GROUP_KICK_MEMBER.permission == "group.member.kick"
    assert GROUP_MUTE_MEMBER.name == "group.mute_member"
    assert GROUP_MUTE_MEMBER.permission == "group.member.mute"
    assert GROUP_SET_MEMBER_NICKNAME.name == "group.set_member_nickname"
    assert GROUP_SET_MEMBER_NICKNAME.permission == "group.member.edit"


@pytest.mark.parametrize(
    ("tool_name", "allowed"),
    [
        ("system.info", True),
        ("SYSTEM.TOKEN_STATS", True),
        ("group.get_members", False),
        ("message.send", False),
    ],
)
def test_observe_only_mode_only_allows_system_diagnostics(
    tool_name: str, allowed: bool
) -> None:
    assert is_observe_only_allowed_tool(tool_name) is allowed


def test_gateway_requires_and_consumes_kick_confirmation() -> None:
    manager = GuardrailManager(token_factory=lambda: "confirm-tool")
    registry = ToolRegistry()
    calls: list[dict[str, object]] = []

    async def handler(
        request_context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        calls.append(dict(arguments))
        return "kicked"

    registry.register(GROUP_KICK_MEMBER, handler)
    gateway = ToolGateway(registry, guardrails=manager)

    requested = asyncio.run(
        gateway.execute(
            "group.kick_member",
            {"user_id": "99"},
            context(UserRole.GROUP_ADMIN),
        )
    )
    assert requested.code is ToolResultCode.CONFIRMATION_REQUIRED
    assert requested.value == {
        "confirmation_id": "confirm-tool",
        "tool": "group.kick_member",
        "expires_at": requested.value["expires_at"],
        "target_user_id": "99",
    }
    assert calls == []

    confirmed = asyncio.run(
        gateway.confirm(
            "confirm-tool",
            context(UserRole.GROUP_ADMIN),
        )
    )
    assert confirmed.code is ToolResultCode.SUCCESS
    assert calls == [{"user_id": "99"}]

    replayed = asyncio.run(
        gateway.confirm(
            "confirm-tool",
            context(UserRole.GROUP_ADMIN),
        )
    )
    assert replayed.code is ToolResultCode.CONFIRMATION_REPLAYED
