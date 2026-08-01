"""Bounded plan execution with failure convergence and result summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Protocol

from .models import (
    AgentBudget,
    AgentPlan,
    AgentRunResult,
    RunStatus,
    StepKind,
    StepOutcome,
    SubAgentRequest,
    SubAgentResult,
    TaskStep,
)


class ToolExecutor(Protocol):
    def __call__(self, step: TaskStep) -> Awaitable[object]: ...


class SubAgentExecutor(Protocol):
    def __call__(self, request: SubAgentRequest) -> Awaitable[SubAgentResult]: ...


class AgentOrchestrator:
    """Execute a plan without exposing platform clients to the plan itself."""

    def __init__(self, budget: AgentBudget | None = None) -> None:
        self.budget = budget or AgentBudget()

    async def run(
        self,
        plan: AgentPlan,
        *,
        tool_executor: ToolExecutor | None = None,
        subagent_executor: SubAgentExecutor | None = None,
    ) -> AgentRunResult:
        try:
            outcomes = await asyncio.wait_for(
                self._run_steps(
                    plan,
                    tool_executor=tool_executor,
                    subagent_executor=subagent_executor,
                ),
                timeout=self.budget.timeout_seconds,
            )
        except TimeoutError:
            return AgentRunResult(
                RunStatus.TIMEOUT,
                plan,
                (),
                "orchestration timed out before completion",
            )

        if len(plan.steps) > self.budget.max_steps:
            return AgentRunResult(
                RunStatus.STEP_LIMIT,
                plan,
                outcomes,
                (
                    f"step limit reached after {len(outcomes)} of "
                    f"{len(plan.steps)} step(s)"
                ),
            )
        if any(not outcome.ok for outcome in outcomes):
            failed = next(outcome for outcome in outcomes if not outcome.ok)
            return AgentRunResult(
                RunStatus.FAILED,
                plan,
                outcomes,
                (
                    f"step {failed.step.step_id} failed: "
                    f"{failed.error or 'execution_error'}"
                ),
            )
        return AgentRunResult(
            RunStatus.SUCCESS,
            plan,
            outcomes,
            self._success_summary(plan, outcomes),
        )

    async def _run_steps(
        self,
        plan: AgentPlan,
        *,
        tool_executor: ToolExecutor | None,
        subagent_executor: SubAgentExecutor | None,
    ) -> tuple[StepOutcome, ...]:
        outcomes: list[StepOutcome] = []
        for batch in _batches(plan.steps[: self.budget.max_steps]):
            if len(batch) == 1:
                outcome = await self._run_one(
                    batch[0],
                    tool_executor=tool_executor,
                    subagent_executor=subagent_executor,
                )
                outcomes.append(outcome)
                if not outcome.ok:
                    break
                continue

            semaphore = asyncio.Semaphore(self.budget.max_concurrency)

            async def guarded(
                step: TaskStep,
                *,
                batch_semaphore: asyncio.Semaphore = semaphore,
            ) -> StepOutcome:
                async with batch_semaphore:
                    return await self._run_one(
                        step,
                        tool_executor=tool_executor,
                        subagent_executor=subagent_executor,
                    )

            batch_outcomes = await asyncio.gather(*(guarded(step) for step in batch))
            outcomes.extend(batch_outcomes)
            if any(not outcome.ok for outcome in batch_outcomes):
                break
        return tuple(outcomes)

    async def _run_one(
        self,
        step: TaskStep,
        *,
        tool_executor: ToolExecutor | None,
        subagent_executor: SubAgentExecutor | None,
    ) -> StepOutcome:
        try:
            if step.kind is StepKind.TOOL:
                if tool_executor is None:
                    return StepOutcome(step, False, error="tool_executor_unavailable")
                value = await tool_executor(step)
                ok = _tool_result_ok(value)
                return StepOutcome(
                    step,
                    ok,
                    value=value if ok else None,
                    error=None if ok else _tool_result_error(value),
                )

            if subagent_executor is None:
                return StepOutcome(step, False, error="subagent_executor_unavailable")
            task = step.arguments.get("task")
            if not isinstance(task, str) or not task.strip():
                return StepOutcome(step, False, error="subagent_task_missing")
            result = await subagent_executor(
                SubAgentRequest(step.target, task, step.allowed_tools)
            )
            return StepOutcome(
                step,
                result.ok,
                value=result.summary if result.ok else None,
                error=None if result.ok else result.error or "subagent_failed",
            )
        except Exception as error:
            return StepOutcome(step, False, error=type(error).__name__)

    @staticmethod
    def _success_summary(
        plan: AgentPlan,
        outcomes: tuple[StepOutcome, ...],
    ) -> str:
        if not outcomes:
            return f"{plan.route.kind.value} route completed without tool steps"
        return f"{plan.route.kind.value} route completed {len(outcomes)} step(s)"


def _batches(steps: tuple[TaskStep, ...]) -> tuple[tuple[TaskStep, ...], ...]:
    batches: list[tuple[TaskStep, ...]] = []
    current: list[TaskStep] = []
    current_group: str | None = None
    for step in steps:
        if step.parallel_group is None:
            if current:
                batches.append(tuple(current))
                current = []
                current_group = None
            batches.append((step,))
            continue
        if current_group != step.parallel_group and current:
            batches.append(tuple(current))
            current = []
        current_group = step.parallel_group
        current.append(step)
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _tool_result_ok(value: object) -> bool:
    result_ok = getattr(value, "ok", None)
    return result_ok if isinstance(result_ok, bool) else True


def _tool_result_error(value: object) -> str:
    code = getattr(value, "code", None)
    normalized = getattr(code, "value", code)
    return str(normalized) if normalized else "tool_failed"
