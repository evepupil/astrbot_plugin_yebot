"""OneBot action adapters for the YeBot tool catalog."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from typing import Protocol

from ...domain.identity import normalize_id
from .catalog import (
    GROUP_GET_MEMBERS,
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_UNMUTE_MEMBER,
    MESSAGE_SEND,
)
from .gateway import ToolGateway
from .models import ToolContext, ToolResult
from .registry import ToolRegistry


class ActionCallable(Protocol):
    """Callable shape shared by AstrBot's OneBot clients."""

    def __call__(self, action: str, **params: object) -> Awaitable[object] | object: ...


class OneBotActionClient:
    """Normalize sync and async OneBot action clients behind one async API."""

    def __init__(self, call_action: ActionCallable) -> None:
        self._call_action = call_action

    async def call_action(self, action: str, **params: object) -> object:
        result = self._call_action(action, **params)
        if inspect.isawaitable(result):
            return await result
        return result


def resolve_event_action_client(event: object) -> OneBotActionClient | None:
    """Resolve the OneBot action API exposed by an AstrBot message event."""

    bot = getattr(event, "bot", None)
    api = getattr(bot, "api", None)
    call_action = getattr(api, "call_action", None)
    if not callable(call_action):
        call_action = getattr(bot, "call_action", None)
    if not callable(call_action):
        return None
    return OneBotActionClient(call_action)


class OneBotToolRuntime:
    """Tool gateway wired to one OneBot action client."""

    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway

    @classmethod
    def from_client(
        cls,
        client: OneBotActionClient,
        *,
        dry_run: bool = True,
    ) -> OneBotToolRuntime:
        registry = ToolRegistry()
        handlers = _OneBotHandlers(client, dry_run=dry_run)
        registry.register(GROUP_GET_MEMBERS, handlers.get_members)
        registry.register(GROUP_KICK_MEMBER, handlers.kick_member)
        registry.register(GROUP_MUTE_MEMBER, handlers.mute_member)
        registry.register(GROUP_UNMUTE_MEMBER, handlers.unmute_member)
        registry.register(MESSAGE_SEND, handlers.send_message)
        return cls(ToolGateway(registry))

    @classmethod
    def from_event(
        cls,
        event: object,
        *,
        dry_run: bool = True,
    ) -> OneBotToolRuntime | None:
        client = resolve_event_action_client(event)
        if client is None:
            return None
        return cls.from_client(client, dry_run=dry_run)

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | object,
        context: ToolContext,
    ) -> ToolResult:
        return await self._gateway.execute(tool_name, arguments, context)


class _OneBotHandlers:
    """Concrete handlers kept private so callers use the gateway only."""

    def __init__(self, client: OneBotActionClient, *, dry_run: bool) -> None:
        self._client = client
        self._dry_run = dry_run

    async def get_members(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        del arguments
        group_id = _numeric_id(context.target_group_id, "group_id")
        response = await self._client.call_action(
            "get_group_member_list",
            group_id=group_id,
        )
        members = _extract_member_list(response)
        return {
            "group_id": str(group_id),
            "member_count": len(members),
            "members": [_sanitize_member(member) for member in members],
        }

    async def kick_member(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        group_id = _numeric_id(context.target_group_id, "group_id")
        user_id = _numeric_id(arguments["user_id"], "user_id")
        params: dict[str, object] = {"group_id": group_id, "user_id": user_id}
        return await self._mutating_action("set_group_kick", params)

    async def mute_member(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        group_id = _numeric_id(context.target_group_id, "group_id")
        user_id = _numeric_id(arguments["user_id"], "user_id")
        duration = arguments["duration_seconds"]
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise ValueError("duration_seconds must be an integer")
        params: dict[str, object] = {
            "group_id": group_id,
            "user_id": user_id,
            "duration": duration,
        }
        return await self._mutating_action("set_group_ban", params)

    async def unmute_member(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        group_id = _numeric_id(context.target_group_id, "group_id")
        user_id = _numeric_id(arguments["user_id"], "user_id")
        params: dict[str, object] = {
            "group_id": group_id,
            "user_id": user_id,
            "duration": 0,
        }
        return await self._mutating_action("set_group_ban", params)

    async def send_message(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        group_id = _numeric_id(context.target_group_id, "group_id")
        message = arguments["message"]
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        params: dict[str, object] = {"group_id": group_id, "message": message}
        return await self._mutating_action("send_group_msg", params)

    async def _mutating_action(
        self,
        action: str,
        params: Mapping[str, object],
    ) -> object:
        if self._dry_run:
            return {"dry_run": True, "action": action, "params": params}
        response = await self._client.call_action(action, **params)
        return {"dry_run": False, "action": action, "result": _safe_result(response)}


def _numeric_id(value: object, name: str) -> int:
    normalized = normalize_id(value)
    if not normalized.isdecimal():
        raise ValueError(f"{name} must be a numeric ID")
    return int(normalized)


def _extract_member_list(response: object) -> list[Mapping[str, object]]:
    candidate: object = response
    if isinstance(response, Mapping):
        data = response.get("data")
        candidate = data if data is not None else response.get("members")
    if not isinstance(candidate, list):
        raise ValueError("OneBot returned no member list")
    return [item for item in candidate if isinstance(item, Mapping)]


def _sanitize_member(member: Mapping[str, object]) -> dict[str, str]:
    user_id = normalize_id(member.get("user_id"))
    if not user_id:
        raise ValueError("OneBot returned a member without user_id")
    return {
        "user_id": user_id,
        "nickname": _safe_text(member.get("nickname")),
        "card": _safe_text(member.get("card")),
        "role": _safe_text(member.get("role")),
    }


def _safe_text(value: object, limit: int = 128) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _safe_result(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            _safe_text(key, 64): _safe_scalar(item)
            for key, item in value.items()
            if isinstance(key, str) and _is_scalar(item)
        }
    if isinstance(value, list):
        return [_safe_scalar(item) for item in value if _is_scalar(item)]
    return _safe_scalar(value)


def _is_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool)


def _safe_scalar(value: object) -> str | int | float | bool:
    if isinstance(value, str):
        return value.strip()[:256]
    if isinstance(value, int | float | bool):
        return value
    return ""
