"""AstrBot entry point for YeBot."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from .yebot.domain.identity import normalize_id, parse_identity
    from .yebot.domain.policy import LowFrequencyPolicy, PolicyConfig
    from .yebot.runtime.observer import observe_event
    from .yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from .yebot.runtime.tools.onebot import OneBotToolRuntime
except ImportError:
    from yebot.domain.identity import normalize_id, parse_identity
    from yebot.domain.policy import LowFrequencyPolicy, PolicyConfig
    from yebot.runtime.observer import observe_event
    from yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from yebot.runtime.tools.onebot import OneBotToolRuntime


def _as_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _as_float(value: object, default: float) -> float:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else default
    )


def _as_id_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple | set):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


@register(
    "astrbot_plugin_yebot",
    "YeBot",
    "QQ 机器人分阶段插件：消息观察、身份权限、工具网关与 Agent 编排",
    "0.1.0",
)
class YeBot(Star):
    """YeBot runtime with observation and permission-gated tool execution."""

    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context, config)
        values: Mapping[str, Any] = config or {}
        configured_owner_ids = _as_id_list(values.get("owner_qq_ids"))
        astrbot_config = context.get_config()
        astrbot_owner_ids = _as_id_list(astrbot_config.get("admins_id"))
        self._owner_ids = tuple(
            dict.fromkeys((*configured_owner_ids, *astrbot_owner_ids))
        )
        self._bot_id = str(values.get("bot_qq_id", "")).strip()
        self._observe_only = _as_bool(values.get("observe_only"), True)
        self._tool_dry_run = _as_bool(values.get("tool_dry_run"), True)
        self._policy = LowFrequencyPolicy(
            PolicyConfig(
                observe_only=self._observe_only,
                cooldown_seconds=_as_int(values.get("cooldown_seconds"), 60),
                quiet_hours_start=_as_int(values.get("quiet_hours_start"), 0),
                quiet_hours_end=_as_int(values.get("quiet_hours_end"), 7),
                daily_reply_limit=_as_int(values.get("daily_reply_limit"), 20),
                reply_probability=_as_float(values.get("reply_probability"), 0.2),
                require_mention=_as_bool(values.get("require_mention"), True),
            )
        )

    async def execute_tool(
        self,
        event: AstrMessageEvent,
        tool_name: str,
        arguments: Mapping[str, object] | object,
        *,
        request_id: str = "",
        target_group_id: str | None = None,
    ) -> ToolResult:
        """Execute a registered tool for a platform event.

        M5 will call this entry point after routing an agent request. Keeping
        identity extraction here ensures every future caller uses the same
        owner and group-admin rules as message observation.
        """

        raw_event = getattr(event.message_obj, "raw_message", None)
        normalized_name = tool_name.strip().lower()
        if not isinstance(raw_event, Mapping):
            return ToolResult(
                normalized_name,
                ToolResultCode.EXECUTION_ERROR,
                error="event unavailable",
            )
        if self._observe_only:
            return ToolResult(
                normalized_name,
                ToolResultCode.EXECUTION_DISABLED,
                error="observe-only mode",
            )

        runtime = OneBotToolRuntime.from_event(event, dry_run=self._tool_dry_run)
        if runtime is None:
            return ToolResult(
                normalized_name,
                ToolResultCode.EXECUTION_ERROR,
                error="action client unavailable",
            )

        identity = parse_identity(raw_event, self._owner_ids)
        context = ToolContext(
            identity=identity,
            target_group_id=normalize_id(target_group_id)
            or normalize_id(raw_event.get("group_id"))
            or None,
            request_id=request_id,
        )
        return await runtime.execute(normalized_name, arguments, context)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def observe_group(self, event: AstrMessageEvent) -> None:
        """Analyze a group message and emit a redacted debug record only."""

        raw_event = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_event, Mapping):
            return
        event_bot_id = event.get_self_id().strip()
        observation = observe_event(
            raw_event,
            owner_ids=self._owner_ids,
            bot_id=event_bot_id or self._bot_id,
            policy=self._policy,
            now=datetime.now().astimezone(),
        )
        if observation is None:
            return
        logger.debug(
            "YeBot observed group=%s user=%s role=%s mentioned=%s decision=%s",
            observation.identity.group_id,
            observation.identity.user_id,
            observation.identity.role,
            observation.mentioned,
            observation.decision.code,
        )
