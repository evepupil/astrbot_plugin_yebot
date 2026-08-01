"""Tool declarations, registry, and the single execution gateway."""

from .catalog import (
    GROUP_GET_MEMBERS,
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_UNMUTE_MEMBER,
    MESSAGE_SEND,
    TOOL_CATALOG,
)
from .gateway import ToolGateway
from .models import (
    ParameterSpec,
    ParameterType,
    ToolContext,
    ToolDefinition,
    ToolHandler,
    ToolResult,
    ToolResultCode,
    ToolRisk,
    validate_parameters,
)
from .onebot import OneBotActionClient, OneBotToolRuntime, resolve_event_action_client
from .registry import RegisteredTool, ToolRegistrationError, ToolRegistry

__all__ = [
    "ParameterSpec",
    "ParameterType",
    "GROUP_GET_MEMBERS",
    "GROUP_KICK_MEMBER",
    "GROUP_MUTE_MEMBER",
    "GROUP_UNMUTE_MEMBER",
    "MESSAGE_SEND",
    "RegisteredTool",
    "ToolContext",
    "ToolDefinition",
    "ToolGateway",
    "ToolHandler",
    "ToolRegistrationError",
    "ToolRegistry",
    "OneBotActionClient",
    "OneBotToolRuntime",
    "ToolResult",
    "ToolResultCode",
    "ToolRisk",
    "TOOL_CATALOG",
    "validate_parameters",
    "resolve_event_action_client",
]
