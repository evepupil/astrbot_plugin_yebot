"""Single execution gate for all YeBot tools."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from ...domain.permissions import (
    TOOL_PERMISSION_POLICIES,
    CapabilityPolicy,
    PermissionDecisionCode,
    authorize,
)
from ..guardrails import GuardrailCode, GuardrailManager
from ..release import RuntimeMetrics
from .models import (
    ToolContext,
    ToolResult,
    ToolResultCode,
    validate_parameters,
)
from .registry import ToolRegistry

_PERMISSION_RESULT_CODES: Mapping[PermissionDecisionCode, ToolResultCode] = {
    PermissionDecisionCode.ROLE_DENIED: ToolResultCode.ROLE_DENIED,
    PermissionDecisionCode.OUT_OF_SCOPE: ToolResultCode.OUT_OF_SCOPE,
    PermissionDecisionCode.GROUP_REQUIRED: ToolResultCode.GROUP_REQUIRED,
    PermissionDecisionCode.UNKNOWN_CAPABILITY: ToolResultCode.UNKNOWN_PERMISSION,
}

_GUARDRAIL_RESULT_CODES: Mapping[GuardrailCode, ToolResultCode] = {
    GuardrailCode.CONFIRMATION_REQUIRED: ToolResultCode.CONFIRMATION_REQUIRED,
    GuardrailCode.INVALID_CONFIRMATION: ToolResultCode.INVALID_CONFIRMATION,
    GuardrailCode.CONFIRMATION_EXPIRED: ToolResultCode.CONFIRMATION_EXPIRED,
    GuardrailCode.CONFIRMATION_REPLAYED: ToolResultCode.CONFIRMATION_REPLAYED,
    GuardrailCode.QUOTA_EXCEEDED: ToolResultCode.QUOTA_EXCEEDED,
    GuardrailCode.CONCURRENCY_LIMIT: ToolResultCode.CONCURRENCY_LIMIT,
    GuardrailCode.TARGET_PROTECTED: ToolResultCode.TARGET_PROTECTED,
}


class ToolGateway:
    """Authorize, validate, time-limit, and wrap every tool invocation."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_policies: Mapping[str, CapabilityPolicy] = TOOL_PERMISSION_POLICIES,
        guardrails: GuardrailManager | None = None,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self._registry = registry
        self._permission_policies = permission_policies
        self._guardrails = guardrails
        self._metrics = metrics

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | object,
        context: ToolContext,
    ) -> ToolResult:
        """Run one registered tool or return a stable failure envelope."""

        normalized_name = tool_name.strip().lower()
        if self._metrics is not None:
            self._metrics.record_tool(normalized_name, "called")
        registered = self._registry.resolve(normalized_name)
        if registered is None:
            return ToolResult(normalized_name, ToolResultCode.UNKNOWN_TOOL)

        definition = registered.definition
        policies: Mapping[str, CapabilityPolicy] = self._permission_policies
        if definition.permission_policy is not None:
            policies = {definition.permission: definition.permission_policy}
        decision = authorize(
            context.identity,
            definition.permission,
            target_group_id=context.target_group_id,
            policies=policies,
        )
        if not decision.allowed:
            return ToolResult(
                definition.name,
                _PERMISSION_RESULT_CODES[decision.code],
                permission=decision,
            )

        validation_errors = validate_parameters(definition, arguments)
        if validation_errors:
            return ToolResult(
                definition.name,
                ToolResultCode.INVALID_PARAMETERS,
                error="; ".join(validation_errors),
                permission=decision,
            )

        effective_context = replace(
            context,
            target_group_id=decision.target_group_id or None,
        )
        validated_arguments = cast(Mapping[str, object], arguments)
        if self._guardrails is not None:
            guardrail = self._guardrails.begin(
                definition.name,
                validated_arguments,
                context.identity,
                request_id=context.request_id,
                confirmation_token=context.confirmation_token,
            )
            if guardrail.code is GuardrailCode.IDEMPOTENT_REPLAY:
                cached = guardrail.cached_result
                if isinstance(cached, ToolResult):
                    return ToolResult(
                        definition.name,
                        ToolResultCode.IDEMPOTENT_REPLAY,
                        value=cached.value,
                        error=cached.error,
                        permission=cached.permission,
                    )
            if not guardrail.allowed:
                value: object | None = None
                if guardrail.pending is not None:
                    value = {
                        "confirmation_id": guardrail.pending.token,
                        "tool": guardrail.pending.tool_name,
                        "expires_at": guardrail.pending.expires_at.isoformat(),
                        "target_user_id": guardrail.pending.arguments.get(
                            "user_id", ""
                        ),
                    }
                return ToolResult(
                    definition.name,
                    _GUARDRAIL_RESULT_CODES.get(
                        guardrail.code, ToolResultCode.EXECUTION_ERROR
                    ),
                    value=value,
                    error=guardrail.code.value,
                    permission=decision,
                )
        try:
            value = await asyncio.wait_for(
                registered.handler(effective_context, validated_arguments),
                timeout=definition.timeout_seconds,
            )
        except TimeoutError:
            if self._guardrails is not None:
                self._guardrails.complete(
                    definition.name,
                    validated_arguments,
                    context.identity,
                    request_id=context.request_id,
                    outcome="timeout",
                )
            return ToolResult(
                definition.name,
                ToolResultCode.TIMEOUT,
                error="tool timed out",
                permission=decision,
            )
        except Exception as error:
            if self._guardrails is not None:
                self._guardrails.complete(
                    definition.name,
                    validated_arguments,
                    context.identity,
                    request_id=context.request_id,
                    outcome="execution_error",
                )
            return ToolResult(
                definition.name,
                ToolResultCode.EXECUTION_ERROR,
                error=type(error).__name__,
                permission=decision,
            )
        result = ToolResult(
            definition.name,
            ToolResultCode.SUCCESS,
            value=value,
            permission=decision,
        )
        if self._guardrails is not None:
            self._guardrails.complete(
                definition.name,
                validated_arguments,
                context.identity,
                request_id=context.request_id,
                result=result,
            )
        return result

    async def confirm(
        self,
        confirmation_id: str,
        context: ToolContext,
    ) -> ToolResult:
        """Execute a pending proposal after the original actor confirms it."""

        if self._guardrails is None:
            return ToolResult(
                "confirmation",
                ToolResultCode.INVALID_CONFIRMATION,
                error="guardrails_unavailable",
            )
        pending = self._guardrails.pending(confirmation_id)
        if pending is None:
            return ToolResult(
                "confirmation",
                (
                    ToolResultCode.CONFIRMATION_REPLAYED
                    if self._guardrails.was_consumed(confirmation_id)
                    else ToolResultCode.CONFIRMATION_EXPIRED
                ),
                error="confirmation_replayed"
                if self._guardrails.was_consumed(confirmation_id)
                else "confirmation_not_found_or_expired",
            )
        registered = self._registry.resolve(pending.tool_name)
        if registered is None:
            return ToolResult(
                pending.tool_name,
                ToolResultCode.UNKNOWN_TOOL,
                error="pending_tool_unavailable",
            )
        confirmed_context = replace(
            context,
            request_id=pending.request_id or context.request_id,
            confirmation_token=confirmation_id.strip(),
        )
        return await self.execute(
            pending.tool_name,
            pending.arguments,
            confirmed_context,
        )
