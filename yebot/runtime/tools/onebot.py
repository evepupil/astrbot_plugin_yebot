"""OneBot action adapters for the YeBot tool catalog."""

from __future__ import annotations

import inspect
import ipaddress
import socket
from collections.abc import Awaitable, Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ...domain.identity import normalize_id
from ..guardrails import GuardrailManager
from ..jobs import Job, JobScheduler
from ..memory import MemoryService
from ..release import RuntimeMetrics
from ..stickers import StickerService, StickerStore
from .catalog import (
    FILE_READ,
    GROUP_GET_MEMBERS,
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_UNMUTE_MEMBER,
    MEMORY_FORGET,
    MEMORY_RECALL,
    MEMORY_REMEMBER,
    MESSAGE_SEND,
    REMINDER_CANCEL,
    REMINDER_CREATE,
    REMINDER_LIST,
    REMINDER_PAUSE,
    REMINDER_RESUME,
    STICKER_CONSIDER,
    STICKER_SEARCH,
    STICKER_SEND,
    WEB_FETCH,
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
        guardrails: GuardrailManager | None = None,
        scheduler: JobScheduler | None = None,
        file_root: str | Path | None = None,
        protect_target_roles: bool = False,
        metrics: RuntimeMetrics | None = None,
        sticker_store: StickerStore | None = None,
        memory_service: MemoryService | None = None,
        event: object | None = None,
    ) -> OneBotToolRuntime:
        registry = ToolRegistry()
        handlers = _OneBotHandlers(
            client,
            dry_run=dry_run,
            scheduler=scheduler,
            file_root=file_root,
            protect_target_roles=protect_target_roles,
            sticker_service=(StickerService(sticker_store) if sticker_store else None),
            memory_service=memory_service,
            event=event,
        )
        registry.register(GROUP_GET_MEMBERS, handlers.get_members)
        registry.register(GROUP_KICK_MEMBER, handlers.kick_member)
        registry.register(GROUP_MUTE_MEMBER, handlers.mute_member)
        registry.register(GROUP_UNMUTE_MEMBER, handlers.unmute_member)
        registry.register(MESSAGE_SEND, handlers.send_message)
        if scheduler is not None:
            registry.register(REMINDER_CREATE, handlers.create_reminder)
            registry.register(REMINDER_LIST, handlers.list_reminders)
            registry.register(REMINDER_CANCEL, handlers.cancel_reminder)
            registry.register(REMINDER_PAUSE, handlers.pause_reminder)
            registry.register(REMINDER_RESUME, handlers.resume_reminder)
        registry.register(FILE_READ, handlers.read_file)
        registry.register(WEB_FETCH, handlers.fetch_web)
        if handlers.sticker_service is not None:
            registry.register(STICKER_CONSIDER, handlers.consider_sticker)
            registry.register(STICKER_SEARCH, handlers.search_stickers)
            registry.register(STICKER_SEND, handlers.send_sticker)
        if handlers.memory_service is not None:
            registry.register(MEMORY_REMEMBER, handlers.remember_memory)
            registry.register(MEMORY_RECALL, handlers.recall_memory)
            registry.register(MEMORY_FORGET, handlers.forget_memory)
        return cls(ToolGateway(registry, guardrails=guardrails, metrics=metrics))

    @classmethod
    def from_event(
        cls,
        event: object,
        *,
        dry_run: bool = True,
        guardrails: GuardrailManager | None = None,
        scheduler: JobScheduler | None = None,
        file_root: str | Path | None = None,
        protect_target_roles: bool = False,
        metrics: RuntimeMetrics | None = None,
        sticker_store: StickerStore | None = None,
        memory_service: MemoryService | None = None,
    ) -> OneBotToolRuntime | None:
        client = resolve_event_action_client(event)
        if client is None:
            return None
        return cls.from_client(
            client,
            dry_run=dry_run,
            guardrails=guardrails,
            scheduler=scheduler,
            file_root=file_root,
            protect_target_roles=protect_target_roles,
            metrics=metrics,
            sticker_store=sticker_store,
            memory_service=memory_service,
            event=event,
        )

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | object,
        context: ToolContext,
    ) -> ToolResult:
        return await self._gateway.execute(tool_name, arguments, context)

    async def confirm(
        self,
        confirmation_id: str,
        context: ToolContext,
    ) -> ToolResult:
        return await self._gateway.confirm(confirmation_id, context)


