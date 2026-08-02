"""Explainable routing and plan construction for YeBot."""

from __future__ import annotations

from collections.abc import Mapping

from .models import (
    AgentPlan,
    MessageSummary,
    RouteDecision,
    RouteKind,
    StepKind,
    SubAgentRequest,
    TaskStep,
)


class AgentRouter:
    """Route only from explicit, already-authorized intent metadata.

    Natural-language interpretation remains AstrBot's main Agent concern. The
    YeBot boundary receives the chosen tool or SubAgent name and records why it
    followed that path, so a model cannot silently bypass the execution gate.
    """

    def route(
        self,
        summary: MessageSummary,
        *,
        requested_tool: str | None = None,
        tool_arguments: Mapping[str, object] | None = None,
        requested_subagent: str | None = None,
        allow_unmentioned: bool = False,
    ) -> RouteDecision:
        if not allow_unmentioned and not summary.mentioned and summary.group_id:
            return RouteDecision(RouteKind.IGNORE, "bot_not_mentioned")
        if requested_tool and requested_subagent:
            return RouteDecision(RouteKind.DIRECT, "ambiguous_route_request")
        if requested_tool:
            return RouteDecision(
                RouteKind.TOOL,
                "explicit_tool_request",
                target=requested_tool,
                arguments=tool_arguments or {},
            )
        if requested_subagent:
            return RouteDecision(
                RouteKind.SUBAGENT,
                "explicit_subagent_request",
                target=requested_subagent,
                arguments={"task": summary.text},
            )
        return RouteDecision(RouteKind.DIRECT, "no_tool_or_subagent_requested")


class AgentPlanner:
    """Turn a route into a small immutable plan."""

    def build(
        self,
        route: RouteDecision,
        *,
        plan_id: str = "",
        subagent_tools: Mapping[str, tuple[str, ...]] | None = None,
    ) -> AgentPlan:
        if route.kind in {RouteKind.IGNORE, RouteKind.DIRECT}:
            return AgentPlan(route, plan_id=plan_id)
        if route.kind is RouteKind.TOOL:
            if route.target is None:
                raise ValueError("tool route requires a target")
            return AgentPlan(
                route,
                steps=(
                    TaskStep(
                        step_id="tool-1",
                        kind=StepKind.TOOL,
                        target=route.target,
                        arguments=route.arguments,
                    ),
                ),
                plan_id=plan_id,
            )
        if route.target is None:
            raise ValueError("SubAgent route requires a target")
        arguments = route.arguments
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("SubAgent route requires a task")
        allowed_tools = (subagent_tools or {}).get(route.target, ())
        request = SubAgentRequest(route.target, task, allowed_tools)
        return AgentPlan(
            route,
            steps=(
                TaskStep(
                    step_id="subagent-1",
                    kind=StepKind.SUBAGENT,
                    target=request.name,
                    arguments={"task": request.task},
                    allowed_tools=request.allowed_tools,
                ),
            ),
            plan_id=plan_id,
        )
