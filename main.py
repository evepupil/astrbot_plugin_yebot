"""AstrBot entry point for YeBot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

try:
    from .yebot.domain.identity import (
        is_bot_mentioned,
        normalize_id,
        parse_identity,
    )
    from .yebot.domain.policy import LowFrequencyPolicy, PolicyConfig
    from .yebot.runtime.agents import (
        AgentBudget,
        AgentOrchestrator,
        AgentPlanner,
        AgentRequestTracker,
        AgentRouter,
        AgentRunResult,
        MessageSummary,
        RunStatus,
        SubAgentRequest,
        SubAgentResult,
        TaskStep,
    )
    from .yebot.runtime.observer import observe_event
    from .yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from .yebot.runtime.tools.onebot import OneBotToolRuntime
except ImportError:
    from yebot.domain.identity import is_bot_mentioned, normalize_id, parse_identity
    from yebot.domain.policy import LowFrequencyPolicy, PolicyConfig
    from yebot.runtime.agents import (
        AgentBudget,
        AgentOrchestrator,
        AgentPlanner,
        AgentRequestTracker,
        AgentRouter,
        AgentRunResult,
        MessageSummary,
        RunStatus,
        SubAgentRequest,
        SubAgentResult,
        TaskStep,
    )
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


def _message_text(event: AstrMessageEvent) -> str:
    message_obj = getattr(event, "message_obj", None)
    message_str = getattr(message_obj, "message_str", "")
    return str(message_str).strip()[:4000]


def _request_id(event: AstrMessageEvent) -> str:
    message_obj = getattr(event, "message_obj", None)
    message_id = getattr(message_obj, "message_id", "")
    return str(message_id).strip() or event.unified_msg_origin


def _has_yebot_tools(request: ProviderRequest) -> bool:
    tool_set = request.func_tool
    tools = getattr(tool_set, "func_list", ()) if tool_set is not None else ()
    return any(str(getattr(tool, "name", "")).startswith("yebot_") for tool in tools)


_AGENT_TOOL_GUIDANCE = """\
YeBot 工具选择规则：
- 根据用户的自然语言意图自行选择工具，用户不需要说出工具名或函数名。
- 用户询问本群成员、人数、昵称或群角色时，调用 yebot_group_get_members。
- 用户明确要求踢人、禁言或解禁时，先确认目标 QQ 号和时长是否清楚，
  再调用对应的 YeBot 工具；信息不全就先追问。
- 用户要求向当前群发送指定内容时，调用 yebot_message_send；普通聊天回复不要调用它。
- 需要把只读查询交给专门步骤整理时，调用 yebot_delegate；SubAgent 只能使用
  提供的白名单工具，不能发消息或管理群。