class _OneBotHandlers:
    """Concrete handlers kept private so callers use the gateway only."""

    def __init__(
        self,
        client: OneBotActionClient,
        *,
        dry_run: bool,
        scheduler: JobScheduler | None,
        file_root: str | Path | None,
        protect_target_roles: bool,
        sticker_service: StickerService | None,
        memory_service: MemoryService | None,
        event: object | None,
    ) -> None:
        self._client = client
        self._dry_run = dry_run
        self._scheduler = scheduler
        self._file_root = Path(file_root or "data/yebot_files").resolve()
        self._protect_target_roles = protect_target_roles
        self.sticker_service = sticker_service
        self.memory_service = memory_service
        self._event = event

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
        await self._check_target_role(context, group_id, user_id)
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
        await self._check_target_role(context, group_id, user_id)
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
        await self._check_target_role(context, group_id, user_id)
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

    async def create_reminder(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self._scheduler is None:
            raise RuntimeError("job scheduler unavailable")
        delay = arguments["delay_seconds"]
        message = arguments["message"]
        if not isinstance(delay, int) or isinstance(delay, bool):
            raise ValueError("delay_seconds must be an integer")
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        return _serialize_job(
            self._scheduler.create_reminder(
                context.identity,
                delay_seconds=delay,
                message=message,
            )
        )

    async def list_reminders(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        del arguments
        if self._scheduler is None:
            raise RuntimeError("job scheduler unavailable")
        return {
            "jobs": [
                _serialize_job(job)
                for job in self._scheduler.list_for(context.identity)
            ]
        }

    async def cancel_reminder(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self._scheduler is None:
            raise RuntimeError("job scheduler unavailable")
        return _serialize_job(
            self._scheduler.cancel(context.identity, str(arguments["job_id"]))
        )

    async def pause_reminder(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self._scheduler is None:
            raise RuntimeError("job scheduler unavailable")
        return _serialize_job(
            self._scheduler.pause(context.identity, str(arguments["job_id"]))
        )

    async def resume_reminder(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self._scheduler is None:
            raise RuntimeError("job scheduler unavailable")
        return _serialize_job(
            self._scheduler.resume(context.identity, str(arguments["job_id"]))
        )

    async def read_file(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        del context
        relative = arguments["path"]
        if not isinstance(relative, str):
            raise ValueError("path must be a string")
        limit = arguments.get("max_bytes", 20_000)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("max_bytes must be an integer")
        path = (self._file_root / relative).resolve()
        try:
            path.relative_to(self._file_root)
        except ValueError as error:
            raise PermissionError("file path is outside configured root") from error
        if not path.is_file():
            raise FileNotFoundError("file not found")
        data = path.read_bytes()[:limit]
        return {
            "path": str(path.relative_to(self._file_root)),
            "truncated": path.stat().st_size > limit,
            "text": data.decode("utf-8", errors="replace"),
        }

    async def fetch_web(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        del context
        url = arguments["url"]
        if not isinstance(url, str):
            raise ValueError("url must be a string")
        limit = arguments.get("max_bytes", 20_000)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("max_bytes must be an integer")
        _validate_public_url(url)
        request = Request(url, headers={"User-Agent": "YeBot/0.1"})
        with urlopen(request, timeout=10) as response:
            data = response.read(limit)
            content_type = response.headers.get("Content-Type", "")[:128]
            final_url = response.geturl()[:2048]
        return {
            "url": final_url,
            "content_type": content_type,
            "truncated": len(data) >= limit,
            "text": data.decode("utf-8", errors="replace"),
        }

    async def consider_sticker(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.sticker_service is None or self._event is None:
            raise RuntimeError("sticker service unavailable")
        return await self.sticker_service.consider(
            self._event, context.identity, arguments
        )

    async def search_stickers(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.sticker_service is None:
            raise RuntimeError("sticker service unavailable")
        return self.sticker_service.search(context.identity, arguments)

    async def send_sticker(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.sticker_service is None:
            raise RuntimeError("sticker service unavailable")
        sticker_id = arguments["sticker_id"]
        if not isinstance(sticker_id, str):
            raise ValueError("sticker_id must be a string")
        record, path = self.sticker_service.get_for_send(context.identity, sticker_id)
        params: dict[str, object] = {
            "group_id": _numeric_id(context.target_group_id, "group_id"),
            "message": [
                {"type": "image", "data": {"file": path.as_uri()}},
            ],
        }
        result = await self._mutating_action("send_group_msg", params)
        dry_run = isinstance(result, Mapping) and result.get("dry_run") is True
        if not dry_run:
            self.sticker_service.mark_used(context.identity, record.sticker_id)
        return {
            "sticker_id": record.sticker_id,
            "meaning": record.meaning,
            "sent": not dry_run,
            "image": path.as_uri(),
            "result": result,
        }

    async def remember_memory(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.memory_service is None:
            raise RuntimeError("memory service unavailable")
        scope = arguments.get("scope", "user")
        topic = arguments["topic"]
        content = arguments["content"]
        kind = arguments.get("kind", "fact")
        tags = arguments.get("tags", [])
        confidence = arguments.get("confidence", 1.0)
        expires_days = arguments.get("expires_days")
        if not isinstance(scope, str) or not isinstance(topic, str):
            raise ValueError("memory scope and topic must be text")
        if not isinstance(content, str) or not isinstance(kind, str):
            raise ValueError("memory content and kind must be text")
        if not isinstance(tags, list):
            raise ValueError("memory tags must be a list")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("memory confidence must be numeric")
        if expires_days is not None and (
            not isinstance(expires_days, int) or isinstance(expires_days, bool)
        ):
            raise ValueError("memory expiry must be an integer")
        record = self.memory_service.remember(
            context.identity,
            scope=scope,
            topic=topic,
            content=content,
            kind=kind,
            tags=tags,
            confidence=float(confidence),
            expires_days=expires_days,
            request_id=context.request_id,
        )
        return {
            "memory_id": record.memory_id,
            "scope": record.scope.value,
            "topic": record.topic,
            "status": record.status.value,
        }

    async def recall_memory(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.memory_service is None:
            raise RuntimeError("memory service unavailable")
        query = arguments.get("query", "")
        limit = arguments.get("limit", 5)
        if not isinstance(query, str):
            raise ValueError("memory query must be text")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("memory limit must be an integer")
        records = self.memory_service.recall(
            context.identity,
            query,
            limit=limit,
            include_unmatched=True,
        )
        return {
            "memories": [
                {
                    "memory_id": record.memory_id,
                    "scope": record.scope.value,
                    "kind": record.kind.value,
                    "topic": record.topic,
                    "content": record.content,
                    "tags": list(record.tags),
                }
                for record in records
            ],
        }

    async def forget_memory(
        self,
        context: ToolContext,
        arguments: Mapping[str, object],
    ) -> object:
        if self.memory_service is None:
            raise RuntimeError("memory service unavailable")
        memory_id = arguments["memory_id"]
        if not isinstance(memory_id, str):
            raise ValueError("memory_id must be text")
        return {
            "memory_id": memory_id,
            "forgotten": self.memory_service.forget(context.identity, memory_id),
        }

    async def _mutating_action(
        self,
        action: str,
        params: Mapping[str, object],
    ) -> object:
        if self._dry_run:
            return {"dry_run": True, "action": action, "params": params}
        response = await self._client.call_action(action, **params)
        return {
            "dry_run": False,
            "action": action,
            "params": params,
            "result": _safe_result(response),
        }

    async def _check_target_role(
        self,
        context: ToolContext,
        group_id: int,
        user_id: int,
    ) -> None:
        if not self._protect_target_roles or self._dry_run:
            return
        response = await self._client.call_action(
            "get_group_member_info",
            group_id=group_id,
            user_id=user_id,
        )
        role = _member_role(response)
        if role == "owner" or (
            role == "admin" and context.identity.role.value != "owner"
        ):
            raise PermissionError("target member role is protected")


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


def _member_role(response: object) -> str:
    candidate: object = response
    if isinstance(response, Mapping) and isinstance(response.get("data"), Mapping):
        candidate = response["data"]
    if not isinstance(candidate, Mapping):
        return ""
    role = candidate.get("role")
    return role.strip().lower() if isinstance(role, str) else ""


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


def _serialize_job(job: Job) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "kind": job.kind.value,
        "status": job.status.value,
        "group_id": job.group_id,
        "run_at": job.run_at.isoformat(),
        "attempts": job.attempts,
        "last_error": job.last_error,
    }


def _validate_public_url(value: str) -> None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only public HTTP(S) URLs are supported")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("local hosts are not allowed")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise ValueError("URL host cannot be resolved") from error
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if (
            parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_reserved
            or parsed_address.is_unspecified
        ):
            raise ValueError("private or local URL hosts are not allowed")


def _is_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool)


def _safe_scalar(value: object) -> str | int | float | bool:
    if isinstance(value, str):
        return value.strip()[:256]
    if isinstance(value, int | float | bool):
        return value
    return ""
