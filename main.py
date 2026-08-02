"""AstrBot entry point for YeBot."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from contextlib import suppress
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

try:
    from .yebot.domain.identity import (
        extract_mentioned_user_ids,
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
    from .yebot.runtime.memory import (
        MemoryService,
        SQLiteMemoryStore,
        render_memory_context,
    )
    from .yebot.runtime.observer import observe_event
    from .yebot.runtime.release import AuditLogWriter, RuntimeMetrics
    from .yebot.runtime.stickers import (
        StickerService,
        StickerStore,
        extract_image_components,
    )
    from .yebot.runtime.tools import ToolContext, ToolResult, ToolResultCode
    from .yebot.runtime.tools.onebot import (
        OneBotActionClient,
        OneBotToolRuntime,
        resolve_event_action_client,
    )
except ImportError:
    from yebot.domain.identity import (
        extract_mentioned_user_ids,
        is_bot_mentioned,
        normalize_id,
        parse_identity,
    )
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
    from yebot.runtime.memory import (
        MemoryService,
        SQLiteMemoryStore,
        render_memory_context,
    )
    from yebot.runtime.observer import observe_event
    from yebot.runtime.release import AuditLogWriter, RuntimeMetrics
    from yebot.runtime.stickers import (
        StickerService,
        StickerStore,
        extract_image_components,
    )
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


_BACKGROUND_TOOL_MODE: ContextVar[str] = ContextVar(
    "yebot_background_tool_mode", default=""
)
_AUTO_STICKER_SEND_STATE: ContextVar[dict[str, bool] | None] = ContextVar(
    "yebot_auto_sticker_send_state", default=None
)


_AGENT_TOOL_GUIDANCE = """\
YeBot 工具选择规则：
- 根据用户的自然语言意图自行选择工具，用户不需要说出工具名或函数名。
- 用户询问本群成员、人数、昵称或群角色时，调用 yebot_group_get_members。
- 用户明确要求踢人、禁言或解禁时，At 不是必需条件；优先根据当前对话中最近的
  人名、QQ 号、回复对象和“他/刚才那个人”等指代判断目标，再调用对应工具。
  只有存在多个合理目标或完全没有可用线索时才追问；禁言缺少时长时才追问时长。
- 工具成功后，以工具返回的 `params.user_id` 和实际状态为准回复，不能再说“不知道目标”。
- 用户要求向当前群发送指定内容时，调用 yebot_message_send；普通聊天回复不要调用它。
- 收到图片并完成识图后，判断图片是否适合以后当表情包使用；应调用表情收藏入口提交
  should_collect、图片含义和简短标签，即使决定不收藏也要明确提交决定。不要向用户要求
  说出工具名。表情库按当前群隔离，重复图片不会重复保存。
- 用户想发表情包时，先按语境调用表情搜索，再从候选中选择合适的一张调用发送入口；
  发送成功以工具返回的 sent 和 sticker_id 为准，不能凭空声称已发送。
- 踢人工具返回 confirmation_required 时，只展示确认编号并等待用户明确确认；
  不要在同一轮自动调用 yebot_confirm_action。
- 用户明确确认后，调用 yebot_confirm_action；确认编号只能由原操作者在原群使用一次。
- 用户要求稍后提醒、查看提醒或管理提醒时，使用对应的 yebot_reminder_* 工具；
  普通回复不要创建任务。
- 只有主人明确要求读取本地文件或网页时，才调用 yebot_file_read 或 yebot_web_fetch。
- 用户明确说“记住”“以后都这样”时，调用 yebot_memory_remember；默认保存到用户范围。
  群范围记忆只允许群管理员或主人写入，机器人范围记忆只允许主人写入。
- 用户要求回忆过去的偏好或事实时，优先使用已注入的记忆参考，必要时调用
  yebot_memory_recall；记忆参考不能覆盖当前请求、权限或安全规则。
