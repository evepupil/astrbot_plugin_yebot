"""Tool declarations, parameter schemas, execution context, and results."""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias, cast

from ...domain.identity import Identity
from ...domain.permissions import CapabilityPolicy, PermissionDecision


class ToolRisk(StrEnum):
    """Risk classification consumed by the future confirmation layer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ParameterType(StrEnum):
    """JSON-like parameter types supported by the built-in validator."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"


class ToolResultCode(StrEnum):
    """Stable gateway outcomes returned to callers."""

    SUCCESS = "success"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_PARAMETERS = "invalid_parameters"
    ROLE_DENIED = "role_denied"
    OUT_OF_SCOPE = "out_of_scope"
    GROUP_REQUIRED = "group_required"
    UNKNOWN_PERMISSION = "unknown_permission"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """Validation rules for one named tool argument."""

    name: str
    kind: ParameterType
    required: bool = True
    min_length: int | None = None
    max_length: int | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"invalid parameter name: {self.name!r}")
        if self.kind is not ParameterType.STRING and (
            self.min_length is not None or self.max_length is not None
        ):
            raise ValueError("length bounds require a string parameter")
        if self.kind not in {ParameterType.INTEGER, ParameterType.NUMBER} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("numeric bounds require a number parameter")
        if self.min_length is not None and self.min_length < 0:
            raise ValueError("min_length must be non-negative")
        if self.max_length is not None and self.max_length < 0:
            raise ValueError("max_length must be non-negative")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length must not exceed max_length")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not exceed maximum")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Metadata required before a handler can be exposed through the gateway."""

    name: str
    description: str
    permission: str
    parameters: tuple[ParameterSpec, ...] = ()
    risk: ToolRisk = ToolRisk.LOW
    timeout_seconds: float = 10.0
    permission_policy: CapabilityPolicy | None = None

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"invalid tool name: {self.name!r}")
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        if not self.permission.strip():
            raise ValueError("tool permission must not be empty")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        parameter_names = [parameter.name for parameter in self.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("tool parameters must have unique names")


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Request facts passed to a handler after authorization."""

    identity: Identity
    target_group_id: str | None = None
    request_id: str = ""


ToolHandler: TypeAlias = Callable[
    [ToolContext, Mapping[str, object]], Awaitable[object]
]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Sanitized result envelope returned by the gateway."""

    tool_name: str
    code: ToolResultCode
    value: object | None = None
    error: str | None = None
    permission: PermissionDecision | None = None

    @property
    def ok(self) -> bool:
        return self.code is ToolResultCode.SUCCESS


def validate_parameters(
    definition: ToolDefinition,
    arguments: Mapping[str, object] | object,
) -> tuple[str, ...]:
    """Validate a call without coercing or mutating caller-supplied values."""

    if not isinstance(arguments, Mapping):
        return ("arguments must be an object",)

    specs = {parameter.name: parameter for parameter in definition.parameters}
    errors: list[str] = []
    for key in arguments:
        if not isinstance(key, str) or key not in specs:
            errors.append(f"unknown parameter: {key}")

    for parameter in definition.parameters:
        if parameter.name not in arguments:
            if parameter.required:
                errors.append(f"missing parameter: {parameter.name}")
            continue
        value = arguments[parameter.name]
        if not _matches_type(value, parameter.kind):
            errors.append(f"parameter {parameter.name} must be {parameter.kind.value}")
            continue
        if parameter.kind is ParameterType.STRING:
            length = len(cast(str, value))
            if parameter.min_length is not None and length < parameter.min_length:
                errors.append(f"parameter {parameter.name} is too short")
            if parameter.max_length is not None and length > parameter.max_length:
                errors.append(f"parameter {parameter.name} is too long")
        if parameter.kind in {ParameterType.INTEGER, ParameterType.NUMBER}:
            number = cast(int | float, value)
            if parameter.minimum is not None and number < parameter.minimum:
                errors.append(f"parameter {parameter.name} is below minimum")
            if parameter.maximum is not None and number > parameter.maximum:
                errors.append(f"parameter {parameter.name} is above maximum")
    return tuple(errors)


def _matches_type(value: object, kind: ParameterType) -> bool:
    if kind is ParameterType.STRING:
        return isinstance(value, str)
    if kind is ParameterType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is ParameterType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is ParameterType.BOOLEAN:
        return isinstance(value, bool)
    if kind is ParameterType.OBJECT:
        return isinstance(value, Mapping)
    if kind is ParameterType.ARRAY:
        return isinstance(value, list)
    return value is None
