"""AstrBot entry point for YeBot."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextlib import suppress
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
    from .yebot.runtime.guardrails import GuardrailManager, GuardrailSettings
    from .yebot.runtime.jobs import Job, JobScheduler, JsonJobStore
    from .yebot.runtime.observer import observe_event
    from .yebot.runtime.release import AuditLogWriter, RuntimeMetrics
    from .yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from .yebot.runtime.tools.onebot import (
        OneBotActionClient,
        OneBotToolRuntime,
        resolve_event_action_client,
    )
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
    from yebot.runtime.guardrails import GuardrailManager, GuardrailSettings
    from yebot.runtime.jobs import Job, JobScheduler, JsonJobStore
    from yebot.runtime.observer import observe_event
    from yebot.runtime.release import AuditLogWriter, RuntimeMetrics
    from yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from yebot.runtime.tools.onebot import (
        OneBotActionClient,
        OneBotToolRuntime,
        resolve_event_action_client,
    )


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


def _as_text(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


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
- 踢人工具返回 confirmation_required 时，只展示确认编号并等待用户明确确认；
  不要在同一轮自动调用 yebot_confirm_action。
- 用户明确确认后，调用 yebot_confirm_action；确认编号只能由原操作者在原群使用一次。
- 用户要求稍后提醒、查看提醒或管理提醒时，使用对应的 yebot_reminder_* 工具；
  普通回复不要创建任务。
- 只有主人明确要求读取本地文件或网页时，才调用 yebot_file_read 或 yebot_web_fetch。
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
        self._audit_writer = AuditLogWriter(
            _as_text(values.get("audit_log_path"), "data/yebot_audit.jsonl")
        )
        self._metrics = RuntimeMetrics()
        self._guardrails = GuardrailManager(
            GuardrailSettings(
                confirmation_ttl_seconds=_as_int(
                    values.get("confirmation_ttl_seconds"), 120
                ),
                daily_action_limit=_as_int(values.get("daily_action_limit"), 100),
                daily_kick_limit=_as_int(values.get("daily_kick_limit"), 20),
                max_concurrent_actions=_as_int(values.get("max_concurrent_actions"), 2),
            ),
            protected_target_ids=tuple((*self._owner_ids, self._bot_id)),
            audit_sink=self._audit_writer.append,
        )
        self._job_scheduler = JobScheduler(
            JsonJobStore(
                _as_text(values.get("job_store_path"), "data/yebot_jobs.json")
            ),
            metrics=self._metrics,
        )
        self._file_root = _as_text(values.get("file_root"), "data/yebot_files")
        self._job_task: asyncio.Task[None] | None = None
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
        confirmation_token: str = "",
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

        await self._ensure_job_worker(event)
        runtime = OneBotToolRuntime.from_event(
            event,
            dry_run=self._tool_dry_run,
            guardrails=self._guardrails,
            scheduler=self._job_scheduler,
            file_root=self._file_root,
            protect_target_roles=True,
            metrics=self._metrics,
        )
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
            confirmation_token=confirmation_token,
            protected_target_ids=tuple((*self._owner_ids, self._bot_id)),
        )
        return await runtime.execute(normalized_name, arguments, context)

    async def confirm_tool(
        self,
        event: AstrMessageEvent,
        confirmation_id: str,
        *,
        request_id: str = "",
    ) -> ToolResult:
        """Execute a pending high-risk action for the current actor and group."""

        raw_event = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_event, Mapping):
            return ToolResult(
                "confirmation",
                ToolResultCode.EXECUTION_ERROR,
                error="event unavailable",
            )
        if self._observe_only:
            return ToolResult(
                "confirmation",
                ToolResultCode.EXECUTION_DISABLED,
                error="observe-only mode",
            )
        await self._ensure_job_worker(event)
        runtime = OneBotToolRuntime.from_event(
            event,
            dry_run=self._tool_dry_run,
            guardrails=self._guardrails,
            scheduler=self._job_scheduler,
            file_root=self._file_root,
            protect_target_roles=True,
            metrics=self._metrics,
        )
        if runtime is None:
            return ToolResult(
                "confirmation",
                ToolResultCode.EXECUTION_ERROR,
                error="action client unavailable",
            )
        identity = parse_identity(raw_event, self._owner_ids)
        context = ToolContext(
            identity=identity,
            target_group_id=normalize_id(raw_event.get("group_id")) or None,
            request_id=request_id or _request_id(event),
            protected_target_ids=tuple((*self._owner_ids, self._bot_id)),
        )
        return await runtime.confirm(confirmation_id, context)

    async def _ensure_job_worker(self, event: AstrMessageEvent) -> None:
        if self._job_task is not None and not self._job_task.done():
            return
        client = resolve_event_action_client(event)
        if client is None:
            return
        self._job_task = asyncio.create_task(self._job_loop(client))

    async def _job_loop(self, client: OneBotActionClient) -> None:
        async def execute(job: Job) -> None:
            if self._tool_dry_run:
                raise RuntimeError("dry_run_enabled")
            message = job.payload.get("message")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("reminder_message_missing")
            group_id = normalize_id(job.group_id)
            if not group_id.isdecimal():
                raise ValueError("reminder_group_id_invalid")
            await client.call_action(
                "send_group_msg",
                group_id=int(group_id),
                message=message,
            )

        while True:
            await self._job_scheduler.run_due(execute)
            await asyncio.sleep(1)

    async def terminate(self) -> None:
        if self._job_task is None:
            return
        self._job_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._job_task
        self._job_task = None

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
                "reminder.list": "yebot_reminder_list",
                "file.read": "yebot_file_read",
                "web.fetch": "yebot_web_fetch",
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

    @filter.llm_tool(name="yebot_confirm_action")
    async def llm_confirm_action(
        self,
        event: AstrMessageEvent,
        confirmation_id: str,
    ) -> str:
        """确认当前群中由同一操作者发起的待执行高风险动作。"""

        result = await self.confirm_tool(event, confirmation_id)
        return json.dumps(
            {
                "status": result.code.value,
                "result": result.value,
                "error": result.error,
            },
            ensure_ascii=False,
            default=str,
        )

    @filter.llm_tool(name="yebot_reminder_create")
    async def llm_reminder_create(
        self,
        event: AstrMessageEvent,
        delay_seconds: float,
        message: str,
    ) -> str:
        """在当前群创建一条延时提醒。"""

        delay: object = delay_seconds
        if isinstance(delay_seconds, float) and delay_seconds.is_integer():
            delay = int(delay_seconds)
        result = await self._run_single_tool(
            event,
            "reminder.create",
            {"delay_seconds": delay, "message": message},
        )
        return self._encode_run(result)

    @filter.llm_tool(name="yebot_reminder_list")
    async def llm_reminder_list(self, event: AstrMessageEvent) -> str:
        """列出当前群中当前操作者可见的提醒任务。"""

        return self._encode_run(await self._run_single_tool(event, "reminder.list", {}))

    @filter.llm_tool(name="yebot_reminder_cancel")
    async def llm_reminder_cancel(
        self,
        event: AstrMessageEvent,
        job_id: str,
    ) -> str:
        """取消一条提醒任务。"""

        return self._encode_run(
            await self._run_single_tool(event, "reminder.cancel", {"job_id": job_id})
        )

    @filter.llm_tool(name="yebot_reminder_pause")
    async def llm_reminder_pause(
        self,
        event: AstrMessageEvent,
        job_id: str,
    ) -> str:
        """暂停一条提醒任务。"""

        return self._encode_run(
            await self._run_single_tool(event, "reminder.pause", {"job_id": job_id})
        )

    @filter.llm_tool(name="yebot_reminder_resume")
    async def llm_reminder_resume(
        self,
        event: AstrMessageEvent,
        job_id: str,
    ) -> str:
        """恢复一条已暂停的提醒任务。"""

        return self._encode_run(
            await self._run_single_tool(event, "reminder.resume", {"job_id": job_id})
        )

    @filter.llm_tool(name="yebot_file_read")
    async def llm_file_read(
        self,
        event: AstrMessageEvent,
        path: str,
        max_bytes: float = 20000,
    ) -> str:
        """读取配置根目录下的受限文本文件。"""

        limit: object = max_bytes
        if isinstance(max_bytes, float) and max_bytes.is_integer():
            limit = int(max_bytes)
        return self._encode_run(
            await self._run_single_tool(
                event, "file.read", {"path": path, "max_bytes": limit}
            )
        )

    @filter.llm_tool(name="yebot_web_fetch")
    async def llm_web_fetch(
        self,
        event: AstrMessageEvent,
        url: str,
        max_bytes: float = 20000,
    ) -> str:
        """读取公开网页的受限文本内容。"""

        limit: object = max_bytes
        if isinstance(max_bytes, float) and max_bytes.is_integer():
            limit = int(max_bytes)
        return self._encode_run(
            await self._run_single_tool(
                event, "web.fetch", {"url": url, "max_bytes": limit}
            )
        )

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