- 工具返回权限拒绝、dry-run 或错误状态时，必须如实说明状态，不能声称动作已经完成。
"""


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
        self._agent_budget = AgentBudget(
            max_steps=_as_int(values.get("agent_max_steps"), 6),
            max_concurrency=_as_int(values.get("agent_max_concurrency"), 1),
            timeout_seconds=_as_float(values.get("agent_timeout_seconds"), 30.0),
        )
        self._agent_router = AgentRouter()
        self._agent_planner = AgentPlanner()
        self._agent_orchestrator = AgentOrchestrator(self._agent_budget)
        self._agent_request_tracker = AgentRequestTracker(self._agent_budget)
        self._subagent_allowed_tools = _as_id_list(
            values.get("subagent_allowed_tools", ["group.get_members"])
        )
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

        Every Agent and function-tool adapter uses this entry point. Keeping
        identity extraction here ensures all callers use the same owner and
        group-admin rules as message observation.
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

    @filter.on_llm_request()
    async def guide_agent_tool_selection(
        self,
        event: AstrMessageEvent,
        request: ProviderRequest,
    ) -> None:
        """Tell the main Agent how to choose YeBot tools from user intent."""

        del event
        if _AGENT_TOOL_GUIDANCE not in request.system_prompt and _has_yebot_tools(
            request
        ):
            request.system_prompt = (
                f"{request.system_prompt.rstrip()}\n\n{_AGENT_TOOL_GUIDANCE}"
            )

    async def _run_single_tool(
        self,
        event: AstrMessageEvent,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> AgentRunResult:
        raw_event = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_event, Mapping):
            raise ValueError("event unavailable")
        identity = parse_identity(raw_event, self._owner_ids)
        summary = MessageSummary(
            _message_text(event),
            identity.user_id,
            identity.group_id,
            identity.role,
            is_bot_mentioned(raw_event, event.get_self_id() or self._bot_id),
            _request_id(event),
        )
        route = self._agent_router.route(
            summary,
            requested_tool=tool_name,
            tool_arguments=arguments,
        )
        plan = self._agent_planner.build(route, plan_id=summary.request_id)
        if plan.steps:
            reservation = self._agent_request_tracker.reserve(summary.request_id)
            if not reservation.allowed:
                return AgentRunResult(
                    reservation.status or RunStatus.FAILED,
                    plan,
                    (),
                    reservation.summary,
                )

        async def invoke(step: TaskStep) -> ToolResult:
            return await self.execute_tool(
                event,
                step.target,
                step.arguments,
                request_id=summary.request_id,
            )

        return await self._agent_orchestrator.run(plan, tool_executor=invoke)

    async def _run_subagent(
        self,
        event: AstrMessageEvent,
        request: SubAgentRequest,
    ) -> SubAgentResult:
        try:
            from astrbot.core.agent.tool import ToolSet

            tool_set = ToolSet()
            tool_manager = self.context.get_llm_tool_manager()
            exposed_names = {
                "group.get_members": "yebot_group_get_members",
                "group.kick_member": "yebot_group_kick_member",
                "group.mute_member": "yebot_group_mute_member",
                "group.unmute_member": "yebot_group_unmute_member",
                "message.send": "yebot_message_send",
            }
            for tool_name in request.allowed_tools:
                exposed_name = exposed_names.get(tool_name)
                if exposed_name is None:
                    continue
                tool = tool_manager.get_func(exposed_name)
                if tool is not None:
                    tool_set.add_tool(tool)

            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
            response = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=provider_id,
                prompt=request.task,
                system_prompt=(
                    "You are a restricted YeBot SubAgent. Return a concise result. "
                    "Use only the supplied read-only tools. Never send messages or "
                    "perform group administration."
                ),
                tools=tool_set,
                max_steps=self._agent_budget.max_steps,
                tool_call_timeout=int(self._agent_budget.timeout_seconds),
            )
            completion = str(getattr(response, "completion_text", "")).strip()
            return SubAgentResult(True, completion, used_tools=request.allowed_tools)
        except Exception as error:
            return SubAgentResult(False, error=type(error).__name__)

    @staticmethod
    def _encode_run(result: AgentRunResult) -> str:
        values = [outcome.value for outcome in result.outcomes if outcome.ok]
        payload = {
            "status": result.status.value,
            "summary": result.summary,
            "result": values[0] if len(values) == 1 else values,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @filter.llm_tool(name="yebot_group_get_members")
    async def llm_group_get_members(self, event: AstrMessageEvent) -> str:
        """读取当前群成员。"""

        result = await self._run_single_tool(event, "group.get_members", {})
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_group_kick_member")
    async def llm_group_kick_member(
        self,
        event: AstrMessageEvent,
        user_id: str,
        reason: str = "",
    ) -> str:
        """请求移出当前群的一名成员。

        Args:
            user_id(string): 要操作的 QQ 号
            reason(string): 操作原因
        """
        result = await self._run_single_tool(
            event,
            "group.kick_member",
            {"user_id": user_id, "reason": reason},
        )
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_group_mute_member")
    async def llm_group_mute_member(
        self,
        event: AstrMessageEvent,
        user_id: str,
        duration_seconds: float,
        reason: str = "",
    ) -> str:
        """请求禁言当前群的一名成员。

        Args:
            user_id(string): 要操作的 QQ 号
            duration_seconds(number): 禁言秒数
            reason(string): 操作原因
        """
        duration: object = duration_seconds
        if isinstance(duration_seconds, float) and duration_seconds.is_integer():
            duration = int(duration_seconds)
        result = await self._run_single_tool(
            event,
            "group.mute_member",
            {
                "user_id": user_id,
                "duration_seconds": duration,
                "reason": reason,
            },
        )
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_group_unmute_member")
    async def llm_group_unmute_member(
        self,
        event: AstrMessageEvent,
        user_id: str,
    ) -> str:
        """解除当前群一名成员的禁言。

        Args:
            user_id(string): 要操作的 QQ 号
        """
        result = await self._run_single_tool(
            event,
            "group.unmute_member",
            {"user_id": user_id},
        )
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_message_send")
    async def llm_message_send(self, event: AstrMessageEvent, message: str) -> str:
        """向当前群发送一条消息。

        Args:
            message(string): 要发送的消息正文
        """
        result = await self._run_single_tool(
            event,
            "message.send",
            {"message": message},
        )
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_delegate")
    async def llm_delegate(
        self,
        event: AstrMessageEvent,
        task: str,
        agent: str = "research",
    ) -> str:
        """把只读查询交给受限 SubAgent，并返回汇总结果。

        Args:
            task(string): 要处理的只读任务
            agent(string): SubAgent 名称
        """
        raw_event = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_event, Mapping):
            return json.dumps(
                {"status": "failed", "summary": "event unavailable"},
                ensure_ascii=False,
            )
        identity = parse_identity(raw_event, self._owner_ids)
        summary = MessageSummary(
            task,
            identity.user_id,
            identity.group_id,
            identity.role,
            is_bot_mentioned(raw_event, event.get_self_id() or self._bot_id),
            _request_id(event),
        )
        route = self._agent_router.route(summary, requested_subagent=agent)
        plan = self._agent_planner.build(
            route,
            plan_id=summary.request_id,
            subagent_tools={agent.strip().lower(): self._subagent_allowed_tools},
        )
        reservation = self._agent_request_tracker.reserve(summary.request_id)
        if not reservation.allowed:
            return self._encode_run(
                AgentRunResult(
                    reservation.status or RunStatus.FAILED,
                    plan,
                    (),
                    reservation.summary,
                )
            )
        result = await self._agent_orchestrator.run(
            plan,
            subagent_executor=lambda request: self._run_subagent(event, request),
        )
        return self._encode_run(result)

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
