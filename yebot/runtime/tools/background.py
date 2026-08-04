"""Explicit context for AstrBot cron-triggered tool execution."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ...domain.identity import Identity, UserRole, normalize_id, normalize_id_list
from ..jobs.native_access import group_scope_from_session


class ToolActionClient(Protocol):
    """The small OneBot action surface needed by background tools."""

    def call_action(
        self, action: str, **params: object
    ) -> Awaitable[object] | object: ...


@dataclass(frozen=True, slots=True)
class BackgroundEventContext:
    """Metadata carried by AstrBot's active-agent cron event."""

    group_id: str
    executor_id: str
    request_id: str
    platform_id: str = ""
    source: str = "astrbot_cron"

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", normalize_id(self.group_id))
        object.__setattr__(self, "executor_id", normalize_id(self.executor_id))
        object.__setattr__(self, "request_id", self.request_id.strip()[:160])
        object.__setattr__(self, "platform_id", self.platform_id.strip()[:120])
        object.__setattr__(self, "source", self.source.strip()[:64])


@dataclass(frozen=True, slots=True)
class BackgroundToolContext:
    """Identity and platform bridge explicitly authorized for one background run."""

    identity: Identity
    group_id: str
    request_id: str
    action_client: ToolActionClient | None = None
    event: object | None = None
    source: str = "astrbot_cron"

    def __post_init__(self) -> None:
        group_id = normalize_id(self.group_id) or self.identity.group_id
        if group_id != self.identity.group_id:
            raise ValueError("background group must match executor identity")
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "request_id", self.request_id.strip()[:160])
        object.__setattr__(self, "source", self.source.strip()[:64])


def extract_background_event_context(event: object) -> BackgroundEventContext | None:
    """Extract explicit cron metadata without treating the cron event as QQ data."""

    get_extra = getattr(event, "get_extra", None)
    cron_payload = get_extra("cron_payload", None) if callable(get_extra) else None
    cron_job = get_extra("cron_job", None) if callable(get_extra) else None
    if not isinstance(cron_payload, Mapping):
        cron_payload = {}
    if not isinstance(cron_job, Mapping):
        cron_job = {}

    platform_name = ""
    get_platform_name = getattr(event, "get_platform_name", None)
    if callable(get_platform_name):
        value = get_platform_name()
        if isinstance(value, str):
            platform_name = value.strip()
    is_cron = platform_name.lower() == "cron" or bool(cron_payload or cron_job)
    if not is_cron:
        return None

    session = _text(cron_payload.get("session"))
    if not session:
        session = _text(getattr(event, "unified_msg_origin", ""))
    scope = group_scope_from_session(session)
    explicit_group_id = normalize_id(cron_payload.get("group_id"))
    group_id = explicit_group_id or (scope[1] if scope is not None else "")

    executor_id = normalize_id(
        cron_payload.get("executor_id") or cron_payload.get("sender_id")
    )
    if not executor_id and not group_id:
        get_sender_id = getattr(event, "get_sender_id", None)
        if callable(get_sender_id):
            executor_id = normalize_id(get_sender_id())

    job_id = _text(cron_job.get("id"))
    started_at = _text(cron_job.get("run_started_at"))
    request_id = ":".join(part for part in ("cron", job_id, started_at) if part)
    if not request_id:
        message_obj = getattr(event, "message_obj", None)
        request_id = _text(getattr(message_obj, "message_id", ""))
    if not request_id:
        request_id = session

    platform_id = _text(cron_payload.get("platform_id"))
    if not platform_id and scope is not None:
        platform_id = scope[0]
    if not platform_id:
        platform_id = platform_name

    if not executor_id:
        return None
    return BackgroundEventContext(
        group_id=group_id,
        executor_id=executor_id,
        request_id=request_id,
        platform_id=platform_id,
    )


async def build_background_tool_context(
    event: object,
    owner_ids: Iterable[str],
    action_client: ToolActionClient | None,
) -> BackgroundToolContext | None:
    """Resolve a cron actor and group role before entering the normal gateway."""

    metadata = extract_background_event_context(event)
    if metadata is None:
        return None

    owner_set = set(normalize_id_list(tuple(owner_ids)))
    if metadata.executor_id in owner_set:
        role = UserRole.OWNER
        sender_role = "owner"
    else:
        sender_role = "member"
        if metadata.group_id and action_client is not None:
            sender_role = await _lookup_group_role(
                action_client,
                metadata.group_id,
                metadata.executor_id,
            )
        role = (
            UserRole.GROUP_ADMIN
            if metadata.group_id and sender_role in {"owner", "admin"}
            else UserRole.MEMBER
        )

    identity = Identity(
        user_id=metadata.executor_id,
        group_id=metadata.group_id,
        role=role,
        sender_role=sender_role,
    )
    return BackgroundToolContext(
        identity=identity,
        group_id=metadata.group_id,
        request_id=metadata.request_id,
        action_client=action_client,
        event=event,
        source=metadata.source,
    )


async def _lookup_group_role(
    action_client: ToolActionClient,
    group_id: str,
    executor_id: str,
) -> str:
    try:
        # Group roles can change while a cron job is waiting.  Prefer the
        # uncached OneBot path when the shared client exposes it; simple test
        # and adapter clients still use the ordinary action method.
        call_action = getattr(action_client, "call_uncached", None)
        if not callable(call_action):
            call_action = action_client.call_action
        response = call_action(
            "get_group_member_info",
            group_id=int(group_id),
            user_id=int(executor_id),
        )
        response = await response if inspect.isawaitable(response) else response
    except Exception:  # noqa: BLE001 - lookup failure stays least-privileged
        return "member"

    data: object = response
    if isinstance(response, Mapping):
        data = response.get("data", response)
    if isinstance(data, Mapping):
        role = _text(data.get("role")).lower()
        if role in {"owner", "admin", "member"}:
            return role
    return "member"


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return str(value).strip() if value else ""


__all__ = [
    "BackgroundEventContext",
    "BackgroundToolContext",
    "ToolActionClient",
    "build_background_tool_context",
    "extract_background_event_context",
]
