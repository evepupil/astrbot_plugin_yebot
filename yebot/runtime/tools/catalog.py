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
    risk=ToolRisk.MEDIUM,
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

REMINDER_CREATE = ToolDefinition(
    name="reminder.create",
    description="Create a delayed reminder in the current group.",
    permission="job.reminder.create",
    parameters=(
        ParameterSpec(
            "delay_seconds",
            ParameterType.INTEGER,
            minimum=1,
            maximum=2_592_000,
        ),
        ParameterSpec("message", ParameterType.STRING, min_length=1, max_length=1000),
    ),
    risk=ToolRisk.MEDIUM,
)

REMINDER_LIST = ToolDefinition(
    name="reminder.list",
    description="List reminders visible to the current actor in this group.",
    permission="job.reminder.read",
)

REMINDER_CANCEL = ToolDefinition(
    name="reminder.cancel",
    description="Cancel one pending reminder in the current group.",
    permission="job.reminder.manage",
    parameters=(ParameterSpec("job_id", ParameterType.STRING, min_length=1),),
    risk=ToolRisk.MEDIUM,
)

REMINDER_PAUSE = ToolDefinition(
    name="reminder.pause",
    description="Pause one pending reminder in the current group.",
    permission="job.reminder.manage",
    parameters=(ParameterSpec("job_id", ParameterType.STRING, min_length=1),),
    risk=ToolRisk.MEDIUM,
)

REMINDER_RESUME = ToolDefinition(
    name="reminder.resume",
    description="Resume one paused reminder in the current group.",
    permission="job.reminder.manage",
    parameters=(ParameterSpec("job_id", ParameterType.STRING, min_length=1),),
    risk=ToolRisk.MEDIUM,
)

FILE_READ = ToolDefinition(
    name="file.read",
    description="Read a bounded text file below the configured YeBot root.",
    permission="file.read",
    parameters=(
        ParameterSpec("path", ParameterType.STRING, min_length=1, max_length=500),
        ParameterSpec(
            "max_bytes",
            ParameterType.INTEGER,
            required=False,
            minimum=1,
            maximum=100_000,
        ),
    ),
    risk=ToolRisk.LOW,
)

WEB_FETCH = ToolDefinition(
    name="web.fetch",
    description="Fetch bounded text from a public HTTP or HTTPS URL.",
    permission="web.fetch",
    parameters=(
        ParameterSpec("url", ParameterType.STRING, min_length=8, max_length=2048),
        ParameterSpec(
            "max_bytes",
            ParameterType.INTEGER,
            required=False,
            minimum=1,
            maximum=100_000,
        ),
    ),
    risk=ToolRisk.LOW,
)


TOOL_CATALOG: tuple[ToolDefinition, ...] = (
    GROUP_GET_MEMBERS,
    GROUP_KICK_MEMBER,
    GROUP_MUTE_MEMBER,
    GROUP_UNMUTE_MEMBER,
    MESSAGE_SEND,
    REMINDER_CREATE,
    REMINDER_LIST,
    REMINDER_CANCEL,
    REMINDER_PAUSE,
    REMINDER_RESUME,
    FILE_READ,
    WEB_FETCH,
)
