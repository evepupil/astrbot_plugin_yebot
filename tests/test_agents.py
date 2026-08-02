import asyncio

import pytest

from yebot.domain.identity import UserRole
from yebot.runtime.agents import (
    AgentBudget,
    AgentOrchestrator,
    AgentPlan,
    AgentPlanner,
    AgentRouter,
    MessageSummary,
    RouteKind,
    RunStatus,
    StepKind,
    SubAgentRequest,
    SubAgentResult,
    TaskStep,
)


def summary(*, mentioned: bool = True, text: str = "查一下") -> MessageSummary:
    return MessageSummary(text, "42", "100", UserRole.MEMBER, mentioned)


def test_router_returns_explainable_decisions() -> None:
    router = AgentRouter()

    ignored = router.route(summary(mentioned=False))
    direct = router.route(summary())
    tool = router.route(
        summary(), requested_tool="GROUP.GET_MEMBERS", tool_arguments={"limit": 10}
    )
    subagent = router.route(summary(text="整理群成员"), requested_subagent="research")

    assert (ignored.kind, ignored.reason) == (RouteKind.IGNORE, "bot_not_mentioned")
    assert (direct.kind, direct.reason) == (
        RouteKind.DIRECT,
        "no_tool_or_subagent_requested",
    )
    assert tool.kind is RouteKind.TOOL
    assert tool.target == "group.get_members"
    assert dict(tool.arguments) == {"limit": 10}
    assert (subagent.kind, subagent.reason) == (
        RouteKind.SUBAGENT,
        "explicit_subagent_request",
    )


def test_background_route_can_use_a_tool_without_a_mention() -> None:
    route = AgentRouter().route(
        summary(mentioned=False),
        requested_tool="sticker.search",
        allow_unmentioned=True,
    )

    assert route.kind is RouteKind.TOOL
    assert route.target == "sticker.search"


def test_planner_builds_tool_and_restricted_subagent_steps() -> None:
    router = AgentRouter()
    planner = AgentPlanner()

    tool_plan = planner.build(
        router.route(summary(), requested_tool="group.get_members"),
        plan_id="tool-plan",
    )
    subagent_plan = planner.build(
        router.route(summary(text="整理"), requested_subagent="research"),
        subagent_tools={"research": ("group.get_members",)},
    )

    assert tool_plan.steps[0].kind is StepKind.TOOL
    assert tool_plan.steps[0].target == "group.get_members"
    assert subagent_plan.steps[0].kind is StepKind.SUBAGENT
    assert subagent_plan.steps[0].allowed_tools == ("group.get_members",)


def test_subagent_cannot_be_given_outbound_message_tool() -> None:
    with pytest.raises(ValueError, match="outbound message"):
        TaskStep(
            "subagent-1",
            StepKind.SUBAGENT,
            "research",
            {"task": "整理"},
            allowed_tools=("message.send",),
        )


def test_orchestrator_runs_serial_tools_and_summarizes() -> None:
    calls: list[str] = []
    plan = AgentPlan(
        AgentRouter().route(summary(), requested_tool="group.get_members"),
        steps=(
            TaskStep("one", StepKind.TOOL, "group.get_members"),
            TaskStep("two", StepKind.TOOL, "group.get_members"),
        ),
    )

    async def invoke(step: TaskStep) -> object:
        calls.append(step.step_id)
        return {"step": step.step_id}

    result = asyncio.run(AgentOrchestrator().run(plan, tool_executor=invoke))

    assert result.status is RunStatus.SUCCESS
    assert result.summary == "tool route completed 2 step(s)"
    assert calls == ["one", "two"]
    assert [outcome.value for outcome in result.outcomes] == [
        {"step": "one"},
        {"step": "two"},
    ]


def test_orchestrator_stops_at_step_limit() -> None:
    calls: list[str] = []
    route = AgentRouter().route(summary(), requested_tool="group.get_members")
    plan = AgentPlan(
        route,
        steps=tuple(
            TaskStep(str(index), StepKind.TOOL, "group.get_members")
            for index in range(3)
        ),
    )

    async def invoke(step: TaskStep) -> object:
        calls.append(step.step_id)
        return "ok"

    result = asyncio.run(
        AgentOrchestrator(AgentBudget(max_steps=2)).run(plan, tool_executor=invoke)
    )

    assert result.status is RunStatus.STEP_LIMIT
    assert calls == ["0", "1"]
    assert "2 of 3" in result.summary


def test_orchestrator_caps_parallel_group_concurrency() -> None:
    active = 0
    peak = 0
    route = AgentRouter().route(summary(), requested_tool="group.get_members")
    plan = AgentPlan(
        route,
        steps=tuple(
            TaskStep(
                str(index),
                StepKind.TOOL,
                "group.get_members",
                parallel_group="readers",
            )
            for index in range(4)
        ),
    )

    async def invoke(step: TaskStep) -> object:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return step.step_id

    result = asyncio.run(
        AgentOrchestrator(AgentBudget(max_concurrency=2)).run(
            plan, tool_executor=invoke
        )
    )

    assert result.status is RunStatus.SUCCESS
    assert peak == 2


def test_orchestrator_converges_after_tool_failure() -> None:
    calls: list[str] = []
    route = AgentRouter().route(summary(), requested_tool="group.get_members")
    plan = AgentPlan(
        route,
        steps=(
            TaskStep("one", StepKind.TOOL, "group.get_members"),
            TaskStep("two", StepKind.TOOL, "group.get_members"),
        ),
    )

    async def invoke(step: TaskStep) -> object:
        calls.append(step.step_id)
        if step.step_id == "one":
            raise RuntimeError("private platform details")
        return "unreachable"

    result = asyncio.run(AgentOrchestrator().run(plan, tool_executor=invoke))

    assert result.status is RunStatus.FAILED
    assert result.summary == "step one failed: RuntimeError"
    assert calls == ["one"]
    assert result.outcomes[0].error == "RuntimeError"


def test_orchestrator_applies_total_timeout() -> None:
    plan = AgentPlan(
        AgentRouter().route(summary(), requested_tool="group.get_members"),
        steps=(TaskStep("one", StepKind.TOOL, "group.get_members"),),
    )

    async def invoke(step: TaskStep) -> object:
        await asyncio.sleep(0.05)
        return "late"

    result = asyncio.run(
        AgentOrchestrator(AgentBudget(timeout_seconds=0.001)).run(
            plan, tool_executor=invoke
        )
    )

    assert result.status is RunStatus.TIMEOUT
    assert result.outcomes == ()


def test_orchestrator_restricts_subagent_to_result_only() -> None:
    plan = AgentPlan(
        AgentRouter().route(summary(text="整理"), requested_subagent="research"),
        steps=(
            TaskStep(
                "subagent-1",
                StepKind.SUBAGENT,
                "research",
                {"task": "整理"},
                allowed_tools=("group.get_members",),
            ),
        ),
    )
    received: list[tuple[str, tuple[str, ...]]] = []

    async def invoke(request: SubAgentRequest) -> SubAgentResult:
        received.append((request.name, request.allowed_tools))
        return SubAgentResult(True, "已整理", used_tools=request.allowed_tools)

    result = asyncio.run(AgentOrchestrator().run(plan, subagent_executor=invoke))

    assert result.status is RunStatus.SUCCESS
    assert result.outcomes[0].value == "已整理"
    assert received == [("research", ("group.get_members",))]