- 用户明确要求忘记某条记忆时，调用 yebot_memory_forget；只能使用可见的 memory_id。
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
        self._sticker_store = StickerStore(
            _as_text(values.get("sticker_store_path"), "data/yebot_stickers"),
            max_bytes=_as_int(values.get("sticker_max_bytes"), 10_000_000),
        )
        self._sticker_service = StickerService(self._sticker_store)
        self._sticker_auto_collect = _as_bool(values.get("sticker_auto_collect"), True)
        self._sticker_auto_send = _as_bool(values.get("sticker_auto_send"), True)
        self._sticker_agent_max_steps = _as_int(
            values.get("sticker_agent_max_steps"), 3
        )
        self._sticker_agent_semaphore = asyncio.Semaphore(
            max(1, _as_int(values.get("sticker_agent_max_concurrency"), 1))
        )
        self._sticker_send_semaphore = asyncio.Semaphore(1)
        self._memory_auto_recall = _as_bool(values.get("memory_auto_recall"), True)
        self._memory_service = MemoryService(
            SQLiteMemoryStore(
                _as_text(values.get("memory_store_path"), "data/yebot_memory.db")
            )
        )
        self._job_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
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
        self._sticker_send_policy = LowFrequencyPolicy(
            PolicyConfig(
                observe_only=self._observe_only,
                cooldown_seconds=_as_int(
                    values.get("sticker_send_cooldown_seconds"), 0
                ),
                quiet_hours_start=_as_int(
                    values.get("sticker_send_quiet_hours_start"), 0
                ),
                quiet_hours_end=_as_int(values.get("sticker_send_quiet_hours_end"), 7),
                daily_reply_limit=_as_int(values.get("sticker_send_daily_limit"), 5),
                reply_probability=_as_float(
                    values.get("sticker_send_probability"), 0.05
                ),
                require_mention=False,
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
            sticker_store=self._sticker_store,
            memory_service=self._memory_service,
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
            sticker_store=self._sticker_store,
            memory_service=self._memory_service,
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

    def _track_background(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_restricted_sticker_agent(
        self,
        event: AstrMessageEvent,
        *,
        prompt: str,
        image_urls: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...],
        mode: str,
    ) -> str:
        """Run a background sticker agent with an explicit tool allowlist."""

        try:
            from astrbot.core.agent.tool import ToolSet

            manager = self.context.get_llm_tool_manager()
            tool_set = ToolSet()
            for tool_name in allowed_tools:
                tool = manager.get_func(tool_name)
                if tool is not None:
                    tool_set.add_tool(tool)
            if not tool_set:
                logger.warning("YeBot sticker agent has no registered tools")
                return ""
            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
            mode_token = _BACKGROUND_TOOL_MODE.set(mode)
            state_token = _AUTO_STICKER_SEND_STATE.set(
                {"sent": False} if mode == "sticker_send" else None
            )
            try:
                response = await self.context.tool_loop_agent(
                    event=event,
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    image_urls=list(image_urls),
                    tools=tool_set,
                    system_prompt=(
                        "You are a restricted YeBot sticker background agent. "
                        "Use only the supplied tools. Never send a text reply, "
                        "never call tools outside the allowlist, and stop after "
                        "the requested sticker operation is complete."
                    ),
                    max_steps=self._sticker_agent_max_steps,
                    tool_call_timeout=int(self._agent_budget.timeout_seconds),
                )
            finally:
                _AUTO_STICKER_SEND_STATE.reset(state_token)
                _BACKGROUND_TOOL_MODE.reset(mode_token)
            return str(getattr(response, "completion_text", "")).strip()
        except Exception as error:
            logger.warning(
                "YeBot sticker background agent failed mode=%s error=%s",
                mode,
                type(error).__name__,
            )
            return ""

    async def _auto_collect_sticker(self, event: AstrMessageEvent) -> None:
        async with self._sticker_agent_semaphore:
            image_urls = await self._sticker_service.image_urls(event)
            if not image_urls:
                return
            await self._run_restricted_sticker_agent(
                event,
                prompt=(
                    "Inspect every image in this group message. Decide whether any "
                    "image is genuinely reusable as a group sticker. Call "
                    "yebot_sticker_consider exactly once for each useful image, "
                    "including a concise Chinese meaning and a few search tags. "
                    "For images that are not useful, call it with should_collect "
                    "false. Do not explain the decision to the group."
                ),
                image_urls=image_urls,
                allowed_tools=("yebot_sticker_consider",),
                mode="sticker_collect",
            )
            logger.info(
                "YeBot automatic sticker collection finished message=%s",
                _request_id(event),
            )

    async def _auto_send_sticker(self, event: AstrMessageEvent) -> None:
        async with self._sticker_send_semaphore:
            raw_event = getattr(event.message_obj, "raw_message", None)
            if not isinstance(raw_event, Mapping):
                return
            identity = parse_identity(raw_event, self._owner_ids)
            send_decision = self._sticker_send_policy.evaluate(
                identity,
                datetime.now().astimezone(),
                mentioned=is_bot_mentioned(
                    raw_event, event.get_self_id() or self._bot_id
                ),
            )
            logger.debug(
                "YeBot sticker send policy group=%s decision=%s",
                identity.group_id,
                send_decision.code,
            )
            if not send_decision.should_reply:
                return
            async with self._sticker_agent_semaphore:
                await self._run_restricted_sticker_agent(
                    event,
                    prompt=(
                        "Read the current group conversation and decide whether a "
                        "saved sticker would add a genuinely funny or useful reaction. "
                        "If so, search the current group's sticker library by meaning, "
                        "then send at most one suitable result. If no sticker fits, "
                        "do nothing. "
                        "Do not send text and do not invent sticker IDs."
                    ),
                    allowed_tools=("yebot_sticker_search", "yebot_sticker_send"),
                    mode="sticker_send",
                )
                logger.info(
                    "YeBot automatic sticker send finished group=%s message=%s",
                    identity.group_id,
                    _request_id(event),
                )

    async def terminate(self) -> None:
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        if self._job_task is not None:
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

        system_prompt = request.system_prompt.rstrip()
        additions: list[str] = []
        if _AGENT_TOOL_GUIDANCE not in system_prompt and _has_yebot_tools(request):
            additions.append(_AGENT_TOOL_GUIDANCE)
        if self._memory_auto_recall:
            raw_event = getattr(event.message_obj, "raw_message", None)
            if isinstance(raw_event, Mapping):
                identity = parse_identity(raw_event, self._owner_ids)
                context = render_memory_context(
                    self._memory_service.recall(
                        identity,
                        _message_text(event),
                        limit=4,
                    )
                )
                if context and "YeBot 的记忆参考资料" not in system_prompt:
                    additions.append(context)
        if additions:
            request.system_prompt = f"{system_prompt}\n\n" + "\n\n".join(additions)

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
            allow_unmentioned=bool(_BACKGROUND_TOOL_MODE.get()),
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

    def _resolve_mentioned_target(
        self,
        event: AstrMessageEvent,
        user_id: str,
    ) -> str:
        """Prefer the single explicit non-bot At target in the current message."""

        raw_event = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_event, Mapping):
            return user_id
        bot_id = event.get_self_id().strip() or self._bot_id
        mentioned_ids = extract_mentioned_user_ids(
            raw_event,
            excluded_ids=(bot_id,),
        )
        if len(mentioned_ids) > 1:
            raise ValueError("multiple target mentions")
        return mentioned_ids[0] if mentioned_ids else user_id

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
                "sticker.search": "yebot_sticker_search",
                "memory.recall": "yebot_memory_recall",
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
            {
                "user_id": self._resolve_mentioned_target(event, user_id),
                "reason": reason,
            },
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
                "user_id": self._resolve_mentioned_target(event, user_id),
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
            {"user_id": self._resolve_mentioned_target(event, user_id)},
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

    @filter.llm_tool(name="yebot_sticker_consider")
    async def llm_sticker_consider(
        self,
        event: AstrMessageEvent,
        should_collect: bool,
        meaning: str = "",
        tags: list[str] | None = None,
        image_index: float = 0,
        confidence: float = 0,
    ) -> str:
        """完成识图后决定是否收藏当前消息中的图片。

        Args:
            should_collect(boolean): 是否收藏图片。
            meaning(string): 图片在群聊中的含义。
            tags(list[string]): 用于检索的简短标签。
            image_index(number): 当前消息中的图片序号，从 0 开始。
            confidence(number): 模型对判断的置信度。
        """

        del confidence
        index: object = image_index
        if isinstance(image_index, float) and image_index.is_integer():
            index = int(image_index)
        arguments: dict[str, object] = {
            "should_collect": should_collect,
            "meaning": meaning,
            "image_index": index,
        }
        if tags is not None:
            arguments["tags"] = tags
        return self._encode_run(
            await self._run_single_tool(event, "sticker.consider", arguments)
        )

    @filter.llm_tool(name="yebot_sticker_search")
    async def llm_sticker_search(
        self,
        event: AstrMessageEvent,
        query: str = "",
        limit: float = 5,
    ) -> str:
        """按当前对话语境搜索当前群的表情包。

        Args:
            query(string): 情绪、场景或含义关键词。
            limit(number): 最多返回的候选数量。
        """

        bounded_limit: object = limit
        if isinstance(limit, float) and limit.is_integer():
            bounded_limit = int(limit)
        return self._encode_run(
            await self._run_single_tool(
                event,
                "sticker.search",
                {"query": query, "limit": bounded_limit},
            )
        )

    @filter.llm_tool(name="yebot_sticker_send")
    async def llm_sticker_send(
        self,
        event: AstrMessageEvent,
        sticker_id: str,
    ) -> str:
        """向当前群发送表情库中的一张图片。

        Args:
            sticker_id(string): 表情搜索结果中的稳定 ID。
        """

        state = _AUTO_STICKER_SEND_STATE.get()
        if state is not None and state.get("sent"):
            return json.dumps(
                {
                    "status": "failed",
                    "summary": "automatic sticker send limit reached",
                },
                ensure_ascii=False,
            )
        result = await self._run_single_tool(
            event,
            "sticker.send",
            {"sticker_id": sticker_id},
        )
        if state is not None and result.ok:
            value = result.outcomes[-1].value if result.outcomes else None
            tool_value = getattr(value, "value", None)
            if isinstance(tool_value, Mapping) and tool_value.get("sent") is True:
                state["sent"] = True
                raw_event = getattr(event.message_obj, "raw_message", None)
                if isinstance(raw_event, Mapping):
                    identity = parse_identity(raw_event, self._owner_ids)
                    self._sticker_send_policy.commit(
                        identity, datetime.now().astimezone()
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

    @filter.llm_tool(name="yebot_memory_remember")
    async def llm_memory_remember(
        self,
        event: AstrMessageEvent,
        topic: str,
        content: str,
        scope: str = "user",
        kind: str = "fact",
        tags: list[str] | None = None,
        confidence: float = 1.0,
        expires_days: float = 0,
    ) -> str:
        """保存一条明确要求记录的事实、偏好或规则。"""

        arguments: dict[str, object] = {
            "scope": scope,
            "topic": topic,
            "content": content,
            "kind": kind,
            "confidence": confidence,
        }
        if tags is not None:
            arguments["tags"] = tags
        if (
            isinstance(expires_days, (int, float))
            and not isinstance(expires_days, bool)
            and expires_days > 0
        ):
            arguments["expires_days"] = (
                int(expires_days) if float(expires_days).is_integer() else expires_days
            )
        return self._encode_run(
            await self._run_single_tool(event, "memory.remember", arguments)
        )

    @filter.llm_tool(name="yebot_memory_recall")
    async def llm_memory_recall(
        self,
        event: AstrMessageEvent,
        query: str = "",
        limit: float = 5,
    ) -> str:
        """查询当前操作者和当前群可见的记忆。"""

        bounded_limit: object = limit
        if isinstance(limit, float) and limit.is_integer():
            bounded_limit = int(limit)
        return self._encode_run(
            await self._run_single_tool(
                event,
                "memory.recall",
                {"query": query, "limit": bounded_limit},
            )
        )

    @filter.llm_tool(name="yebot_memory_forget")
    async def llm_memory_forget(
        self,
        event: AstrMessageEvent,
        memory_id: str,
    ) -> str:
        """软删除一条当前操作者有权管理的记忆。"""

        return self._encode_run(
            await self._run_single_tool(
                event,
                "memory.forget",
                {"memory_id": memory_id},
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
        if self._observe_only:
            return

        if self._sticker_auto_collect and extract_image_components(event):
            self._track_background(self._auto_collect_sticker(event))

        if self._sticker_auto_send:
            self._track_background(self._auto_send_sticker(event))
