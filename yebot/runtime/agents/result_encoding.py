"""Encode agent outcomes with enough detail for the next model turn."""

from __future__ import annotations

import json

from ..tools.models import ToolResult
from .models import AgentRunResult, StepOutcome


def encode_agent_run_result(result: AgentRunResult) -> str:
    """Return a model-readable run result without dropping failed tool steps."""

    steps = [_encode_step(outcome) for outcome in result.outcomes]
    successful_results = [
        _success_value(outcome) for outcome in result.outcomes if outcome.ok
    ]
    payload = {
        "status": result.status.value,
        "summary": result.summary,
        "result": (
            successful_results[0]
            if len(successful_results) == 1
            else successful_results
        ),
        "steps": steps,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def encode_tool_result(result: ToolResult) -> dict[str, object]:
    """Expose a sanitized gateway result for prehandled tool requests."""

    payload = _encode_tool_result(result)
    return payload


def _encode_step(outcome: StepOutcome) -> dict[str, object]:
    payload: dict[str, object] = {
        "step_id": outcome.step.step_id,
        "kind": outcome.step.kind.value,
        "target": outcome.step.target,
        "ok": outcome.ok,
    }
    if isinstance(outcome.value, ToolResult):
        payload.update(_encode_tool_result(outcome.value))
    elif outcome.value is not None:
        payload["result"] = outcome.value
    if outcome.error and "error" not in payload:
        payload["error"] = outcome.error
    return payload


def _success_value(outcome: StepOutcome) -> object | None:
    if isinstance(outcome.value, ToolResult):
        return outcome.value.value
    return outcome.value


def _encode_tool_result(result: ToolResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "tool": result.tool_name,
        "status": result.code.value,
        "ok": result.ok,
    }
    if result.value is not None:
        payload["result"] = result.value
    if result.error:
        payload["error"] = result.error
    if result.permission is not None:
        decision = result.permission
        payload["permission"] = {
            "capability": decision.capability,
            "role": decision.role.value,
            "target_group_id": decision.target_group_id,
            "decision": decision.code.value,
        }
    return payload
