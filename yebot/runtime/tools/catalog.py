"""Canonical metadata for QQ-facing tools to be wired by platform adapters."""

from __future__ import annotations

from .models import ParameterSpec, ParameterType, ToolDefinition, ToolRisk

GROUP_KICK_MEMBER = ToolDefinition(
    name="group.kick_member",
    description="Remove one member from the current group.",
    permission="group.member.kick",
    parameters=(
        ParameterSpec("user_id", ParameterType.STRING, min_length=1),
        ParameterSpec("reason", ParameterType.STRING, required=False, max_length=200),
    ),
    risk=ToolRisk.HIGH,
)

GROUP_MUTE_MEMBER = ToolDefinition(
    name="group.mute_member",
    description="Mute one member in the current group for a bounded duration.",
    permission="group.member.mute",
    parameters=(
        ParameterSpec("user_id", ParameterType.STRING, min_length=1),
        ParameterSpec(
            "duration_seconds",
            ParameterType.INTEGER,
            minimum=1,
            maximum=2_592_000,
        ),
        ParameterSpec("reason", ParameterType.STRING, required=False, max_length=200),
    ),
    risk=ToolRisk.HIGH,
)

GROUP_UNMUTE_MEMBER = ToolDefinition(
    name="group.unmute_member",
    description="Remove a mute from one member in the current group.",
    permission="group.member.mute",
    parameters=(ParameterSpec("user_id", ParameterType.STRING, min_length=1),),
    risk=ToolRisk.MEDIUM,
)

GROUP_GET_MEMBERS = ToolDefinition(
    name="group.get_members",
    description="Read members of the current group.",
    permission="group.member.read",
)

MESSAGE_SEND = ToolDefinition(
    name="message.send",
    description="Send a message to the current group.",
    permission="message.send",
    parameters=(ParameterSpec("message", ParameterType.STRING, min_length=1),),
    risk=ToolRisk.MEDIUM,
)


TOOL_CATALOG: tuple[ToolDefinition, ...] = (
    GROUP_GET_MEMBERS,
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_UNMUTE_MEMBER,
    MESSAGE_SEND,
)
