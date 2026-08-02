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

STICKER_CONSIDER = ToolDefinition(
    name="sticker.consider",
    description=(
        "After viewing the current message image, decide whether to save it "
        "with meaning and tags."
    ),
    permission="sticker.consider",
    parameters=(
        ParameterSpec("should_collect", ParameterType.BOOLEAN),
        ParameterSpec("meaning", ParameterType.STRING, required=False, max_length=500),
        ParameterSpec("tags", ParameterType.ARRAY, required=False),
        ParameterSpec(
            "image_index",
            ParameterType.INTEGER,
            required=False,
            minimum=0,
            maximum=8,
        ),
        ParameterSpec(
            "confidence",
            ParameterType.NUMBER,
            required=False,
            minimum=0,
            maximum=1,
        ),
    ),
    risk=ToolRisk.LOW,
)

STICKER_SEARCH = ToolDefinition(
    name="sticker.search",
    description="Search the current group's saved stickers by meaning or tags.",
    permission="sticker.search",
    parameters=(
        ParameterSpec("query", ParameterType.STRING, required=False, max_length=200),
        ParameterSpec(
            "limit", ParameterType.INTEGER, required=False, minimum=1, maximum=20
        ),
    ),
    risk=ToolRisk.LOW,
)

STICKER_SEND = ToolDefinition(
    name="sticker.send",
    description="Send one saved sticker to the current group.",
    permission="sticker.send",
    parameters=(
        ParameterSpec("sticker_id", ParameterType.STRING, min_length=1, max_length=100),
    ),
    risk=ToolRisk.MEDIUM,
)

MEMORY_REMEMBER = ToolDefinition(
    name="memory.remember",
    description="Store one explicit, scoped fact or preference for later recall.",
    permission="memory.write",
    parameters=(
        ParameterSpec("scope", ParameterType.STRING, required=False, max_length=16),
        ParameterSpec("topic", ParameterType.STRING, min_length=1, max_length=120),
        ParameterSpec("content", ParameterType.STRING, min_length=1, max_length=1000),
        ParameterSpec("kind", ParameterType.STRING, required=False, max_length=20),
        ParameterSpec("tags", ParameterType.ARRAY, required=False),
        ParameterSpec(
            "confidence",
            ParameterType.NUMBER,
            required=False,
            minimum=0,
            maximum=1,
        ),
        ParameterSpec(
            "expires_days",
            ParameterType.INTEGER,
            required=False,
            minimum=1,
            maximum=3650,
        ),
    ),
    risk=ToolRisk.LOW,
)

MEMORY_RECALL = ToolDefinition(
    name="memory.recall",
    description="Search memories visible to the current actor and group.",
    permission="memory.read",
    parameters=(
        ParameterSpec("query", ParameterType.STRING, required=False, max_length=200),
        ParameterSpec(
            "limit", ParameterType.INTEGER, required=False, minimum=1, maximum=20
        ),
    ),
    risk=ToolRisk.LOW,
)

MEMORY_FORGET = ToolDefinition(
    name="memory.forget",
    description="Forget one visible memory record without deleting its history.",
    permission="memory.forget",
    parameters=(
        ParameterSpec("memory_id", ParameterType.STRING, min_length=1, max_length=100),
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
    STICKER_CONSIDER,
    STICKER_SEARCH,
    STICKER_SEND,
    MEMORY_REMEMBER,
    MEMORY_RECALL,
    MEMORY_FORGET,
)
