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


class ToolGateway:
    """Authorize, validate, time-limit, and wrap every tool invocation."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_policies: Mapping[str, CapabilityPolicy] = TOOL_PERMISSION_POLICIES,
    ) -> None:
        self._registry = registry
        self._permission_policies = permission_policies

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | object,
        context: ToolContext,
    ) -> ToolResult:
        """Run one registered tool or return a stable failure envelope."""

        normalized_name = tool_name.strip().lower()
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
        try:
            value = await asyncio.wait_for(
                registered.handler(effective_context, validated_arguments),
                timeout=definition.timeout_seconds,
            )
        except TimeoutError:
            return ToolResult(
                definition.name,
                ToolResultCode.TIMEOUT,
                error="tool timed out",
                permission=decision,
            )
        except Exception as error:
            return ToolResult(
                definition.name,
                ToolResultCode.EXECUTION_ERROR,
                error=type(error).__name__,
                permission=decision,
            )
        return ToolResult(
            definition.name,
            ToolResultCode.SUCCESS,
            value=value,
            permission=decision,
        )
