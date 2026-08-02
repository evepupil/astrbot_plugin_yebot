"""Data contracts for YeBot's deterministic agent orchestration layer."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from ...domain.identity import UserRole


class RouteKind(StrEnum):
    """The high-level path selected for one message."""

    IGNORE = "ignore"
    DIRECT = "direct"
    TOOL = "tool"
    SUBAGENT = "subagent"


class StepKind(StrEnum):
    """The two kinds of work a plan may execute."""

    TOOL = "tool"
    SUBAGENT = "subagent"


class RunStatus(StrEnum):
    """Stable terminal states for one orchestration run."""

    SUCCESS = "success"
    FAILED = "failed"
    STEP_LIMIT = "step_limit"
    TIMEOUT = "timeout"


_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_FORBIDDEN_SUBAGENT_TOOLS = frozenset(
    {"message.send", "send_message", "sticker.send", "sticker.consider"}
)


def _mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class MessageSummary:
    """Transient facts passed to the router without retaining raw event data."""

    text: str
    user_id: str
    group_id: str
    role: UserRole
    mentioned: bool
    request_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", self.text.strip()[:4000])
        object.__setattr__(self, "user_id", self.user_id.strip())
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "request_id", self.request_id.strip())


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Explainable routing output produced before a plan is built."""

    kind: RouteKind
    reason: str
    target: str | None = None
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("route reason must not be empty")
        target = self.target.strip().lower() if self.target else None
        if target is not None and not _NAME_PATTERN.fullmatch(target):
            raise ValueError(f"invalid route target: {target!r}")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "arguments", _mapping(self.arguments))


@dataclass(frozen=True, slots=True)
class TaskStep:
    """One bounded tool or SubAgent invocation in a plan."""

    step_id: str
    kind: StepKind
    target: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    parallel_group: str | None = None
    allowed_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        step_id = self.step_id.strip()
        target = self.target.strip().lower()
        if not step_id:
            raise ValueError("step_id must not be empty")
        if not _NAME_PATTERN.fullmatch(target):
            raise ValueError(f"invalid step target: {target!r}")
        group = self.parallel_group.strip() if self.parallel_group else None
        allowed = tuple(
            sorted(
                {name.strip().lower() for name in self.allowed_tools if name.strip()}
            )
        )
        if self.kind is StepKind.SUBAGENT:
            forbidden = _FORBIDDEN_SUBAGENT_TOOLS.intersection(allowed)
            if forbidden:
                raise ValueError(
                    "SubAgent cannot access outbound message tools: "
                    + ", ".join(sorted(forbidden))
                )
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "parallel_group", group)
        object.__setattr__(self, "allowed_tools", allowed)
        object.__setattr__(self, "arguments", _mapping(self.arguments))


@dataclass(frozen=True, slots=True)
class AgentPlan:
    """Immutable plan handed to the executor."""

    route: RouteDecision
    steps: tuple[TaskStep, ...] = ()
    plan_id: str = ""

    def __post_init__(self) -> None:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step IDs must be unique")
        object.__setattr__(self, "plan_id", self.plan_id.strip())


@dataclass(frozen=True, slots=True)
class AgentBudget:
    """Hard limits applied to every plan execution."""

    max_steps: int = 6
    max_concurrency: int = 1
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")


@dataclass(frozen=True, slots=True)
class SubAgentRequest:
    """Restricted work request; it carries no outbound messaging capability."""

    name: str
    task: str
    allowed_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        allowed = tuple(
            sorted(
                {tool.strip().lower() for tool in self.allowed_tools if tool.strip()}
            )
        )
        forbidden = _FORBIDDEN_SUBAGENT_TOOLS.intersection(allowed)
        if not name or not _NAME_PATTERN.fullmatch(name):
            raise ValueError("invalid SubAgent name")
        if forbidden:
            raise ValueError(
                "SubAgent cannot access outbound message tools: "
                + ", ".join(sorted(forbidden))
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "task", self.task.strip()[:4000])
        object.__setattr__(self, "allowed_tools", allowed)


@dataclass(frozen=True, slots=True)
class SubAgentResult:
    """Sanitized result returned by a SubAgent."""

    ok: bool
    summary: str = ""
    error: str | None = None
    used_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", self.summary.strip()[:4000])
        object.__setattr__(
            self, "error", self.error.strip()[:128] if self.error else None
        )
        object.__setattr__(
            self,
            "used_tools",
            tuple(
                sorted(
                    {tool.strip().lower() for tool in self.used_tools if tool.strip()}
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Result of one plan step, with errors reduced to stable categories."""

    step: TaskStep
    ok: bool
    value: object | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Final result envelope used by the adapter and acceptance tests."""

    status: RunStatus
    plan: AgentPlan
    outcomes: tuple[StepOutcome, ...]
    summary: str

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.SUCCESS
